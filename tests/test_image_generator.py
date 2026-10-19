"""Tests for local Pillow-based graphics engine, image quality validation, and layouts."""

from pathlib import Path
from PIL import Image, ImageDraw
import pytest

from unittest.mock import MagicMock, patch
from io import BytesIO

from src.config import Config
from src.db import Database
from src.image_generator import (
    FontManager,
    ImageGenerator,
    ImageValidator,
    extract_image_elements,
    fetch_ai_realistic_image,
    process_and_save_custom_image,
    synthesize_realistic_poster_prompt,
)


@pytest.fixture
def image_gen(tmp_path):
    cfg = Config()
    cfg.images_dir = tmp_path / "images"
    cfg.images_dir.mkdir(parents=True, exist_ok=True)
    cfg.ai_image_generation = False  # Local Pillow rendering for layout tests
    return ImageGenerator(cfg)


def test_font_manager_fallback():
    """Verify FontManager successfully returns usable fonts with fallback."""
    font_reg = FontManager.get_font(24, bold=False)
    font_bold = FontManager.get_font(32, bold=True)

    assert font_reg is not None
    assert font_bold is not None


def test_extract_image_elements_headline_and_points():
    """Verify headline extraction targets 5-9 words and derives concise points."""
    topic = "DeepMind Announces AlphaFold 3: Major Breakthrough in Molecular Biology and Drug Discovery"
    commentary = (
        "Here is the latest breakthrough in structural biology.\n"
        "- Predicts interactions across DNA, RNA, and ligands with high precision.\n"
        "- Reduces wet-lab experimentation cycles by an order of magnitude.\n"
        "- Democratizes computational biology for open-source researchers worldwide.\n"
        "What are your thoughts? #AI #Biology #DeepMind"
    )

    headline, points = extract_image_elements(topic=topic, context="", commentary=commentary)

    # Headline should be punchy (5-9 words)
    words = headline.split()
    assert 4 <= len(words) <= 10
    # Should extract 3 concise points from commentary
    assert len(points) == 3
    assert "DNA, RNA" in points[0]
    assert "wet-lab" in points[1]


def test_image_generation_dimensions_and_format(image_gen):
    """Verify generated image produces 1200x1200px PNG."""
    meta = image_gen.generate_image_for_post(
        post_id=101,
        topic="OpenAI Releases Reasoning Model",
        category="Artificial Intelligence",
        source_name="TechCrunch",
        headline="OpenAI Releases Next-Gen Reasoning Model",
        points=[
            "Chain-of-thought verification at inference time.",
            "Significant benchmark gains on coding benchmarks.",
            "Available via API without architectural changes.",
        ],
        template_type="editorial_highlight",
    )

    img_path = Path(meta["image_path"])
    assert img_path.exists()
    assert img_path.suffix.lower() == ".png"
    assert meta["image_width"] == 1200
    assert meta["image_height"] == 1200
    assert meta["validation_status"] == "VALIDATED"
    assert len(meta["image_hash"]) == 64  # SHA-256 hex string

    # Verify physical file with Pillow
    with Image.open(img_path) as img:
        assert img.size == (1200, 1200)
        assert img.format == "PNG"


def test_image_generation_all_templates(image_gen):
    """Verify all layout templates render without error."""
    templates = ["editorial_highlight", "architecture_diagram", "concept_card"]

    for i, tmpl in enumerate(templates):
        meta = image_gen.generate_image_for_post(
            post_id=200 + i,
            topic=f"Testing {tmpl} Template Layout",
            category="Software Engineering",
            source_name="Engineering Blog",
            points=["Step 1 Analysis", "Step 2 Synthesis", "Step 3 Execution"],
            template_type=tmpl,
        )
        assert Path(meta["image_path"]).exists()
        is_valid, _ = ImageValidator.validate(meta["image_path"])
        assert is_valid is True


def test_long_title_wrapping(image_gen):
    """Verify extremely long titles wrap properly without clipping."""
    long_topic = (
        "A Comprehensive Multi-Architecture Benchmark Analysis on High-Throughput "
        "Distributed Vector Database Retrieval Latencies Under Massive Concurrent Production Loads"
    )
    meta = image_gen.generate_image_for_post(
        post_id=301,
        topic=long_topic,
        category="Data Science",
        source_name="ArXiv",
    )

    is_valid, reason = ImageValidator.validate(meta["image_path"])
    assert is_valid is True


def test_image_validator_rejects_invalid_dimensions(tmp_path):
    """Verify ImageValidator rejects images that are not 1200x1200."""
    wrong_dim = tmp_path / "wrong.png"
    img = Image.new("RGB", (800, 600), (30, 40, 50))
    img.save(str(wrong_dim))

    is_valid, reason = ImageValidator.validate(wrong_dim)
    assert is_valid is False
    assert "Invalid dimensions" in reason


def test_image_validator_rejects_non_png(tmp_path):
    """Verify ImageValidator rejects non-PNG formats."""
    jpg_path = tmp_path / "test.jpg"
    img = Image.new("RGB", (1200, 1200), (30, 40, 50))
    img.save(str(jpg_path), format="JPEG")

    is_valid, reason = ImageValidator.validate(jpg_path)
    assert is_valid is False
    assert "PNG" in reason


def test_image_validator_rejects_blank_image(tmp_path):
    """Verify ImageValidator rejects solid-color or blank images."""
    blank_path = tmp_path / "blank.png"
    # Solid black image (stddev == 0)
    img = Image.new("RGB", (1200, 1200), (0, 0, 0))
    img.save(str(blank_path))

    is_valid, reason = ImageValidator.validate(blank_path)
    assert is_valid is False
    assert "blank or single-color" in reason


def test_image_validator_placeholder_detection():
    """Verify placeholder detection identifies forbidden placeholder tokens."""
    assert ImageValidator.check_text_for_placeholders("This is a [TODO] item") is True
    assert ImageValidator.check_text_for_placeholders("Lorem ipsum dolor sit amet") is True
    assert ImageValidator.check_text_for_placeholders("Insert your_headline_here") is True
    assert ImageValidator.check_text_for_placeholders("Clean production headline for AI agents") is False


def test_db_image_hash_duplicate_prevention(tmp_path):
    """Verify SQLite prevents publishing duplicate images."""
    db = Database(tmp_path / "test_dup_img.db")
    post_id = db.create_post("Post with graphic", topic="Graphic Topic")
    
    img_hash = "unique_image_hash_abcdef123456"
    db.attach_image_to_post(
        post_id=post_id,
        image_path=str(tmp_path / "dummy.png"),
        image_hash=img_hash,
        image_alt_text="Alt text",
    )

    # Not published yet
    assert db.is_image_hash_duplicate(img_hash) is False

    # Mark as published
    db.mark_post_published(post_id, linkedin_post_id="urn:li:share:999")
    assert db.is_image_hash_duplicate(img_hash) is True


def test_synthesize_realistic_poster_prompt_domains():
    """Verify prompt synthesis selects topic-tailored scenes across key tech domains."""
    # 1. Claude / Anthropic -> Cybernetic humanoid robot
    p_claude = synthesize_realistic_poster_prompt(
        topic="Claude Opus 5.5 Announcement",
        category="Frontier AI",
        source_name="Anthropic",
    )
    assert "cybernetic humanoid robot" in p_claude or "cybernetic robot" in p_claude

    # 2. OpenAI / GPT -> Dual scenic landscape cards
    p_openai = synthesize_realistic_poster_prompt(
        topic="OpenAI Introduces GPT-6 Sol & Luna",
        category="Artificial Intelligence",
        source_name="OpenAI",
    )
    assert "scenic" in p_openai or "sunrise" in p_openai

    # 3. Copilot / Developer Agents -> 3D desktop robot & IDE
    p_copilot = synthesize_realistic_poster_prompt(
        topic="Microsoft Copilot Revamp for Developers",
        category="Developer Tools",
        source_name="Microsoft",
    )
    assert "robot companion" in p_copilot.lower() or "ide" in p_copilot.lower()

    # 4. NVIDIA / Semiconductor -> Silicon microchip
    p_nvidia = synthesize_realistic_poster_prompt(
        topic="NVIDIA Ships Blackwell Ultra B200 Chips",
        category="Hardware & Semiconductors",
        source_name="NVIDIA",
    )
    assert "microchip" in p_nvidia or "silicon" in p_nvidia

    # 5. Policy / US-China -> Diplomatic handshake & holographic globe
    p_policy = synthesize_realistic_poster_prompt(
        topic="US & China To Discuss AI Safeguards in New York",
        category="Tech Policy",
        source_name="Reuters",
    )
    assert "handshake" in p_policy or "flags" in p_policy

    # 6. Biology / AlphaFold -> Molecular DNA
    p_bio = synthesize_realistic_poster_prompt(
        topic="DeepMind AlphaFold 3 Released",
        category="Biotechnology",
        source_name="Google DeepMind",
    )
    assert "dna" in p_bio.lower() or "protein" in p_bio.lower()


def test_synthesize_realistic_poster_prompt_for_grok():
    """Verify for_midjourney_or_grok generates rich cinematic master prompt."""
    prompt = synthesize_realistic_poster_prompt(
        topic="DeepSeek-R1 Technical Architecture",
        category="Frontier AI",
        source_name="DeepSeek",
        headline="DeepSeek-R1 Architecture Overview",
        points=["Reinforcement learning without supervised warm-up.", "Drastic reduction in compute cost."],
        for_midjourney_or_grok=True,
    )
    assert "DeepSeek-R1 Architecture Overview" in prompt
    assert "glassmorphic" in prompt
    assert "8k resolution" in prompt
    assert "Reinforcement learning" in prompt


def test_fetch_ai_realistic_image_mocked_success(tmp_path):
    """Verify fetch_ai_realistic_image processes response to 1200x1200px PNG with branded footer."""
    out_file = tmp_path / "fetched.png"

    # Create dummy 512x512 JPEG bytes to simulate API payload
    dummy_img = Image.new("RGB", (512, 512), (20, 30, 50))
    buf = BytesIO()
    dummy_img.save(buf, format="JPEG")
    fake_bytes = buf.getvalue()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = fake_bytes

    with patch("requests.get", return_value=mock_resp):
        success = fetch_ai_realistic_image("Test Prompt", out_file, timeout=5)
        assert success is True
        assert out_file.exists()

        with Image.open(out_file) as img:
            assert img.size == (1200, 1200)
            assert img.format == "PNG"

        is_valid, _ = ImageValidator.validate(out_file)
        assert is_valid is True


def test_fetch_ai_realistic_image_mocked_timeout_fallback(tmp_path):
    """Verify fetch_ai_realistic_image returns False safely when API fails or times out."""
    out_file = tmp_path / "failed.png"
    with patch("requests.get", side_effect=TimeoutError("Connection timed out")):
        success = fetch_ai_realistic_image("Test Prompt", out_file, timeout=5)
        assert success is False
        assert not out_file.exists()


def test_process_and_save_custom_image_local(tmp_path):
    """Verify processing arbitrary external images standardizes to 1200x1200px PNG."""
    src_file = tmp_path / "arbitrary.jpg"
    # Create arbitrary rectangular image (800x400)
    img = Image.new("RGB", (800, 400), (45, 60, 80))
    img.save(str(src_file), format="JPEG")

    out_file = tmp_path / "standardized.png"
    saved_path, img_hash = process_and_save_custom_image(str(src_file), out_file)

    assert saved_path.exists()
    assert len(img_hash) == 64
    with Image.open(saved_path) as res_img:
        assert res_img.size == (1200, 1200)
        assert res_img.format == "PNG"


def test_attach_custom_image_flow(image_gen, tmp_path):
    """Verify ImageGenerator.attach_custom_image creates validated asset."""
    src_file = tmp_path / "custom.png"
    img = Image.new("RGB", (1000, 1000), (30, 45, 60))
    draw = ImageDraw.Draw(img)
    draw.rectangle([100, 100, 500, 500], fill=(200, 100, 50))
    img.save(str(src_file))

    meta = image_gen.attach_custom_image(
        post_id=999,
        source_path_or_url=str(src_file),
        headline="Custom Announcement",
        category="AI",
    )

    assert meta["validation_status"] == "VALIDATED"
    assert meta["image_width"] == 1200
    assert meta["image_height"] == 1200
    assert Path(meta["image_path"]).exists()


def test_photorealistic_poster_rendering(image_gen):
    """Verify photorealistic announcement poster layout renders and validates across topics."""
    meta = image_gen.generate_image_for_post(
        post_id=888,
        topic="Claude 3.7 Sonnet Hybrid Reasoning Architecture",
        category="Frontier AI Models",
        source_name="Anthropic Lab",
        headline="Introducing Claude 3.7 Sonnet",
        points=[
            "Balances instantaneous execution with dynamic test-time reasoning.",
            "State-of-the-art results on competitive coding and math benchmarks.",
            "Enterprise-ready API with full parameter controls.",
        ],
        template_type="photorealistic_poster",
    )

    assert meta["validation_status"] == "VALIDATED"
    assert meta["image_width"] == 1200
    assert meta["image_height"] == 1200
    assert meta["template_used"] == "photorealistic_poster"
    assert Path(meta["image_path"]).exists()
    is_valid, reason = ImageValidator.validate(meta["image_path"])
    assert is_valid is True


