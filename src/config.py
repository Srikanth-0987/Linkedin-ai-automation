"""Configuration management for LinkedIn AI Automation.

Reads from environment variables and .env file.
Enforces safety defaults and provides secret redaction.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load .env from project root
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def redact_secret(secret: Optional[str], visible_chars: int = 4) -> str:
    """Safely redact secrets, tokens, and API keys.
    
    Ensures secrets are never printed in full in logs or CLI.
    """
    if not secret:
        return "[NOT SET]"
    s = secret.strip()
    if len(s) <= visible_chars * 2:
        return "[REDACTED]"
    return f"{s[:visible_chars]}...[REDACTED]...{s[-visible_chars:]}"


class Config:
    """Application configuration with safe defaults."""

    def __init__(self, **kwargs) -> None:
        # LinkedIn OAuth & API Credentials
        self.linkedin_client_id: str = os.getenv("LINKEDIN_CLIENT_ID", "").strip()
        self.linkedin_client_secret: str = os.getenv("LINKEDIN_CLIENT_SECRET", "").strip()
        self.linkedin_redirect_uri: str = os.getenv(
            "LINKEDIN_REDIRECT_URI", "http://localhost:8000/auth/linkedin/callback"
        ).strip()
        self.linkedin_access_token: str = os.getenv("LINKEDIN_ACCESS_TOKEN", "").strip()
        self.linkedin_member_id: str = os.getenv("LINKEDIN_MEMBER_ID", "").strip()
        self.linkedin_api_version: str = os.getenv("LINKEDIN_API_VERSION", "202601").strip()

        # AI Provider Selection (Default: ollama, Options: ollama, groq, gemini)
        self.ai_provider: str = os.getenv("AI_PROVIDER", "ollama").strip().lower()

        # Local Ollama Configuration (Default model: qwen3.5:4b)
        self.ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
        self.ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3.5:4b").strip()

        # Groq Cloud Configuration (Free tier)
        self.groq_api_key: str = os.getenv("GROQ_API_KEY", "").strip()
        self.groq_model: str = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip()

        # Google Gemini & Other AI
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
        self.openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()

        # Mandatory Safety Defaults
        self.dry_run: bool = os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")
        self.publish_enabled: bool = os.getenv("PUBLISH_ENABLED", "false").lower() in ("true", "1", "yes")
        self.require_approval: bool = os.getenv("REQUIRE_APPROVAL", "true").lower() in ("true", "1", "yes")

        # Post Length & Content Settings
        self.max_post_words: int = int(os.getenv("MAX_POST_WORDS", "180"))
        self.daily_post_count: int = int(os.getenv("DAILY_POST_COUNT", "3"))

        # Output Directories
        self.images_dir: Path = ROOT_DIR / os.getenv("IMAGES_DIR", "images")
        self.images_dir.mkdir(parents=True, exist_ok=True)

        # Realistic AI Image Generation Settings (Zero-Cost / Fallback)
        self.ai_image_generation: bool = os.getenv("AI_IMAGE_GENERATION", "true").lower() in ("true", "1", "yes")
        self.image_generation_timeout: int = int(os.getenv("IMAGE_GENERATION_TIMEOUT", "25"))

        # Database
        self.database_path: Path = ROOT_DIR / os.getenv("DATABASE_PATH", "linkedin_automation.db")

        # Trend Scoring Configurable Weights (Default total: 100 points)
        self.weight_recency: float = float(os.getenv("WEIGHT_RECENCY", "25.0"))
        self.weight_credibility: float = float(os.getenv("WEIGHT_CREDIBILITY", "20.0"))
        self.weight_significance: float = float(os.getenv("WEIGHT_SIGNIFICANCE", "20.0"))
        self.weight_coverage: float = float(os.getenv("WEIGHT_COVERAGE", "15.0"))
        self.weight_relevance: float = float(os.getenv("WEIGHT_RELEVANCE", "15.0"))
        self.weight_novelty: float = float(os.getenv("WEIGHT_NOVELTY", "5.0"))

        # Optional custom sources configuration file
        sources_cfg = os.getenv("SOURCES_CONFIG_FILE", "")
        self.sources_config_file: Optional[Path] = ROOT_DIR / sources_cfg if sources_cfg else None

        # Allow keyword argument overrides for testing and dynamic config
        for key, value in kwargs.items():
            setattr(self, key, value)

    def validate_oauth_credentials(self) -> list[str]:
        """Validate presence of LinkedIn OAuth app credentials."""
        missing = []
        if not self.linkedin_client_id:
            missing.append("LINKEDIN_CLIENT_ID")
        if not self.linkedin_client_secret:
            missing.append("LINKEDIN_CLIENT_SECRET")
        if not self.linkedin_redirect_uri:
            missing.append("LINKEDIN_REDIRECT_URI")
        return missing

    def summary(self) -> dict[str, str | bool]:
        """Return safe configuration summary with redacted secrets."""
        return {
            "linkedin_client_id": redact_secret(self.linkedin_client_id),
            "linkedin_client_secret": redact_secret(self.linkedin_client_secret),
            "linkedin_redirect_uri": self.linkedin_redirect_uri,
            "linkedin_access_token": redact_secret(self.linkedin_access_token),
            "linkedin_member_id": self.linkedin_member_id or "[NOT SET]",
            "linkedin_api_version": self.linkedin_api_version,
            "ai_provider": self.ai_provider,
            "ollama_base_url": self.ollama_base_url,
            "ollama_model": self.ollama_model,
            "groq_api_key": redact_secret(self.groq_api_key),
            "groq_model": self.groq_model,
            "gemini_api_key": redact_secret(self.gemini_api_key),
            "dry_run": self.dry_run,
            "publish_enabled": self.publish_enabled,
            "require_approval": self.require_approval,
            "database_path": str(self.database_path),
        }


# Singleton instance
config = Config()
