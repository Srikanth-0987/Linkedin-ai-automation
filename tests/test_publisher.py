"""Tests for LinkedIn post publishing, official REST Images/Posts APIs, safety gates, and error handling."""

from pathlib import Path
import time
from unittest.mock import MagicMock, patch
from PIL import Image, ImageDraw
import pytest
import requests

from src.config import Config
from src.db import Database
from src.publisher import (
    DuplicatePostError,
    LinkedInAPIError,
    LinkedInPublisher,
    PublisherError,
    PublishingDisabledError,
    TokenExpiredError,
    UnapprovedPostError,
)


@pytest.fixture
def temp_db(tmp_path):
    return Database(tmp_path / "test_pub.db")


@pytest.fixture
def active_token(temp_db):
    """Seed DB with a valid token."""
    temp_db.save_token(
        access_token="valid_access_token_123",
        expires_in=86400,
        scope="w_member_social openid profile",
        member_id="person_12345",
        member_name="Test Publisher",
    )
    return "valid_access_token_123"


@pytest.fixture
def sample_image(tmp_path):
    """Create a verified 1200x1200px PNG image."""
    img_path = tmp_path / "test_graphic.png"
    img = Image.new("RGB", (1200, 1200), (11, 15, 25))
    draw = ImageDraw.Draw(img)
    draw.rectangle([100, 100, 1100, 1100], fill=(22, 30, 49), outline=(56, 189, 248), width=3)
    draw.text((200, 200), "VERIFIED TECHNICAL HEADLINE", fill=(248, 250, 252))
    img.save(str(img_path), format="PNG")
    return img_path


def create_post_with_image(
    db: Database,
    image_path: Path,
    commentary: str = "Breakthrough in AI agent frameworks. #AI #Python",
    topic: str = "AI Agents",
    approved: bool = True,
) -> int:
    """Helper to create post with attached verified image."""
    post_id = db.create_post(commentary=commentary, topic=topic)
    db.attach_image_to_post(
        post_id=post_id,
        image_path=str(image_path),
        image_hash="sha256_mock_hash_123",
        image_alt_text="Infographic for AI Agents",
        image_width=1200,
        image_height=1200,
        validation_status="VALIDATED",
    )
    if approved:
        db.approve_post(post_id)
    return post_id


def test_dry_run_safety_gate(temp_db, active_token, sample_image):
    """Verify DRY_RUN=True prevents any external network calls and simulates media payload."""
    cfg = Config()
    cfg.dry_run = True
    cfg.publish_enabled = False
    cfg.require_approval = True

    post_id = create_post_with_image(temp_db, sample_image, "Exploring autonomous AI agents. #AI #Tech", approved=True)

    publisher = LinkedInPublisher(cfg, temp_db)

    with patch("requests.post") as mock_post, patch("requests.put") as mock_put:
        result = publisher.publish_post(post_id)

        # Ensure NO network calls were made
        mock_post.assert_not_called()
        mock_put.assert_not_called()

        assert result["success"] is True
        assert result["dry_run"] is True
        assert result["author"] == "urn:li:person:person_12345"
        assert "simulated" in result["image_urn"]
        assert "media" in result["payload"]["content"]
        assert result["payload"]["content"]["media"]["id"] == result["image_urn"]

        # Verify DB status remained APPROVED (not published)
        post = temp_db.get_post(post_id)
        assert post["status"] == "APPROVED"
        assert post["linkedin_post_id"] is None


def test_scripted_text_only_post_publication(temp_db, active_token):
    """Verify system allows publishing a scripted text-only post without requiring an image."""
    cfg = Config()
    cfg.dry_run = True
    cfg.publish_enabled = False
    cfg.require_approval = False

    # Create post WITHOUT image
    post_id = temp_db.create_post("Scripted news post without graphic", topic="ScriptedNews")
    publisher = LinkedInPublisher(cfg, temp_db)

    result = publisher.publish_post(post_id)
    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["image_path"] is None
    assert result["image_urn"] is None
    # Payload should NOT contain media block
    assert "content" not in result["payload"]
    assert result["payload"]["commentary"] == "Scripted news post without graphic"


def test_corrupted_image_blocks_publication(temp_db, active_token, tmp_path):
    """Verify invalid/corrupted image blocks publishing and marks post failed."""
    cfg = Config()
    cfg.dry_run = True
    cfg.publish_enabled = False
    cfg.require_approval = False

    bad_image_path = tmp_path / "bad.png"
    # Create invalid dimension image (e.g. 100x100)
    bad_img = Image.new("RGB", (100, 100), (0, 0, 0))
    bad_img.save(str(bad_image_path))

    post_id = temp_db.create_post("Post with bad dimensions", topic="BadImg")
    temp_db.attach_image_to_post(
        post_id=post_id,
        image_path=str(bad_image_path),
        image_hash="hash",
        image_alt_text="Alt",
    )

    publisher = LinkedInPublisher(cfg, temp_db)
    with pytest.raises(PublisherError, match="image failed pre-publication quality check"):
        publisher.publish_post(post_id)

    post = temp_db.get_post(post_id)
    assert post["status"] == "FAILED"


def test_publishing_disabled_safety_gate(temp_db, active_token, sample_image):
    """Verify PUBLISH_ENABLED=False blocks live publication when DRY_RUN=False."""
    cfg = Config()
    cfg.dry_run = False
    cfg.publish_enabled = False
    cfg.require_approval = True

    post_id = create_post_with_image(temp_db, sample_image, "Live post attempt while disabled.", approved=True)

    publisher = LinkedInPublisher(cfg, temp_db)

    with patch("requests.post") as mock_post:
        with pytest.raises(PublishingDisabledError, match="Live publishing is currently disabled"):
            publisher.publish_post(post_id)

        mock_post.assert_not_called()


def test_require_approval_safety_gate(temp_db, active_token, sample_image):
    """Verify unapproved DRAFT posts are blocked when REQUIRE_APPROVAL=True."""
    cfg = Config()
    cfg.dry_run = True
    cfg.require_approval = True

    # Post created as DRAFT, NOT approved
    post_id = create_post_with_image(temp_db, sample_image, "Draft content waiting for review.", approved=False)

    publisher = LinkedInPublisher(cfg, temp_db)
    with pytest.raises(UnapprovedPostError, match="status is 'DRAFT'.*Approve this post first"):
        publisher.publish_post(post_id)


def test_duplicate_prevention_already_published(temp_db, active_token, sample_image):
    """Verify already published posts cannot be republished."""
    cfg = Config()
    cfg.dry_run = True
    cfg.require_approval = False

    post_id = create_post_with_image(temp_db, sample_image, "One-time announcement.")
    temp_db.mark_post_published(post_id, linkedin_post_id="urn:li:share:existing_123")

    publisher = LinkedInPublisher(cfg, temp_db)
    with pytest.raises(DuplicatePostError, match="already been published to LinkedIn"):
        publisher.publish_post(post_id)


def test_token_expired_gate(temp_db, sample_image):
    """Verify expired token blocks publishing and requests reauthorization."""
    temp_db.save_token(
        access_token="expired_token",
        expires_in=-3600,
        member_id="person_12345",
    )

    cfg = Config()
    cfg.dry_run = False
    cfg.publish_enabled = True
    cfg.require_approval = False

    post_id = create_post_with_image(temp_db, sample_image, "Test post with expired token")

    publisher = LinkedInPublisher(cfg, temp_db)
    with pytest.raises(TokenExpiredError, match="expired.*Please re-authenticate"):
        publisher.publish_post(post_id)


def test_missing_token_gate(temp_db, sample_image):
    """Verify missing token blocks publishing."""
    cfg = Config()
    cfg.dry_run = False
    cfg.publish_enabled = True
    cfg.require_approval = False

    post_id = create_post_with_image(temp_db, sample_image, "Test post with no token")

    publisher = LinkedInPublisher(cfg, temp_db)
    with pytest.raises(TokenExpiredError, match="No LinkedIn access token found"):
        publisher.publish_post(post_id)


def test_publish_success_flow(temp_db, active_token, sample_image):
    """Test full publishing flow: Image upload initialization, binary PUT, and REST Posts API with media."""
    cfg = Config()
    cfg.dry_run = False
    cfg.publish_enabled = True
    cfg.require_approval = True
    cfg.linkedin_api_version = "202601"

    post_id = create_post_with_image(temp_db, sample_image, "Official breakthrough in multi-agent LLM systems.", approved=True)

    # 1. Mock Images initializeUpload response
    mock_init_resp = MagicMock()
    mock_init_resp.status_code = 200
    mock_init_resp.json.return_value = {
        "value": {
            "uploadUrl": "https://api.linkedin.com/mediaUpload/12345",
            "image": "urn:li:image:D4E10AQF1234567890",
            "uploadUrlExpiresAt": int(time.time()) + 3600,
        }
    }

    # 2. Mock binary PUT response
    mock_put_resp = MagicMock()
    mock_put_resp.status_code = 201

    # 3. Mock Posts API response
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 201
    mock_post_resp.headers = {"x-restli-id": "urn:li:share:7123456789012345678"}

    publisher = LinkedInPublisher(cfg, temp_db)

    with patch("requests.post", side_effect=[mock_init_resp, mock_post_resp]) as mock_post, \
         patch("requests.put", return_value=mock_put_resp) as mock_put:
        
        result = publisher.publish_post(post_id)

        assert result["success"] is True
        assert result["linkedin_post_id"] == "urn:li:share:7123456789012345678"
        assert result["image_urn"] == "urn:li:image:D4E10AQF1234567890"

        # Verify Images API initialization call
        init_call = mock_post.call_args_list[0]
        assert "rest/images?action=initializeUpload" in init_call[0][0]
        assert init_call[1]["json"]["initializeUploadRequest"]["owner"] == "urn:li:person:person_12345"
        assert init_call[1]["headers"]["LinkedIn-Version"] == "202601"

        # Verify binary PUT call
        mock_put.assert_called_once()
        assert mock_put.call_args[0][0] == "https://api.linkedin.com/mediaUpload/12345"
        assert mock_put.call_args[1]["headers"]["Content-Type"] == "image/png"

        # Verify Posts API call
        posts_call = mock_post.call_args_list[1]
        assert posts_call[0][0] == "https://api.linkedin.com/rest/posts"
        payload = posts_call[1]["json"]
        assert payload["author"] == "urn:li:person:person_12345"
        assert payload["content"]["media"]["id"] == "urn:li:image:D4E10AQF1234567890"
        assert payload["content"]["media"]["altText"] == "Infographic for AI Agents"

        # Verify DB state
        post = temp_db.get_post(post_id)
        assert post["status"] == "PUBLISHED"
        assert post["linkedin_post_id"] == "urn:li:share:7123456789012345678"
        assert post["image_urn"] == "urn:li:image:D4E10AQF1234567890"


def test_publish_api_errors(temp_db, active_token, sample_image):
    """Test 401 Unauthorized, 403 Forbidden, and 429 Rate Limit error handling."""
    cfg = Config()
    cfg.dry_run = False
    cfg.publish_enabled = True
    cfg.require_approval = False

    publisher = LinkedInPublisher(cfg, temp_db)

    # 1. Test 401 Unauthorized during image upload
    post_id_1 = create_post_with_image(temp_db, sample_image, "401 Test Post", topic="401")
    mock_401 = MagicMock()
    mock_401.status_code = 401
    mock_401.text = "Unauthorized"
    mock_401.json.return_value = {"message": "Expired token"}

    with patch("requests.post", return_value=mock_401):
        with pytest.raises(LinkedInAPIError) as exc_info:
            publisher.publish_post(post_id_1)
        assert exc_info.value.status_code == 401
        assert temp_db.get_post(post_id_1)["status"] == "FAILED"

    # 2. Test 403 Forbidden
    post_id_2 = create_post_with_image(temp_db, sample_image, "403 Test Post", topic="403")
    mock_403 = MagicMock()
    mock_403.status_code = 403
    mock_403.text = "Forbidden"
    mock_403.json.return_value = {"message": "Not enough permissions to access /posts"}

    with patch("requests.post", return_value=mock_403):
        with pytest.raises(LinkedInAPIError) as exc_info:
            publisher.publish_post(post_id_2)
        assert exc_info.value.status_code == 403
        assert temp_db.get_post(post_id_2)["status"] == "FAILED"

    # 3. Test 429 Rate Limit
    post_id_3 = create_post_with_image(temp_db, sample_image, "429 Test Post", topic="429")
    mock_429 = MagicMock()
    mock_429.status_code = 429
    mock_429.text = "Too Many Requests"
    mock_429.json.return_value = {"message": "Resource level rate limit exceeded"}

    with patch("requests.post", return_value=mock_429):
        with pytest.raises(LinkedInAPIError) as exc_info:
            publisher.publish_post(post_id_3)
        assert exc_info.value.status_code == 429
        assert temp_db.get_post(post_id_3)["status"] == "FAILED"


def test_publish_timeout_no_blind_retry(temp_db, active_token, sample_image):
    """Test timeout handling: do not retry blindly to avoid creating duplicate posts."""
    cfg = Config()
    cfg.dry_run = False
    cfg.publish_enabled = True
    cfg.require_approval = False

    post_id = create_post_with_image(temp_db, sample_image, "Timeout Test Post", topic="Timeout")
    publisher = LinkedInPublisher(cfg, temp_db)

    # Provide image_urn so it attempts to connect to Posts API
    temp_db.update_post_image_urn(post_id, "urn:li:image:pre_uploaded_123")

    with patch("requests.post", side_effect=requests.Timeout("Connection timed out")):
        with pytest.raises(PublisherError, match="timed out.*will not retry automatically"):
            publisher.publish_post(post_id)

        post = temp_db.get_post(post_id)
        assert post["status"] == "FAILED"
        assert "timed out" in post["error_message"]
