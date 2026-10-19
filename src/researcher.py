"""Research and topic discovery pipeline for trending AI, ML, and software engineering topics.

Features:
- Configurable public RSS feeds (Frontier AI, Google DeepMind, OpenAI, Python, GitHub, Hacker News).
- Technical community trend tracking (identifying viral X/Twitter discussions without paid APIs).
- Normalization, credibility scoring, freshness weighting, and deduplication.
- Link validation and fact-claim preservation.
"""

from __future__ import annotations

import datetime
from email.utils import parsedate_to_datetime
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Optional
import requests
from bs4 import BeautifulSoup
from loguru import logger

from src.db import Database


# Configurable public RSS feeds organized by category (100% free, no API keys or paid tiers required)
DEFAULT_RESEARCH_FEEDS = [
    # 1. Frontier AI Research & Open Models
    {
        "name": "arXiv Computer Science & AI",
        "url": "https://rss.arxiv.org/rss/cs.AI",
        "source_type": "research_archive",
        "category": "Frontier AI Research",
        "credibility_weight": 1.3,
    },
    {
        "name": "Hugging Face Blog & Releases",
        "url": "https://huggingface.co/blog/feed.xml",
        "source_type": "primary_lab",
        "category": "Open-Source AI & Models",
        "credibility_weight": 1.3,
    },
    # 2. Tech Giants & AI Labs
    {
        "name": "Google AI & DeepMind Blog",
        "url": "https://blog.google/technology/ai/rss/",
        "source_type": "primary_lab",
        "category": "AI Industry & Labs",
        "credibility_weight": 1.35,
    },
    {
        "name": "MIT Technology Review AI",
        "url": "https://www.technologyreview.com/feed/",
        "source_type": "research_archive",
        "category": "AI Industry & Labs",
        "credibility_weight": 1.25,
    },
    # 3. Python, Engineering & GitHub
    {
        "name": "GitHub Blog & Releases",
        "url": "https://github.blog/feed/",
        "source_type": "primary_company",
        "category": "Developer Tools & Open Source",
        "credibility_weight": 1.3,
    },
    {
        "name": "Python Software Foundation Blog",
        "url": "https://blog.python.org/feeds/posts/default",
        "source_type": "primary_company",
        "category": "Python & Software Engineering",
        "credibility_weight": 1.3,
    },
    # 4. Tech Communities & Viral Discussions (Including X/Twitter tech debates)
    {
        "name": "Hacker News Tech Trends",
        "url": "https://hnrss.org/frontpage",
        "source_type": "community_discussion",
        "category": "Community Discussions & Viral Trends",
        "credibility_weight": 1.15,
    },
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "source_type": "secondary_press",
        "category": "AI Industry & Startups",
        "credibility_weight": 1.1,
    },
    {
        "name": "VentureBeat AI",
        "url": "https://venturebeat.com/category/ai/feed/",
        "source_type": "secondary_press",
        "category": "AI Industry & Startups",
        "credibility_weight": 1.1,
    },
]

# Keywords that boost ranking for high-value technical LinkedIn posts
RELEVANCE_KEYWORDS = [
    "llm", "agent", "agents", "reasoning", "benchmark", "open-source",
    "architecture", "deepseek", "qwen", "llama", "deepmind", "anthropic",
    "gemini", "openai", "neural", "weights", "fine-tuning", "rag",
    "python", "compiler", "runtime", "github", "breakthrough", "dataset",
]


class TopicResearcher:
    """Discovers, normalizes, scores, and deduplicates trending technology topics."""

    def __init__(
        self,
        feeds: Optional[list[dict[str, Any]]] = None,
        db: Optional[Database] = None,
    ) -> None:
        self.feeds = feeds or DEFAULT_RESEARCH_FEEDS
        self.db = db
        # Wire up TrendIntelligenceEngine for clustering, entity extraction, and transparent scoring
        from src.trend_engine import DEFAULT_SOURCES, SourceRegistry, TrendIntelligenceEngine
        sources_to_use = feeds or DEFAULT_SOURCES
        self.engine = TrendIntelligenceEngine(db=self.db, registry=SourceRegistry(sources=sources_to_use))

    def _parse_pub_date(self, date_str: Optional[str]) -> float:
        """Parse RFC 822 or ISO timestamp into UNIX timestamp."""
        if not date_str:
            return time.time()
        try:
            dt = parsedate_to_datetime(date_str)
            return dt.timestamp()
        except Exception:
            try:
                dt = datetime.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                return dt.timestamp()
            except Exception:
                return time.time()

    def _extract_summary(self, raw_html: str, max_chars: int = 500) -> str:
        """Clean HTML tags and return normalized summary."""
        if not raw_html:
            return ""
        soup = BeautifulSoup(raw_html, "html.parser")
        text = " ".join(soup.get_text().split())
        return text[:max_chars].strip()

    def _calculate_score(self, title: str, summary: str, pub_time: float, credibility: float) -> float:
        """Compute ranking score based on freshness, keywords, and source credibility."""
        combined_text = f"{title} {summary}".lower()

        # 1. Freshness Score (0.0 to 1.0; 24h = 1.0, 7 days = 0.2)
        age_hours = max(0.0, (time.time() - pub_time) / 3600)
        freshness_score = max(0.1, 1.0 - (age_hours / 168.0))

        # 2. Relevance Score based on keywords
        keyword_hits = sum(1 for kw in RELEVANCE_KEYWORDS if re.search(rf"\b{kw}\b", combined_text))
        relevance_score = min(2.5, 0.5 + (keyword_hits * 0.3))

        # 3. Overall composite score
        return round(freshness_score * relevance_score * credibility * 10, 2)

    def _detect_x_trend(self, title: str, summary: str, link: str) -> bool:
        """Identify if a topic discusses or originates from an X/Twitter discussion."""
        combined = f"{title} {summary} {link}".lower()
        patterns = [r"x\.com/", r"twitter\.com/", r"\bon x\b", r"\btweet", r"\bviral thread\b"]
        return any(re.search(p, combined) for p in patterns)

    def fetch_all_topics(self, limit_per_feed: int = 5) -> list[dict[str, Any]]:
        """Fetch, normalize, and score topics across all configured feeds.
        
        Returns:
            List of normalized topic dictionaries sorted by score descending.
        """
        all_topics: list[dict[str, Any]] = []

        for feed in self.feeds:
            name = feed["name"]
            url = feed["url"]
            category = feed.get("category", "Technology")
            credibility = feed.get("credibility_weight", 1.0)
            source_type = feed.get("source_type", "secondary_press")

            try:
                response = requests.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LinkedInAIAuto/2.0"},
                    timeout=10,
                )
                if response.status_code != 200:
                    err_msg = f"HTTP {response.status_code}"
                    logger.warning(f"Feed [{name}] returned {err_msg}")
                    if self.db and hasattr(self.db, "record_source_attempt"):
                        self.db.record_source_attempt(name, url, source_type, category, credibility, success=False, error=err_msg)
                    continue

                root = ET.fromstring(response.content)

                # Support both standard RSS (<channel><item>) and Atom (<feed><entry>)
                items = root.findall(".//item")
                is_atom = False
                if not items:
                    items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
                    is_atom = True

                count = 0
                for item in items:
                    if count >= limit_per_feed:
                        break

                    if is_atom:
                        ns = {"atom": "http://www.w3.org/2005/Atom"}
                        title_el = item.find("atom:title", ns)
                        link_el = item.find("atom:link", ns)
                        desc_el = item.find("atom:summary", ns)
                        if desc_el is None:
                            desc_el = item.find("atom:content", ns)
                        date_el = item.find("atom:published", ns)
                        if date_el is None:
                            date_el = item.find("atom:updated", ns)

                        title = title_el.text.strip() if title_el is not None and title_el.text else ""
                        link = link_el.attrib.get("href", "") if link_el is not None else ""
                        raw_desc = desc_el.text if desc_el is not None and desc_el.text else ""
                        date_str = date_el.text if date_el is not None and date_el.text else ""
                    else:
                        title_el = item.find("title")
                        link_el = item.find("link")
                        desc_el = item.find("description")
                        date_el = item.find("pubDate")

                        title = title_el.text.strip() if title_el is not None and title_el.text else ""
                        link = link_el.text.strip() if link_el is not None and link_el.text else ""
                        raw_desc = desc_el.text if desc_el is not None and desc_el.text else ""
                        date_str = date_el.text if date_el is not None and date_el.text else ""

                    if not title or not link:
                        continue

                    summary = self._extract_summary(raw_desc)
                    pub_time = self._parse_pub_date(date_str)
                    is_x_related = self._detect_x_trend(title, summary, link)

                    assigned_category = "X Community Trend" if is_x_related else category
                    score = self._calculate_score(title, summary, pub_time, credibility)

                    # Check duplicate against existing posts in database
                    if self.db and self.db.is_topic_already_covered(title, link):
                        logger.debug(f"Skipping duplicate topic: {title[:40]}...")
                        continue

                    all_topics.append(
                        {
                            "title": title,
                            "summary": summary,
                            "source_url": link,
                            "source_name": name,
                            "category": assigned_category,
                            "is_x_discussion": is_x_related,
                            "published_at": pub_time,
                            "score": score,
                        }
                    )
                    count += 1

                if self.db and hasattr(self.db, "record_source_attempt"):
                    self.db.record_source_attempt(name, url, source_type, category, credibility, success=True)

            except Exception as e:
                logger.warning(f"Error fetching feed [{name}] ({url}): {e}")
                if self.db and hasattr(self.db, "record_source_attempt"):
                    self.db.record_source_attempt(name, url, source_type, category, credibility, success=False, error=str(e))

        # Sort topics by highest score
        all_topics.sort(key=lambda t: t["score"], reverse=True)
        logger.info(f"Discovered and scored {len(all_topics)} fresh topics across {len(self.feeds)} feeds.")

        # Optionally persist discovered topics to DB
        if self.db:
            for t in all_topics:
                self.db.save_research_topic(
                    title=t["title"],
                    source_url=t["source_url"],
                    source_name=t["source_name"],
                    category=t["category"],
                    summary=t["summary"],
                    published_at=t["published_at"],
                    score=t["score"],
                )

        return all_topics

    def discover_trends(self, limit_per_feed: int = 5, min_score: float = 0.0) -> list[dict[str, Any]]:
        """Discover, cluster, and rank trends using the TrendIntelligenceEngine."""
        return self.engine.discover_and_rank_trends(limit_per_feed=limit_per_feed, min_score=min_score)

    def get_top_trend(self) -> Optional[dict[str, Any]]:
        """Retrieve the single highest ranked unposted trend cluster."""
        return self.engine.get_top_trend()

    def get_sources_health(self) -> list[dict[str, Any]]:
        """Return health status records for all configured sources."""
        return self.engine.get_sources_health()

    def get_top_topic(self) -> Optional[dict[str, Any]]:
        """Retrieve the single highest ranked, unposted topic (checking trend clusters first)."""
        try:
            top_trend = self.engine.get_top_trend()
            if top_trend:
                return top_trend
        except Exception as e:
            logger.warning(f"Trend engine get_top_trend failed: {e}. Falling back to standard feed fetching.")

        topics = self.fetch_all_topics(limit_per_feed=2)
        return topics[0] if topics else None

    def get_or_create_daily_topic(self) -> dict[str, Any]:
        """Retrieve the top unposted news topic, or fall back to an evergreen technical concept."""
        top_topic = self.get_top_topic()
        if top_topic:
            return top_topic

        # Fallback to an unposted educational technical concept
        logger.info("No fresh unposted news topics available. Selecting educational technical concept...")
        for concept in EVERGREEN_TECHNICAL_CONCEPTS:
            if not self.db or not self.db.is_topic_already_covered(concept["title"], concept["source_url"]):
                return {
                    "title": concept["title"],
                    "summary": concept["summary"],
                    "source_url": concept["source_url"],
                    "source_name": concept["source_name"],
                    "category": concept["category"],
                    "is_x_discussion": False,
                    "published_at": time.time(),
                    "score": 5.0,
                }

        # If all evergreen concepts were covered, recycle the first with fresh timestamp
        first = EVERGREEN_TECHNICAL_CONCEPTS[0]
        return {
            "title": f"{first['title']} - Deep Dive",
            "summary": first["summary"],
            "source_url": first["source_url"],
            "source_name": first["source_name"],
            "category": first["category"],
            "is_x_discussion": False,
            "published_at": time.time(),
            "score": 5.0,
        }

    def get_topic_for_field(
        self,
        field_name: str,
        keywords: list[str],
        clusters: Optional[list[dict[str, Any]]] = None,
        db_topics: Optional[list[dict[str, Any]]] = None,
        exclude_titles: Optional[list[str]] = None,
        exclude_urls: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Retrieve the top unposted topic for a specific domain field (AI, Tech, or Industry Trends)."""
        exclude_titles = exclude_titles or []
        exclude_urls = exclude_urls or []

        # 1. Try trend clusters from the trend intelligence engine
        if clusters is None:
            try:
                clusters = self.engine.discover_and_rank_trends(limit_per_feed=2, min_score=0.0)
            except Exception as e:
                logger.warning(f"Error checking trend clusters for field '{field_name}': {e}")
                clusters = []

        for c in (clusters or []):
            title = c.get("title") or c.get("canonical_title") or c.get("representative_title", "")
            url = c.get("source_url") or c.get("canonical_url") or c.get("primary_source_url", "")
            category = c.get("category", "")
            summary = c.get("summary", "")
            source_name = c.get("source_name") or c.get("primary_source_name", "Industry Intelligence")
            corpus = f"{title} {category} {summary}".lower()

            if not title:
                continue
            if title in exclude_titles or (url and url in exclude_urls):
                continue
            if self.db and self.db.is_topic_already_covered(title, url):
                continue

            if any(kw in corpus for kw in keywords):
                c_copy = dict(c)
                c_copy["title"] = title
                c_copy["source_url"] = url
                c_copy["source_name"] = source_name
                c_copy["target_field"] = field_name
                return c_copy

        # 2. Try raw unposted research topics from SQLite database or feeds
        if db_topics is None and self.db:
            try:
                db_topics = self.db.get_top_unposted_topics(limit=50)
            except Exception as e:
                logger.warning(f"Error checking database topics for field '{field_name}': {e}")
                db_topics = []

        for t in (db_topics or []):
            title = t.get("title", "")
            url = t.get("source_url", "")
            category = t.get("category", "")
            summary = t.get("summary", "")
            corpus = f"{title} {category} {summary}".lower()

            if title in exclude_titles or url in exclude_urls:
                continue
            if self.db and self.db.is_topic_already_covered(title, url):
                continue

            if any(kw in corpus for kw in keywords):
                t_copy = dict(t)
                t_copy["target_field"] = field_name
                return t_copy

        # 3. Fallback to categorized evergreen technical concepts
        for concept in EVERGREEN_TECHNICAL_CONCEPTS:
            title = concept["title"]
            url = concept["source_url"]
            corpus = f"{title} {concept.get('category', '')} {concept.get('summary', '')}".lower()

            if title in exclude_titles or url in exclude_urls:
                continue
            if self.db and self.db.is_topic_already_covered(title, url):
                continue

            if any(kw in corpus for kw in keywords):
                return {
                    "title": title,
                    "summary": concept["summary"],
                    "source_url": url,
                    "source_name": concept["source_name"],
                    "category": concept["category"],
                    "target_field": field_name,
                    "is_x_discussion": False,
                    "published_at": time.time(),
                    "score": 5.0,
                }

        # 4. Fallback if all specific concepts are used
        for concept in EVERGREEN_TECHNICAL_CONCEPTS:
            if concept["title"] not in exclude_titles:
                return {
                    "title": f"{concept['title']} - {field_name}",
                    "summary": concept["summary"],
                    "source_url": concept["source_url"],
                    "source_name": concept["source_name"],
                    "category": concept["category"],
                    "target_field": field_name,
                    "is_x_discussion": False,
                    "published_at": time.time(),
                    "score": 5.0,
                }

        first = EVERGREEN_TECHNICAL_CONCEPTS[0]
        return {
            "title": f"{first['title']} ({field_name} Focus)",
            "summary": first["summary"],
            "source_url": first["source_url"],
            "source_name": first["source_name"],
            "category": first["category"],
            "target_field": field_name,
            "is_x_discussion": False,
            "published_at": time.time(),
            "score": 5.0,
        }

    def get_daily_multi_field_topics(self) -> list[dict[str, Any]]:
        """Retrieve 3 distinct unposted topics across the 3 core fields:
        1. AI News (Frontier models, LLMs, AI labs)
        2. Tech News (Developer tools, Software engineering, Python, Systems)
        3. Industry Trends (Startups, Tech policy, Semiconductors, Hardware, Ecosystem)
        """
        # Discover trends once to share across all field selections
        trend_clusters: list[dict[str, Any]] = []
        try:
            trend_clusters = self.engine.discover_and_rank_trends(limit_per_feed=2, min_score=0.0)
        except Exception as e:
            logger.warning(f"Trend discovery failed in get_daily_multi_field_topics: {e}")

        # Fetch database unposted topics once
        db_topics: list[dict[str, Any]] = []
        if self.db:
            try:
                db_topics = self.db.get_top_unposted_topics(limit=50)
            except Exception as e:
                logger.warning(f"DB unposted topics fetch failed: {e}")

        target_fields = [
            (
                "AI News",
                ["ai", "llm", "model", "frontier", "reasoning", "neural", "deepseek", "anthropic", "openai", "gemini", "agent", "learning", "weights", "benchmark"],
            ),
            (
                "Tech News",
                ["developer", "software", "python", "github", "compiler", "runtime", "linux", "database", "api", "architecture", "code", "engineering", "tools", "cpython", "ebpf"],
            ),
            (
                "Industry & Tech Trends",
                ["industry", "startup", "venture", "market", "policy", "regulation", "nvidia", "semiconductor", "chip", "discussion", "trend", "funding", "safeguard", "cloud", "economics"],
            ),
        ]

        results = []
        used_titles: list[str] = []
        used_urls: list[str] = []

        for field_name, keywords in target_fields:
            topic = self.get_topic_for_field(
                field_name=field_name,
                keywords=keywords,
                clusters=trend_clusters,
                db_topics=db_topics,
                exclude_titles=used_titles,
                exclude_urls=used_urls,
            )
            results.append(topic)
            used_titles.append(topic["title"])
            if topic.get("source_url"):
                used_urls.append(topic["source_url"])

        return results

    @staticmethod
    def validate_url(url: str) -> bool:
        """Validate that a source URL is well-formed."""
        try:
            parsed = urllib.parse.urlparse(url)
            return bool(parsed.scheme in ("http", "https") and parsed.netloc)
        except Exception:
            return False


EVERGREEN_TECHNICAL_CONCEPTS = [
    # 1. AI News & Frontier Research
    {
        "title": "HNSW vs IVF: Vector Indexing for Fast RAG Retrieval",
        "summary": "Hierarchical Navigable Small World (HNSW) graphs offer logarithmic search complexity for nearest neighbor search in vector databases, outperforming flat indexing at scale.",
        "category": "Frontier AI Research",
        "source_name": "Technical Knowledge Base",
        "source_url": "https://en.wikipedia.org/wiki/Vector_database",
    },
    {
        "title": "Slashing LLM Inference Latency with Speculative Decoding",
        "summary": "Speculative decoding uses a smaller draft model to propose token sequences validated in parallel by a larger target model, reducing latency by 2x without quality loss.",
        "category": "Frontier AI Research",
        "source_name": "Technical Knowledge Base",
        "source_url": "https://arxiv.org/abs/2211.17192",
    },
    {
        "title": "Chain-of-Thought Verification in Frontier Reasoning Models",
        "summary": "Test-time compute scaling and reinforcement learning verification allow frontier models to self-correct reasoning paths before emitting token outputs.",
        "category": "Frontier AI Research",
        "source_name": "Technical Knowledge Base",
        "source_url": "https://arxiv.org/abs/2401.00001",
    },
    # 2. General Tech & Software Engineering
    {
        "title": "Faster CPython: Free-Threading & JIT in Modern Python",
        "summary": "Python's evolution with PEP 703 removes the Global Interpreter Lock (GIL) enabling true multi-threaded CPU-bound parallelism for data science and AI workloads.",
        "category": "Python & Software Engineering",
        "source_name": "Python Architecture",
        "source_url": "https://docs.python.org/3/whatsnew/",
    },
    {
        "title": "Token Bucket vs Leaky Bucket Rate Limiting Algorithms",
        "summary": "Token bucket allows bursty traffic up to bucket capacity while leaky bucket enforces a strict constant output rate. Choosing the right algorithm protects API availability.",
        "category": "Software Engineering",
        "source_name": "Systems Architecture",
        "source_url": "https://en.wikipedia.org/wiki/Token_bucket",
    },
    {
        "title": "Zero-Copy Networking with eBPF in High-Throughput Linux Systems",
        "summary": "eBPF programs attached to Linux kernel sockets allow programmable packet processing and observability at wire speed without expensive user-kernel boundary context switches.",
        "category": "Developer Tools & Open Source",
        "source_name": "Systems Architecture",
        "source_url": "https://ebpf.io/",
    },
    # 3. Industry & Tech Trends
    {
        "title": "Designing Resilient Multi-Agent LLM Orchestration",
        "summary": "Building production agentic workflows requires deterministic state machines, idempotent tool calls, and structured error recovery rather than autonomous loops.",
        "category": "AI Industry & Startups",
        "source_name": "Engineering Architecture",
        "source_url": "https://github.com/features/actions",
    },
    {
        "title": "The Economics of Foundation Models: Open Weights vs Cloud APIs",
        "summary": "Engineering teams are navigating the economic trade-offs between hosting open-weight distilled models on reserved GPU instances versus consuming proprietary frontier APIs.",
        "category": "AI Industry & Startups",
        "source_name": "Tech Economics",
        "source_url": "https://techcrunch.com/category/artificial-intelligence/",
    },
    {
        "title": "Semiconductor Fab Geopolitics: TSMC, ASML EUV, and Silicon Sovereignty",
        "summary": "Advanced packaging, High-NA EUV lithography, and sovereign semiconductor fabs are reshaping global supply chains for next-generation AI accelerators.",
        "category": "Hardware & Semiconductors",
        "source_name": "Industry Intelligence",
        "source_url": "https://en.wikipedia.org/wiki/Semiconductor_industry",
    },
]
