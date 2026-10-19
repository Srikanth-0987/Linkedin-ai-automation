"""AI Content Generator for LinkedIn posts.

Supports:
- Groq Cloud API (fast LPU inference, free tier, configurable models like llama-3.3-70b-versatile)
- Local Ollama (100% free offline, budget ₹0, default model qwen3.5:4b)
- Google Gemini API (optional fallback)

Implements graceful degradation: if cloud provider quotas are exhausted, automatically
falls back to local Ollama without user interruption or paid billing.
"""

from __future__ import annotations

import json
from typing import Any, Optional
import requests
from loguru import logger

from src.config import Config, config as default_config, redact_secret
from src.db import Database
from src.image_generator import ImageGenerator, extract_image_elements, ImageValidator


POST_PROMPT_TEMPLATE = """You are a senior tech leader, software engineer, and AI specialist writing a concise, authentic LinkedIn post.

Topic: {topic}
Category: {category}
Context / Evidence: {context}
Source Link: {source_url}

Strict Requirements:
1. Target Length: 80–150 words (maximum 180 words). Be concise, dense, and eliminate fluff. Optimized for mobile screens.
2. Structure:
   - Attention-grabbing opening (1-2 sentences hook without clichés like '🚀 Game changer alert!').
   - Concise explanation of the news or technical concept.
   - Why it matters for engineers and practitioners.
   - One useful, concrete takeaway.
   - Natural closing question to invite technical discussion.
   - 3 to 5 relevant hashtags (e.g., #AI #SoftwareEngineering #Python #MachineLearning).
3. Style: Avoid unnecessary introductions, repetitive explanations, excessive emojis (max 1-2), exaggerated claims, and generic AI filler.
4. Factual Accuracy: Never fabricate news, numbers, benchmarks, quotations, or personal experiences not in the context.
5. If a source link is provided and valid, include it cleanly at the end (e.g. "Source: [URL]").

Return ONLY the complete post text without conversational filler, headers, or word count labels.
"""


def normalize_text_quotes(text: str) -> str:
    """Normalize unicode curly quotes and dashes to clean ASCII."""
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    return text


def enforce_word_limit(text: str, max_words: int = 180) -> str:
    """Ensure post does not exceed max_words while preserving hashtags."""
    text = normalize_text_quotes(text)
    words = text.strip().split()
    if len(words) <= max_words:
        return text

    hashtags = [w for w in words if w.startswith("#")]
    body_words = [w for w in words if not w.startswith("#")]

    hashtag_budget = min(len(hashtags), 5)
    body_budget = max_words - hashtag_budget

    trimmed_body = " ".join(body_words[:body_budget])
    last_punct = max(trimmed_body.rfind("."), trimmed_body.rfind("?"), trimmed_body.rfind("!"))
    if last_punct > len(trimmed_body) * 0.7:
        trimmed_body = trimmed_body[: last_punct + 1]

    final_words = trimmed_body.split() + hashtags[:hashtag_budget]
    return " ".join(final_words)


class ContentGenerator:
    """Generates LinkedIn post drafts via Groq, Ollama, or Gemini with automatic fallback."""

    def __init__(self, cfg: Optional[Config] = None, db: Optional[Database] = None) -> None:
        self.config = cfg or default_config
        self.db = db or Database(self.config.database_path)

    def generate_with_groq(self, prompt: str, model: Optional[str] = None) -> tuple[str, str]:
        """Generate content using Groq's official Python SDK.
        
        Returns:
            (commentary_text, model_name)
        """
        if not self.config.groq_api_key:
            raise ValueError("GROQ_API_KEY is not configured in .env.")

        chosen_model = model or self.config.groq_model or "llama-3.3-70b-versatile"
        logger.info(f"Attempting post generation with Groq model: {chosen_model} (key: {redact_secret(self.config.groq_api_key)})")

        try:
            from groq import Groq, RateLimitError, APIConnectionError, APIStatusError

            client = Groq(api_key=self.config.groq_api_key)
            completion = client.chat.completions.create(
                model=chosen_model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional software engineer and AI content writer producing engaging, factually verified LinkedIn posts.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=1024,
            )

            text = completion.choices[0].message.content or ""
            return text.strip(), chosen_model

        except Exception as e:
            logger.warning(f"Groq API call failed [{type(e).__name__}]: {e}")
            raise

    def generate_with_ollama(self, prompt: str, model: Optional[str] = None) -> tuple[str, str]:
        """Generate content using local Ollama (100% free / budget ₹0).
        
        Returns:
            (commentary_text, model_name)
        """
        chosen_model = model or self.config.ollama_model or "qwen3.5:4b"
        url = f"{self.config.ollama_base_url.rstrip('/')}/api/generate"
        payload = {
            "model": chosen_model,
            "prompt": prompt,
            "stream": False,
        }

        logger.info(f"Generating content locally via Ollama ({chosen_model}) at {self.config.ollama_base_url}...")

        try:
            resp = requests.post(url, json=payload, timeout=15)
        except requests.RequestException as e:
            raise RuntimeError(
                f"Could not connect to Ollama at {self.config.ollama_base_url}. "
                f"Ensure Ollama is running (`ollama serve` or `ollama run {chosen_model}`)."
            ) from e

        if resp.status_code != 200:
            raise RuntimeError(f"Ollama returned HTTP {resp.status_code}: {resp.text}")

        data = resp.json()
        return data.get("response", "").strip(), chosen_model

    def generate_with_gemini(self, prompt: str) -> tuple[str, str]:
        """Generate content using Google Gemini API.
        
        Returns:
            (commentary_text, model_name)
        """
        if not self.config.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not configured in .env.")

        # Try google-genai library
        try:
            from google import genai
            client = genai.Client(api_key=self.config.gemini_api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            if response.text:
                return response.text.strip(), "gemini-2.5-flash"
        except Exception as e:
            logger.debug(f"google-genai client attempt: {e}, attempting direct REST...")

        # Fallback to direct REST API
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={self.config.gemini_api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1000},
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini API error [{resp.status_code}]: {resp.text}")

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini returned empty candidates.")
        return candidates[0]["content"]["parts"][0]["text"].strip(), "gemini-1.5-flash"

    def generate_draft(
        self,
        topic: str,
        context: str = "",
        category: str = "Technology",
        source_url: str = "",
        source_name: str = "",
        provider: Optional[str] = None,
        topic_id: Optional[int] = None,
        generate_image: bool = True,
    ) -> dict[str, Any]:
        """Generate a new LinkedIn post draft with automatic failover to Ollama.
        
        Args:
            topic: The central topic or headline.
            context: Additional context or article summary.
            category: Topic category.
            source_url: Reference URL.
            source_name: Name of the source.
            provider: 'groq', 'ollama', 'gemini', or None (uses config.ai_provider).
            topic_id: Optional research topic ID to mark as used in database.
            generate_image: Whether to generate an image for this post. Set False for scripted text-only news posts.
            
        Returns:
            Dict containing post_id, commentary, ai_provider, ai_model, fallback_used, and status.
        """
        prompt = POST_PROMPT_TEMPLATE.format(
            topic=topic,
            category=category,
            context=context or "Recent software engineering and AI innovation",
            source_url=source_url or "N/A",
        )

        target_provider = (provider or self.config.ai_provider or "ollama").lower()
        commentary = ""
        actual_provider = target_provider
        actual_model = ""
        fallback_used = False

        # Provider Execution with Automatic Local Fallback
        if target_provider == "groq":
            try:
                commentary, actual_model = self.generate_with_groq(prompt)
                actual_provider = "groq"
            except Exception as e:
                logger.warning(
                    f"Groq generation failed ({e}). Falling back to local Ollama ({self.config.ollama_model})..."
                )
                commentary, actual_model = self.generate_with_ollama(prompt)
                actual_provider = "ollama"
                fallback_used = True

        elif target_provider == "gemini":
            try:
                commentary, actual_model = self.generate_with_gemini(prompt)
                actual_provider = "gemini"
            except Exception as e:
                logger.warning(
                    f"Gemini generation failed ({e}). Falling back to local Ollama ({self.config.ollama_model})..."
                )
                commentary, actual_model = self.generate_with_ollama(prompt)
                actual_provider = "ollama"
                fallback_used = True

        else:  # Default: 'ollama'
            try:
                commentary, actual_model = self.generate_with_ollama(prompt)
                actual_provider = "ollama"
            except Exception as e:
                # If Ollama is not running and Groq key exists, try Groq as backup
                if self.config.groq_api_key:
                    logger.warning(
                        f"Ollama unavailable ({e}). Attempting backup generation via Groq ({self.config.groq_model})..."
                    )
                    commentary, actual_model = self.generate_with_groq(prompt)
                    actual_provider = "groq"
                    fallback_used = True
                else:
                    raise

        if not commentary:
            raise RuntimeError("Generated commentary was empty.")

        # Enforce mobile-optimized word limit (Feature 2)
        commentary = enforce_word_limit(commentary, max_words=self.config.max_post_words)

        # Save post draft to database
        post_id = self.db.create_post(
            commentary=commentary,
            topic=topic,
            category=category,
            source_url=source_url,
            source_name=source_name,
            ai_provider=actual_provider,
            ai_model=actual_model,
            fallback_used=fallback_used,
            validation_status="VALIDATED",
        )

        if topic_id and self.db:
            self.db.mark_topic_used(topic_id, post_id)

        # Automatic Image Generation (Feature 3 & 4)
        image_metadata: dict[str, Any] = {}
        if generate_image:
            try:
                image_gen = ImageGenerator(self.config)
                headline, points = extract_image_elements(topic=topic, context=context, commentary=commentary)
                img_result = image_gen.generate_image_for_post(
                    post_id=post_id,
                    topic=topic,
                    category=category,
                    source_name=source_name,
                    headline=headline,
                    points=points,
                )
                # Attach image metadata to SQLite database
                self.db.attach_image_to_post(
                    post_id=post_id,
                    image_path=img_result["image_path"],
                    image_hash=img_result["image_hash"],
                    image_alt_text=img_result["image_alt_text"],
                    image_width=img_result["image_width"],
                    image_height=img_result["image_height"],
                    validation_status=img_result["validation_status"],
                )
                image_metadata = img_result
                logger.info(f"Generated & attached 1200x1200px PNG image for post #{post_id} at {img_result['image_path']}")
            except Exception as e:
                logger.error(f"Image generation failed for post #{post_id}: {e}")
                self.db.mark_post_failed(post_id, f"Image generation failed: {e}")
                image_metadata = {"validation_status": "FAILED", "error": str(e)}
        else:
            logger.info(f"Post #{post_id} created as scripted text-only news post (generate_image=False).")

        logger.info(
            f"Created post draft #{post_id} using {actual_provider} ({actual_model}) "
            f"[Fallback: {fallback_used}] [Image: {image_metadata.get('validation_status', 'None (Scripted Text-Only)')}]."
        )

        return {
            "post_id": post_id,
            "topic": topic,
            "category": category,
            "commentary": commentary,
            "status": "DRAFT",
            "source_url": source_url,
            "ai_provider": actual_provider,
            "ai_model": actual_model,
            "fallback_used": fallback_used,
            "image": image_metadata,
        }
