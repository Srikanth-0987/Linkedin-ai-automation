"""Tests for configuration, secret redaction, and database operations."""

import pytest

from src.config import Config, redact_secret
from src.db import Database


def test_secret_redaction():
    """Test that secrets and tokens are masked properly."""
    assert redact_secret(None) == "[NOT SET]"
    assert redact_secret("") == "[NOT SET]"
    assert redact_secret("short") == "[REDACTED]"
    
    # Standard token format (using generic mock string to avoid secret scanner false positives)
    token = "MOCK_TOKEN_XYZ_1234567890_TEST_SAMPLE_FOR_REDACTION"
    redacted = redact_secret(token, visible_chars=4)
    assert redacted.startswith("MOCK")
    assert redacted.endswith("TION")
    assert "[REDACTED]" in redacted
    assert "1234567890" not in redacted


def test_config_safety_defaults(monkeypatch):
    """Test that default configuration enforces safe values."""
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.delenv("PUBLISH_ENABLED", raising=False)
    monkeypatch.delenv("REQUIRE_APPROVAL", raising=False)

    cfg = Config()
    assert cfg.dry_run is True
    assert cfg.publish_enabled is False
    assert cfg.require_approval is True


def test_database_oauth_state_lifecycle(tmp_path):
    """Test state saving, validation, replay prevention, and expiration."""
    db = Database(tmp_path / "state_test.db")

    # 1. Unknown state fails
    is_valid, msg = db.validate_and_consume_state("non_existent_state")
    assert is_valid is False
    assert "Unknown or forged" in msg

    # 2. Valid state passes
    db.save_oauth_state("valid_state_123", ttl_seconds=60)
    is_valid, msg = db.validate_and_consume_state("valid_state_123")
    assert is_valid is True

    # 3. Replay attack: State already consumed
    is_valid, msg = db.validate_and_consume_state("valid_state_123")
    assert is_valid is False
    assert "already been consumed" in msg

    # 4. Expired state
    db.save_oauth_state("expired_state_456", ttl_seconds=-10)
    is_valid, msg = db.validate_and_consume_state("expired_state_456")
    assert is_valid is False
    assert "expired" in msg


def test_database_token_storage(tmp_path):
    """Test saving and retrieving tokens and expiry checks."""
    db = Database(tmp_path / "token_test.db")

    # Initially no token
    assert db.get_token() is None
    assert db.is_token_valid() is False

    # Store token valid for 3600 seconds
    db.save_token(
        access_token="test_token_abc",
        expires_in=3600,
        scope="w_member_social openid",
        member_id="sub_12345",
        member_name="Jane Doe",
        member_email="jane@example.com",
    )

    token = db.get_token()
    assert token is not None
    assert token["access_token"] == "test_token_abc"
    assert token["member_id"] == "sub_12345"
    assert token["member_name"] == "Jane Doe"
    assert db.is_token_valid() is True

    # Store expired token
    db.save_token(
        access_token="expired_token_xyz",
        expires_in=-100,
    )
    assert db.is_token_valid() is False


def test_database_duplicate_content_detection(tmp_path):
    """Test that identical post content cannot be inserted twice."""
    db = Database(tmp_path / "dup_test.db")
    content = "Excited to share insights on AI Agentic Automation! #AI #Tech"

    post_id = db.create_post(commentary=content, topic="AI Agents")
    assert post_id > 0

    # Attempt duplicate insertion with minor whitespace variations
    content_with_spaces = "  Excited  to share insights on AI Agentic Automation!  #AI #Tech \n"
    with pytest.raises(ValueError, match="Duplicate post content detected"):
        db.create_post(commentary=content_with_spaces, topic="AI Duplicate")
