"""AI & Technology Trend Intelligence Engine.

Continuously discovers, normalizes, verifies, clusters, tracks, and ranks the latest
trends across Frontier AI models, AI labs, LLMs, developer tools, infrastructure, and software engineering.

Core Architecture:
1. SourceRegistry: Modular registry of primary labs, company blogs, research archives, and tech communities.
2. URLNormalizer: Strips tracking parameters, normalizes scheme/host, and establishes canonical URLs.
3. EntityExtractor: Identifies companies, models, architectures, frameworks, and event types.
4. EventClusterer: Near-duplicate detection, event clustering, and role classification.
5. FreshnessClassifier: Timezone-aware date parsing and freshness window categorization.
6. TransparentTrendScorer: Configurable 0-100 scoring with documented component breakdowns and penalties.
7. TrendIntelligenceEngine: Orchestrates discovery, health tracking, SQLite persistence, and downstream integration.
"""

from __future__ import annotations

import datetime
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Optional
import urllib.parse
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from loguru import logger
import requests

from src.config import Config, config as default_config
from src.db import Database


# ---------------------------------------------------------------------------
# 1. Modular Source Registry
# ---------------------------------------------------------------------------

DEFAULT_SOURCES = [
    # --- Primary AI Labs & Model Creators (Highest Credibility) ---
    {
        "name": "OpenAI News & Research",
        "url": "https://openai.com/news/rss.xml",
        "source_type": "primary_lab",
        "category": "Frontier AI Models",
        "credibility_weight": 1.4,
        "enabled": True,
    },
    {
        "name": "Google DeepMind Blog",
        "url": "https://deepmind.google/blog/rss.xml",
        "source_type": "primary_lab",
        "category": "AI Research & Labs",
        "credibility_weight": 1.4,
        "enabled": True,
    },
    {
        "name": "Google AI Blog",
        "url": "https://blog.google/technology/ai/rss/",
        "source_type": "primary_lab",
        "category": "AI Research & Labs",
        "credibility_weight": 1.35,
        "enabled": True,
    },
    {
        "name": "Anthropic News",
        "url": "https://www.anthropic.com/news/rss.xml",
        "source_type": "primary_lab",
        "category": "Frontier AI Models",
        "credibility_weight": 1.4,
        "enabled": True,
    },
    {
        "name": "Mistral AI Announcements",
        "url": "https://mistral.ai/news/index.xml",
        "source_type": "primary_lab",
        "category": "Open-Source AI & Models",
        "credibility_weight": 1.35,
        "enabled": True,
    },
    {
        "name": "Hugging Face Blog",
        "url": "https://huggingface.co/blog/feed.xml",
        "source_type": "primary_lab",
        "category": "Open-Source AI & Models",
        "credibility_weight": 1.3,
        "enabled": True,
    },
    # --- Official Company Blogs & Engineering Releases ---
    {
        "name": "GitHub Engineering Blog",
        "url": "https://github.blog/feed/",
        "source_type": "primary_company",
        "category": "Developer Tools & Open Source",
        "credibility_weight": 1.3,
        "enabled": True,
    },
    {
        "name": "Python Software Foundation",
        "url": "https://blog.python.org/feeds/posts/default",
        "source_type": "primary_company",
        "category": "Python & Software Engineering",
        "credibility_weight": 1.3,
        "enabled": True,
    },
    {
        "name": "NVIDIA Technical Blog",
        "url": "https://developer.nvidia.com/blog/feed/",
        "source_type": "primary_company",
        "category": "AI Infrastructure & Chips",
        "credibility_weight": 1.3,
        "enabled": True,
    },
    # --- Official Research Publications & arXiv ---
    {
        "name": "arXiv Computer Science & AI",
        "url": "https://rss.arxiv.org/rss/cs.AI",
        "source_type": "research_archive",
        "category": "Frontier AI Research",
        "credibility_weight": 1.3,
        "enabled": True,
    },
    {
        "name": "arXiv Machine Learning",
        "url": "https://rss.arxiv.org/rss/cs.LG",
        "source_type": "research_archive",
        "category": "Frontier AI Research",
        "credibility_weight": 1.3,
        "enabled": True,
    },
    {
        "name": "MIT Technology Review AI",
        "url": "https://www.technologyreview.com/feed/",
        "source_type": "research_archive",
        "category": "AI Research & Industry",
        "credibility_weight": 1.25,
        "enabled": True,
    },
    # --- Community Discussions & Independent Coverage ---
    {
        "name": "Hacker News Tech Trends",
        "url": "https://hnrss.org/frontpage",
        "source_type": "community_discussion",
        "category": "Community Discussions & Viral Trends",
        "credibility_weight": 1.15,
        "enabled": True,
    },
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "source_type": "secondary_press",
        "category": "AI Industry & Startups",
        "credibility_weight": 1.1,
        "enabled": True,
    },
    {
        "name": "VentureBeat AI",
        "url": "https://venturebeat.com/category/ai/feed/",
        "source_type": "secondary_press",
        "category": "AI Industry & Startups",
        "credibility_weight": 1.1,
        "enabled": True,
    },
    {
        "name": "Ars Technica Tech Lab",
        "url": "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "source_type": "secondary_press",
        "category": "Software Engineering & Infrastructure",
        "credibility_weight": 1.15,
        "enabled": True,
    },
]


class SourceRegistry:
    """Manages configurable technology information sources."""

    def __init__(self, sources: Optional[list[dict[str, Any]]] = None, config_path: Optional[Path] = None) -> None:
        self.sources: list[dict[str, Any]] = []
        # If external config file exists, load from it; otherwise use default sources
        if config_path and config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.sources = data
                        logger.info(f"Loaded {len(self.sources)} sources from {config_path}")
            except Exception as e:
                logger.warning(f"Failed to load sources from {config_path}: {e}. Using defaults.")

        if not self.sources:
            self.sources = list(sources or DEFAULT_SOURCES)

    def add_source(
        self,
        name: str,
        url: str,
        source_type: str = "secondary_press",
        category: str = "Technology",
        credibility_weight: float = 1.0,
        enabled: bool = True,
    ) -> None:
        """Register a new source dynamically."""
        self.sources.append(
            {
                "name": name,
                "url": url,
                "source_type": source_type,
                "category": category,
                "credibility_weight": credibility_weight,
                "enabled": enabled,
            }
        )

    def get_enabled_sources(self) -> list[dict[str, Any]]:
        """Return all active sources."""
        return [s for s in self.sources if s.get("enabled", True)]


# ---------------------------------------------------------------------------
# 2. URL Normalizer
# ---------------------------------------------------------------------------

class URLNormalizer:
    """Normalizes URLs by stripping tracking tokens, lowercasing domains, and sorting query parameters."""

    TRACKING_PARAMS = {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "ref", "ref_src", "fbclid", "gclid", "twclid", "_hsenc", "_hsmi",
        "mc_cid", "mc_eid", "spm", "feature", "si", "rss", "feed", "from",
    }

    @classmethod
    def normalize(cls, raw_url: str) -> str:
        """Produce a canonical normalized URL for deduplication."""
        if not raw_url:
            return ""

        url = raw_url.strip()
        try:
            parsed = urllib.parse.urlsplit(url)
            scheme = (parsed.scheme or "https").lower()
            netloc = parsed.netloc.lower()

            # Remove standard default ports (:80, :443)
            if netloc.endswith(":80"):
                netloc = netloc[:-3]
            elif netloc.endswith(":443"):
                netloc = netloc[:-4]

            # Normalize path: strip redundant slashes
            path = parsed.path or "/"
            if len(path) > 1 and path.endswith("/"):
                path = path[:-1]

            # Filter out analytics & marketing tracking parameters
            query_tuples = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
            filtered_query = [
                (k, v) for k, v in query_tuples
                if k.lower() not in cls.TRACKING_PARAMS and not k.lower().startswith("utm_")
            ]
            # Sort query parameters for consistency
            filtered_query.sort(key=lambda x: x[0])
            new_query = urllib.parse.urlencode(filtered_query)

            # Reconstruct URL without fragment (#...)
            return urllib.parse.urlunsplit((scheme, netloc, path, new_query, ""))
        except Exception:
            return url.split("#")[0].strip()


# ---------------------------------------------------------------------------
# 3. Entity Extractor
# ---------------------------------------------------------------------------

class EntityExtractor:
    """Extracts companies, models, frameworks, and technical topics from text."""

    COMPANIES = {
        "openai": "OpenAI",
        "deepmind": "Google DeepMind",
        "google": "Google",
        "anthropic": "Anthropic",
        "meta": "Meta AI",
        "microsoft": "Microsoft",
        "nvidia": "NVIDIA",
        "mistral": "Mistral AI",
        "deepseek": "DeepSeek",
        "xai": "xAI",
        "apple": "Apple",
        "hugging face": "Hugging Face",
        "replit": "Replit",
        "github": "GitHub",
    }

    MODELS = {
        "gpt-4o": "GPT-4o",
        "gpt-4": "GPT-4",
        "o1": "OpenAI o1",
        "o3": "OpenAI o3",
        "claude 3.5": "Claude 3.5",
        "claude 3.7": "Claude 3.7",
        "claude": "Claude",
        "gemini 2.0": "Gemini 2.0",
        "gemini 1.5": "Gemini 1.5",
        "gemini": "Gemini",
        "llama 3.3": "Llama 3.3",
        "llama 3.2": "Llama 3.2",
        "llama": "Llama",
        "deepseek-r1": "DeepSeek-R1",
        "deepseek-v3": "DeepSeek-V3",
        "deepseek": "DeepSeek",
        "qwen 2.5": "Qwen 2.5",
        "qwen 3.5": "Qwen 3.5",
        "mistral large": "Mistral Large",
        "grok 2": "Grok 2",
        "grok 3": "Grok 3",
        "alphafold": "AlphaFold",
    }

    CORE_TOPICS = {
        "reasoning": "Reasoning Models",
        "agent": "AI Agents & Agentic Workflows",
        "agents": "AI Agents & Agentic Workflows",
        "coding agent": "AI Developer Tools",
        "rag": "RAG & Information Retrieval",
        "vector": "Vector Indexing",
        "hnsw": "Vector Indexing",
        "speculative decoding": "Inference Optimization",
        "inference": "Model Inference & Serving",
        "fine-tuning": "Model Training & Fine-Tuning",
        "quantization": "Model Quantization & Efficiency",
        "benchmark": "AI Benchmarks & Evaluation",
        "compiler": "Compilers & Systems",
        "python": "Python & Software Engineering",
        "free-threading": "Python Architecture",
        "gil": "Python Architecture",
        "gpu": "AI Infrastructure & Hardware",
        "data center": "AI Infrastructure & Hardware",
    }

    @classmethod
    def extract_entities(cls, title: str, summary: str = "") -> dict[str, list[str]]:
        """Identify companies, models, and technical topics."""
        combined = f"{title} {summary}".lower()

        found_companies = []
        for key, name in cls.COMPANIES.items():
            if re.search(rf"\b{re.escape(key)}\b", combined):
                if name not in found_companies:
                    found_companies.append(name)

        found_models = []
        for key, name in cls.MODELS.items():
            if re.search(rf"\b{re.escape(key)}\b", combined):
                if name not in found_models:
                    found_models.append(name)

        found_topics = []
        for key, name in cls.CORE_TOPICS.items():
            if re.search(rf"\b{re.escape(key)}\b", combined):
                if name not in found_topics:
                    found_topics.append(name)

        # Detect event type
        event_type = "technical_update"
        if any(w in combined for w in ["releases", "launches", "announces", "weights", "open-sources", "unveils"]):
            event_type = "original_announcement"
        elif any(w in combined for w in ["paper", "breakthrough", "proves", "discovery", "benchmark"]):
            event_type = "research_breakthrough"
        elif any(w in combined for w in ["debate", "discussion", "replaces", "switches", "versus", "vs"]):
            event_type = "industry_strategy"

        return {
            "companies": found_companies,
            "models": found_models,
            "topics": found_topics,
            "event_type": event_type,
        }


# ---------------------------------------------------------------------------
# 4. Freshness Classifier & Timestamp Normalization
# ---------------------------------------------------------------------------

class FreshnessClassifier:
    """Parses timestamps safely and categorizes into time-aware freshness windows."""

    @staticmethod
    def parse_timestamp(date_str: Optional[str]) -> tuple[float, bool]:
        """Convert RFC 822 or ISO-8601 string to UTC UNIX timestamp.
        
        Returns:
            (timestamp, is_valid_date)
        """
        now = time.time()
        if not date_str or not date_str.strip():
            return now, False

        cleaned = date_str.strip()
        # 1. Try RFC 822 / email format (Standard RSS)
        try:
            dt = parsedate_to_datetime(cleaned)
            ts = dt.timestamp()
            # If timestamp is in future by >1 hour, cap to now
            if ts > now + 3600:
                return now, False
            return ts, True
        except Exception:
            pass

        # 2. Try ISO 8601 (Standard Atom)
        try:
            dt = datetime.datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
            ts = dt.timestamp()
            if ts > now + 3600:
                return now, False
            return ts, True
        except Exception:
            pass

        # 3. Fallback: unparseable date
        return now, False

    @staticmethod
    def get_freshness_window(pub_timestamp: float) -> str:
        """Classify item into defined freshness windows based on age."""
        now = time.time()
        age_seconds = max(0.0, now - pub_timestamp)
        age_hours = age_seconds / 3600.0

        if age_hours <= 24.0:
            return "breaking"
        elif age_hours <= 72.0:
            return "current_development"
        elif age_hours <= 168.0:  # 7 days
            return "recent_release"
        else:
            return "evergreen"


# ---------------------------------------------------------------------------
# 5. Event Clustering & Near-Duplicate Detection
# ---------------------------------------------------------------------------

class EventClusterer:
    """Groups related stories reporting on the same underlying technological event."""

    STOPWORDS = {
        "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "of",
        "with", "is", "are", "was", "were", "it", "its", "by", "from", "as",
        "has", "have", "had", "will", "new", "says", "how", "why", "what",
    }

    @classmethod
    def tokenize(cls, text: str) -> set[str]:
        """Extract alphanumeric token set excluding common stopwords."""
        words = re.findall(r"\b[a-z0-9_-]{2,}\b", text.lower())
        return {w for w in words if w not in cls.STOPWORDS}

    @classmethod
    def calculate_similarity(cls, tokens1: set[str], tokens2: set[str]) -> float:
        """Compute Jaccard similarity between two token sets."""
        if not tokens1 or not tokens2:
            return 0.0
        intersection = len(tokens1.intersection(tokens2))
        union = len(tokens1.union(tokens2))
        return intersection / union if union > 0 else 0.0

    @classmethod
    def generate_cluster_key(cls, title: str, entities: dict[str, Any]) -> str:
        """Produce a deterministic cluster identifier based on primary entities and core terms."""
        comps = sorted(entities.get("companies", []))
        models = sorted(entities.get("models", []))
        top_tokens = sorted(list(cls.tokenize(title)))[:5]

        key_components = []
        if comps:
            key_components.append("-".join(comps))
        if models:
            key_components.append("-".join(models))
        key_components.append("-".join(top_tokens))

        raw_key = "_".join(key_components).lower()
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 6. Transparent Trend Scorer (0 to 100)
# ---------------------------------------------------------------------------

class TransparentTrendScorer:
    """Calculates configurable transparent scores from 0 to 100 with documented component rationale."""

    def __init__(self, cfg: Optional[Config] = None) -> None:
        self.config = cfg or default_config
        # Configurable weights (default sum = 100.0)
        self.weight_recency = getattr(self.config, "weight_recency", 25.0)
        self.weight_credibility = getattr(self.config, "weight_credibility", 20.0)
        self.weight_significance = getattr(self.config, "weight_significance", 20.0)
        self.weight_coverage = getattr(self.config, "weight_coverage", 15.0)
        self.weight_relevance = getattr(self.config, "weight_relevance", 15.0)
        self.weight_novelty = getattr(self.config, "weight_novelty", 5.0)

    def calculate_score(
        self,
        article_age_hours: float,
        source_type: str,
        credibility_weight: float,
        entities: dict[str, Any],
        cluster_article_count: int,
        is_community_trend: bool = False,
        is_duplicate_cluster_article: bool = False,
        is_recently_covered_by_account: bool = False,
        has_verified_url: bool = True,
        has_verified_claims: bool = True,
    ) -> dict[str, Any]:
        """Compute transparent 0-100 score and human-readable explanation."""

        # 1. Recency Score (Max: self.weight_recency = 25 pts)
        if article_age_hours <= 12.0:
            recency_ratio = 1.0
        elif article_age_hours <= 24.0:
            recency_ratio = 0.90
        elif article_age_hours <= 48.0:
            recency_ratio = 0.70
        elif article_age_hours <= 72.0:
            recency_ratio = 0.50
        elif article_age_hours <= 168.0:  # 7 days
            recency_ratio = 0.30
        else:
            recency_ratio = 0.10
        score_recency = round(recency_ratio * self.weight_recency, 1)

        # 2. Source Credibility (Max: self.weight_credibility = 20 pts)
        type_multipliers = {
            "primary_lab": 1.0,         # Official model lab (OpenAI, DeepMind, Anthropic)
            "primary_company": 0.90,     # Official engineering blog (GitHub, Python)
            "research_archive": 0.85,    # arXiv, MIT Tech Review
            "secondary_press": 0.70,     # TechCrunch, VentureBeat
            "community_discussion": 0.60 # Hacker News
        }
        base_mult = type_multipliers.get(source_type, 0.60)
        cred_ratio = min(1.0, base_mult * (credibility_weight / 1.2))
        score_credibility = round(cred_ratio * self.weight_credibility, 1)

        # 3. Significance & Potential Impact (Max: self.weight_significance = 20 pts)
        sig_points = 6.0  # Base significance
        if entities.get("models"):
            sig_points += 7.0  # Specific model announcement
        if entities.get("companies"):
            sig_points += 4.0  # Major lab involved
        if entities.get("event_type") in ("original_announcement", "research_breakthrough"):
            sig_points += 3.0  # Breakthrough/announcement event
        sig_ratio = min(1.0, sig_points / 20.0)
        score_significance = round(sig_ratio * self.weight_significance, 1)

        # 4. Independent Coverage & Accessible Discussion (Max: self.weight_coverage = 15 pts)
        if cluster_article_count >= 4:
            cov_ratio = 1.0
        elif cluster_article_count == 3:
            cov_ratio = 0.85
        elif cluster_article_count == 2:
            cov_ratio = 0.65
        elif is_community_trend:
            cov_ratio = 0.50
        else:
            cov_ratio = 0.35
        score_coverage = round(cov_ratio * self.weight_coverage, 1)

        # 5. Relevance to LinkedIn Audience (Max: self.weight_relevance = 15 pts)
        rel_points = 7.0
        if entities.get("topics"):
            rel_points += min(6.0, len(entities["topics"]) * 3.0)
        if any(w in str(entities.get("topics", [])).lower() for w in ["agent", "python", "reasoning", "vector", "inference"]):
            rel_points += 2.0
        rel_ratio = min(1.0, rel_points / 15.0)
        score_relevance = round(rel_ratio * self.weight_relevance, 1)

        # 6. Novelty (Max: self.weight_novelty = 5 pts)
        score_novelty = round(self.weight_novelty if entities.get("models") or sig_points > 14 else 2.5, 1)

        # 7. Penalties
        penalties = 0.0
        penalty_reasons = []

        if is_duplicate_cluster_article:
            penalties += 15.0
            penalty_reasons.append("duplicate report in cluster (-15)")

        if article_age_hours > 168.0:
            penalties += 20.0
            penalty_reasons.append("stale content (>7 days) (-20)")

        if is_recently_covered_by_account:
            penalties += 30.0
            penalty_reasons.append("topic covered in recent post (-30)")

        if not has_verified_url:
            penalties += 15.0
            penalty_reasons.append("unverified source URL (-15)")

        if not has_verified_claims:
            penalties += 15.0
            penalty_reasons.append("unsupported claims (-15)")

        raw_total = (
            score_recency
            + score_credibility
            + score_significance
            + score_coverage
            + score_relevance
            + score_novelty
            - penalties
        )
        total_score = round(max(0.0, min(100.0, raw_total)), 1)

        # Detailed explanation string
        pen_str = f" | Penalties: {', '.join(penalty_reasons)}" if penalty_reasons else ""
        explanation = (
            f"Score {total_score}/100 [Recency: {score_recency}/{self.weight_recency}, "
            f"Credibility: {score_credibility}/{self.weight_credibility}, "
            f"Significance: {score_significance}/{self.weight_significance}, "
            f"Coverage: {score_coverage}/{self.weight_coverage}, "
            f"Relevance: {score_relevance}/{self.weight_relevance}, "
            f"Novelty: {score_novelty}/{self.weight_novelty}{pen_str}]"
        )

        return {
            "total_score": total_score,
            "score_recency": score_recency,
            "score_credibility": score_credibility,
            "score_significance": score_significance,
            "score_coverage": score_coverage,
            "score_relevance": score_relevance,
            "score_novelty": score_novelty,
            "penalty_score": penalties,
            "explanation": explanation,
        }


# ---------------------------------------------------------------------------
# 7. Trend Intelligence Engine (High-Level Orchestrator)
# ---------------------------------------------------------------------------

class TrendIntelligenceEngine:
    """Master orchestrator for continuous technology trend discovery, verification, and ranking."""

    def __init__(
        self,
        cfg: Optional[Config] = None,
        db: Optional[Database] = None,
        registry: Optional[SourceRegistry] = None,
    ) -> None:
        self.config = cfg or default_config
        self.db = db or Database(self.config.database_path)
        self.registry = registry or SourceRegistry(config_path=getattr(self.config, "sources_config_file", None))
        self.normalizer = URLNormalizer()
        self.clusterer = EventClusterer()
        self.scorer = TransparentTrendScorer(self.config)

    def _clean_summary(self, raw_html: str, max_chars: int = 500) -> str:
        """Strip HTML tags and condense whitespace."""
        if not raw_html:
            return ""
        soup = BeautifulSoup(raw_html, "html.parser")
        text = " ".join(soup.get_text().split())
        return text[:max_chars].strip()

    def fetch_feed_items(self, source: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
        """Fetch and parse RSS/Atom feed items for a registered source with health recording."""
        name = source["name"]
        url = source["url"]
        source_type = source.get("source_type", "secondary_press")
        category = source.get("category", "Technology")
        credibility = source.get("credibility_weight", 1.0)

        items: list[dict[str, Any]] = []
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) TrendIntelligenceEngine/2.0"},
                timeout=12,
            )
            if resp.status_code != 200:
                err_msg = f"HTTP {resp.status_code}"
                logger.warning(f"Source [{name}] fetch failed: {err_msg}")
                self.db.record_source_attempt(name, url, source_type, category, credibility, success=False, error=err_msg)
                return []

            root = ET.fromstring(resp.content)
            raw_items = root.findall(".//item")
            is_atom = False
            if not raw_items:
                raw_items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
                is_atom = True

            count = 0
            for item in raw_items:
                if count >= limit:
                    break

                if is_atom:
                    ns = {"atom": "http://www.w3.org/2005/Atom"}
                    t_el = item.find("atom:title", ns)
                    l_el = item.find("atom:link", ns)
                    d_el = item.find("atom:summary", ns)
                    if d_el is None:
                        d_el = item.find("atom:content", ns)
                    date_el = item.find("atom:published", ns)
                    if date_el is None:
                        date_el = item.find("atom:updated", ns)
                    auth_el = item.find("atom:author/atom:name", ns)

                    title = t_el.text.strip() if t_el is not None and t_el.text else ""
                    raw_link = l_el.attrib.get("href", "") if l_el is not None else ""
                    raw_desc = d_el.text if d_el is not None and d_el.text else ""
                    raw_date = date_el.text if date_el is not None and date_el.text else ""
                    author = auth_el.text.strip() if auth_el is not None and auth_el.text else ""
                else:
                    t_el = item.find("title")
                    l_el = item.find("link")
                    d_el = item.find("description")
                    date_el = item.find("pubDate")
                    auth_el = item.find("author")
                    if auth_el is None:
                        auth_el = item.find("dc:creator", {"dc": "http://purl.org/dc/elements/1.1/"})

                    title = t_el.text.strip() if t_el is not None and t_el.text else ""
                    raw_link = l_el.text.strip() if l_el is not None and l_el.text else ""
                    raw_desc = d_el.text if d_el is not None and d_el.text else ""
                    raw_date = date_el.text if date_el is not None and date_el.text else ""
                    author = auth_el.text.strip() if auth_el is not None and auth_el.text else ""

                if not title or not raw_link:
                    continue

                normalized_url = self.normalizer.normalize(raw_link)
                pub_ts, is_valid_date = FreshnessClassifier.parse_timestamp(raw_date)
                summary = self._clean_summary(raw_desc)
                entities = EntityExtractor.extract_entities(title, summary)

                items.append(
                    {
                        "title": title,
                        "summary": summary,
                        "original_url": raw_link,
                        "normalized_url": normalized_url,
                        "source_name": name,
                        "source_type": source_type,
                        "category": category,
                        "credibility_weight": credibility,
                        "author": author,
                        "published_at": pub_ts,
                        "is_valid_date": is_valid_date,
                        "entities": entities,
                    }
                )
                count += 1

            self.db.record_source_attempt(name, url, source_type, category, credibility, success=True)
            return items

        except Exception as e:
            logger.warning(f"Source [{name}] exception: {e}")
            self.db.record_source_attempt(name, url, source_type, category, credibility, success=False, error=str(e))
            return []

    def discover_and_rank_trends(self, limit_per_feed: int = 5, min_score: float = 0.0) -> list[dict[str, Any]]:
        """Execute full discovery, normalization, clustering, and scoring across sources."""
        enabled_sources = self.registry.get_enabled_sources()
        all_articles: list[dict[str, Any]] = []

        logger.info(f"Discovering trends across {len(enabled_sources)} registered technology sources...")

        # 1. Fetch articles from sources
        for src in enabled_sources:
            items = self.fetch_feed_items(src, limit=limit_per_feed)
            all_articles.extend(items)

        if not all_articles:
            logger.warning("No articles collected from configured sources.")
            return []

        # 2. Retrieve recently published topics to enforce recent-coverage penalties
        recent_topics = self.db.get_recent_published_topics(lookback_days=14)

        # 3. Cluster and score articles
        clusters: dict[str, dict[str, Any]] = {}
        now = time.time()

        for art in all_articles:
            norm_url = art["normalized_url"]
            title = art["title"]
            entities = art["entities"]
            cluster_key = self.clusterer.generate_cluster_key(title, entities)
            art["cluster_key"] = cluster_key

            # Save raw article to SQLite database
            self.db.save_article(
                normalized_url=norm_url,
                original_url=art["original_url"],
                title=title,
                summary=art["summary"],
                source_name=art["source_name"],
                source_type=art["source_type"],
                author=art["author"],
                published_at=art["published_at"],
                cluster_key=cluster_key,
                entities=entities,
                credibility=art["credibility_weight"],
            )

            # Check if this topic closely matches our recent publications
            is_recent_post = any(
                EventClusterer.calculate_similarity(EventClusterer.tokenize(title), EventClusterer.tokenize(t)) > 0.4
                for t in recent_topics
            )

            age_hours = max(0.0, (now - art["published_at"]) / 3600.0)
            freshness_win = FreshnessClassifier.get_freshness_window(art["published_at"])

            if cluster_key not in clusters:
                clusters[cluster_key] = {
                    "cluster_key": cluster_key,
                    "canonical_title": title,
                    "summary": art["summary"],
                    "category": art["category"],
                    "event_type": entities.get("event_type", "original_announcement"),
                    "primary_source_url": art["original_url"],
                    "primary_source_name": art["source_name"],
                    "article_count": 1,
                    "entities": entities,
                    "freshness_window": freshness_win,
                    "momentum": "emerging",
                    "articles": [art],
                    "published_at": art["published_at"],
                    "is_recently_covered": is_recent_post,
                    "credibility_weight": art["credibility_weight"],
                    "source_type": art["source_type"],
                    "age_hours": age_hours,
                }
            else:
                c = clusters[cluster_key]
                c["article_count"] += 1
                c["articles"].append(art)
                # If this new article is from a primary lab, upgrade primary source
                if art["source_type"] in ("primary_lab", "primary_company"):
                    c["primary_source_url"] = art["original_url"]
                    c["primary_source_name"] = art["source_name"]
                    c["source_type"] = art["source_type"]
                    c["credibility_weight"] = max(c["credibility_weight"], art["credibility_weight"])
                # Update momentum
                c["momentum"] = "rising" if c["article_count"] >= 3 else "sustained"

        # 4. Score each cluster
        scored_clusters: list[dict[str, Any]] = []
        for ckey, c in clusters.items():
            has_url = bool(c["primary_source_url"] and c["primary_source_url"].startswith(("http://", "https://")))
            has_claims = bool(c["summary"] and len(c["summary"].strip()) >= 20)
            score_data = self.scorer.calculate_score(
                article_age_hours=c["age_hours"],
                source_type=c["source_type"],
                credibility_weight=c["credibility_weight"],
                entities=c["entities"],
                cluster_article_count=c["article_count"],
                is_community_trend=any(a["source_type"] == "community_discussion" for a in c["articles"]),
                is_recently_covered_by_account=c["is_recently_covered"],
                has_verified_url=has_url,
                has_verified_claims=has_claims,
            )

            # Save cluster record to SQLite
            self.db.save_trend_cluster(
                cluster_key=ckey,
                canonical_title=c["canonical_title"],
                category=c["category"],
                event_type=c["event_type"],
                primary_source_url=c["primary_source_url"],
                primary_source_name=c["primary_source_name"],
                article_count=c["article_count"],
                entities=c["entities"],
                freshness_window=c["freshness_window"],
                momentum=c["momentum"],
                summary=c["summary"],
            )

            # Save score breakdown to SQLite
            self.db.save_trend_score(
                cluster_key=ckey,
                total_score=score_data["total_score"],
                score_recency=score_data["score_recency"],
                score_credibility=score_data["score_credibility"],
                score_significance=score_data["score_significance"],
                score_coverage=score_data["score_coverage"],
                score_relevance=score_data["score_relevance"],
                score_novelty=score_data["score_novelty"],
                penalty_score=score_data["penalty_score"],
                explanation=score_data["explanation"],
            )

            trend_record = {
                "title": c["canonical_title"],
                "summary": c["summary"],
                "category": c["category"],
                "source_url": c["primary_source_url"],
                "source_name": c["primary_source_name"],
                "source_type": c["source_type"],
                "cluster_key": ckey,
                "article_count": c["article_count"],
                "freshness_window": c["freshness_window"],
                "momentum": c["momentum"],
                "published_at": c["published_at"],
                "score": score_data["total_score"],
                "score_explanation": score_data["explanation"],
                "entities": c["entities"],
                "has_primary_evidence": c["source_type"] in ("primary_lab", "primary_company", "research_archive"),
                "uncertainties": [] if has_claims else ["Unverified claim / limited source text"],
            }
            if score_data["total_score"] >= min_score:
                scored_clusters.append(trend_record)

        # Sort by total score descending
        scored_clusters.sort(key=lambda x: x["score"], reverse=True)
        logger.info(f"Ranked {len(scored_clusters)} trend clusters. Top: '{scored_clusters[0]['title'][:40]}...' ({scored_clusters[0]['score']} pts)")
        return scored_clusters

    def get_top_trend(self) -> Optional[dict[str, Any]]:
        """Retrieve the single highest-scoring unposted trend."""
        trends = self.discover_and_rank_trends(limit_per_feed=3)
        for t in trends:
            if not self.db.is_topic_already_covered(t["title"], t["source_url"]):
                return t
        return trends[0] if trends else None

    def get_sources_health(self) -> list[dict[str, Any]]:
        """Return registered sources health metrics from database."""
        return self.db.list_sources_health()

    def ai_assisted_research(
        self,
        topic: str,
        context: str = "",
        provider: Optional[str] = None,
    ) -> dict[str, Any]:
        """Perform AI-assisted research and entity/claim analysis with automatic local fallback."""
        deterministic_entities = EntityExtractor.extract_entities(topic, context)
        fallback_result = {
            "topic": topic,
            "subtopics": deterministic_entities.get("topics", []),
            "key_claims": [context[:150]] if context else ["Verified technical release"],
            "uncertainties": [] if context and len(context) >= 20 else ["Limited source context available"],
            "audience_relevance": "High for AI and software engineers",
            "provider_used": "deterministic_rules",
            "entities": deterministic_entities,
        }

        try:
            from src.generator import ContentGenerator
            gen = ContentGenerator(cfg=self.config, db=self.db)
            analysis_prompt = (
                f"Analyze this technological development for technical accuracy.\n"
                f"Headline: {topic}\n"
                f"Context: {context or 'N/A'}\n\n"
                f"Return JSON with keys:\n"
                f"- 'key_claims': list of 1-2 verified factual points\n"
                f"- 'uncertainties': list of any unconfirmed claims or empty list\n"
                f"- 'relevance': brief explanation of relevance for engineers\n"
            )
            target_prov = (provider or self.config.ai_provider or "ollama").lower()
            if target_prov == "groq" and self.config.groq_api_key:
                raw_out, model_used = gen.generate_with_groq(analysis_prompt)
            elif target_prov == "gemini" and self.config.gemini_api_key:
                raw_out, model_used = gen.generate_with_gemini(analysis_prompt)
            else:
                raw_out, model_used = gen.generate_with_ollama(analysis_prompt)
                target_prov = "ollama"

            match = re.search(r"\{.*\}", raw_out, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                return {
                    "topic": topic,
                    "subtopics": deterministic_entities.get("topics", []),
                    "key_claims": parsed.get("key_claims", fallback_result["key_claims"]),
                    "uncertainties": parsed.get("uncertainties", []),
                    "audience_relevance": parsed.get("relevance", fallback_result["audience_relevance"]),
                    "provider_used": f"{target_prov}:{model_used}",
                    "entities": deterministic_entities,
                }
        except Exception as e:
            logger.debug(f"AI-assisted research fallback to rules: {e}")

        return fallback_result
