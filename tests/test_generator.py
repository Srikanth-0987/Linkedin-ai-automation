"""Tests for ContentGenerator: Groq, Ollama, Gemini, and automatic failovers."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.config import Config
from src.db import Database
from src.generator import ContentGenerator


@pytest.fixture
def temp_db(tmp_path):
    return Database(tmp_path / "test_gen.db")


@pytest.fixture
def test_config():
    cfg = Config()
    cfg.groq_api_key = "gsk_test_mock_key_123"
    cfg.groq_model = "llama-3.3-70b-versatile"
    cfg.ollama_base_url = "http://localhost:11434"
    cfg.ollama_model = "qwen3.5:4b"
    cfg.gemini_api_key = "mock_gemini_key"
    cfg.ai_provider = "groq"
    cfg.ai_image_generation = False
    return cfg


def test_groq_missing_api_key(temp_db):
    """Test that missing GROQ_API_KEY raises ValueError."""
    cfg = Config()
    cfg.groq_api_key = ""
    generator = ContentGenerator(cfg, temp_db)

    with pytest.raises(ValueError, match="GROQ_API_KEY is not configured"):
        generator.generate_with_groq("Test prompt")


def test_groq_generation_success(temp_db, test_config):
    """Test successful generation using mocked Groq Python SDK."""
    generator = ContentGenerator(test_config, temp_db)

    mock_choice = MagicMock()
    mock_choice.message.content = "Here is an authentic breakdown of AI agent systems. #AI #Tech"
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_completion

    with patch("groq.Groq", return_value=mock_client):
        text, model = generator.generate_with_groq("Discuss AI agents", model="llama-3.3-70b-versatile")

        assert "authentic breakdown of AI agent systems" in text
        assert model == "llama-3.3-70b-versatile"
        mock_client.chat.completions.create.assert_called_once()


def test_groq_rate_limit_and_fallback_to_ollama(temp_db, test_config):
    """Test that when Groq hits rate limit or quota exhaustion, it falls back to Ollama."""
    generator = ContentGenerator(test_config, temp_db)

    # Groq fails with rate limit or quota error
    with patch.object(generator, "generate_with_groq", side_effect=RuntimeError("Rate limit reached: 429 Too Many Requests")):
        # Ollama succeeds
        with patch.object(generator, "generate_with_ollama", return_value=("Local Ollama post content. #Tech", "qwen3.5:4b")):
            draft = generator.generate_draft(
                topic="AI Reasoning",
                context="New reasoning benchmark released.",
                category="Frontier AI",
                provider="groq",
            )

            assert draft["ai_provider"] == "ollama"
            assert draft["ai_model"] == "qwen3.5:4b"
            assert draft["fallback_used"] is True
            assert "Local Ollama post content" in draft["commentary"]

            # Verify saved in database with fallback metadata
            post = temp_db.get_post(draft["post_id"])
            assert post["fallback_used"] == 1
            assert post["ai_provider"] == "ollama"
            assert post["category"] == "Frontier AI"


def test_ollama_generation_success(temp_db, test_config):
    """Test generation with local Ollama via mocked HTTP request."""
    generator = ContentGenerator(test_config, temp_db)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": "Local Qwen post regarding Python developer tools. #Python"}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        text, model = generator.generate_with_ollama("Write a post about Python", model="qwen3.5:4b")

        assert "Local Qwen post" in text
        assert model == "qwen3.5:4b"
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "http://localhost:11434/api/generate" in call_url


def test_safe_operation_when_cloud_unavailable_default_ollama(temp_db):
    """Test completely offline ₹0 operation using only local Ollama."""
    cfg = Config()
    cfg.groq_api_key = ""
    cfg.gemini_api_key = ""
    cfg.ai_provider = "ollama"
    cfg.ollama_model = "qwen3.5:4b"
    cfg.ai_image_generation = False

    generator = ContentGenerator(cfg, temp_db)

    with patch.object(generator, "generate_with_ollama", return_value=("100% Offline Local Content. #OpenSource", "qwen3.5:4b")):
        draft = generator.generate_draft(topic="Offline AI", context="Zero cloud dependencies")

        assert draft["ai_provider"] == "ollama"
        assert draft["fallback_used"] is False
        assert draft["status"] == "DRAFT"


def test_gemini_fallback_to_ollama(temp_db, test_config):
    """Test that Gemini quota failure falls back to local Ollama."""
    test_config.ai_provider = "gemini"
    generator = ContentGenerator(test_config, temp_db)

    with patch.object(generator, "generate_with_gemini", side_effect=RuntimeError("Resource has been exhausted (quota)")):
        with patch.object(generator, "generate_with_ollama", return_value=("Fallback content from Ollama. #AI", "qwen3.5:4b")):
            draft = generator.generate_draft(topic="DeepMind Innovation", provider="gemini")

            assert draft["ai_provider"] == "ollama"
            assert draft["fallback_used"] is True


def test_enforce_word_limit_concise_post():
    """Verify word limit enforcement preserves hashtags and caps at max_words (180)."""
    from src.generator import enforce_word_limit

    # Create a 250-word verbose text
    body = " ".join(["word"] * 240) + ". Key takeaway for engineers."
    hashtags = " #AI #Python #SoftwareEngineering #MachineLearning"
    verbose_text = body + hashtags

    trimmed = enforce_word_limit(verbose_text, max_words=180)
    trimmed_words = trimmed.split()

    assert len(trimmed_words) <= 180
    assert "#AI" in trimmed
    assert "#Python" in trimmed


def test_post_prompt_structure_guidelines():
    """Verify prompt guidelines strictly mandate 80-150 words and structured sections."""
    from src.generator import POST_PROMPT_TEMPLATE

    assert "80–150 words" in POST_PROMPT_TEMPLATE
    assert "maximum 180 words" in POST_PROMPT_TEMPLATE
    assert "hook" in POST_PROMPT_TEMPLATE.lower()
    assert "why it matters" in POST_PROMPT_TEMPLATE.lower()
    assert "takeaway" in POST_PROMPT_TEMPLATE.lower()
    assert "closing question" in POST_PROMPT_TEMPLATE.lower()
    assert "hashtags" in POST_PROMPT_TEMPLATE.lower()
    assert "Never fabricate" in POST_PROMPT_TEMPLATE


def test_automatic_image_generation_with_draft(temp_db, test_config, tmp_path):
    """Verify generate_draft automatically generates and attaches 1200x1200px PNG image."""
    test_config.images_dir = tmp_path / "images"
    test_config.images_dir.mkdir(parents=True, exist_ok=True)
    generator = ContentGenerator(test_config, temp_db)

    with patch.object(generator, "generate_with_ollama", return_value=(
        "Recent breakthroughs in vector search indexing algorithms have dramatically improved query latency.\n"
        "- HNSW graphs provide logarithmic search complexity.\n"
        "- Product quantization cuts memory footprint by 75%.\n"
        "- Enables real-time RAG under high production concurrency.\n"
        "How is your team optimizing search? #AI #Search #Python #Engineering",
        "qwen3.5:4b"
    )):
        draft = generator.generate_draft(
            topic="HNSW Vector Indexing Breakthrough",
            context="High-dimensional vector search optimization",
            category="Machine Learning",
            provider="ollama",
        )

        assert draft["post_id"] is not None
        assert "image" in draft
        assert draft["image"]["validation_status"] == "VALIDATED"
        assert Path(draft["image"]["image_path"]).exists()

        # Verify SQLite record has image attached
        post = temp_db.get_post(draft["post_id"])
        assert post["image_path"] == draft["image"]["image_path"]
        assert post["image_width"] == 1200
        assert post["image_height"] == 1200
        assert post["image_hash"] is not None


def test_scripted_text_only_draft_generation(temp_db, test_config):
    """Verify generate_draft with generate_image=False creates clean text-only post without image."""
    generator = ContentGenerator(test_config, temp_db)

    with patch.object(generator, "generate_with_ollama", return_value=(
        "Global semiconductor foundry expansions are redefining modern AI accelerator economics.\n\n"
        "Advanced chip packaging and high-NA EUV lithography have become pivotal geopolitical assets.\n\n"
        "Takeaway: Infrastructure sovereignty is driving long-term hardware investments.\n\n"
        "What are your thoughts on global fab diversification? #Semiconductors #Hardware #AI",
        "qwen3.5:4b"
    )):
        draft = generator.generate_draft(
            topic="Semiconductor Fab Expansion Geopolitics",
            context="ASML and TSMC foundry developments",
            category="Hardware & Semiconductors",
            provider="ollama",
            generate_image=False,
        )

        assert draft["post_id"] is not None
        assert draft["image"] == {}

        post = temp_db.get_post(draft["post_id"])
        assert post["image_path"] is None
        assert post["image_hash"] is None
        assert "foundry expansions" in post["commentary"]

