"""Tests for TopicResearcher: RSS parsing, topic ranking, deduplication, and X trend tracking."""

import time
from unittest.mock import MagicMock, patch
import pytest

from src.db import Database
from src.researcher import TopicResearcher


import datetime
from email.utils import format_datetime

_now_rfc822 = format_datetime(datetime.datetime.now(datetime.timezone.utc))

MOCK_RSS_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>AI Frontier News</title>
    <item>
      <title>Breakthrough in Multi-Agent Reasoning and Architecture</title>
      <link>https://example.com/multi-agent-reasoning</link>
      <description>&lt;p&gt;Researchers demonstrated novel agent workflows achieving 95% on benchmark.&lt;/p&gt;</description>
      <pubDate>{_now_rfc822}</pubDate>
    </item>
    <item>
      <title>Discussion on X: Why open weights are winning</title>
      <link>https://example.com/x-discussion-open-weights</link>
      <description>Engineers on x.com/tech debate the future of open LLM weights.</description>
      <pubDate>{_now_rfc822}</pubDate>
    </item>
  </channel>
</rss>
"""

MOCK_ATOM_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>DeepMind Research</title>
  <entry>
    <title>Scalable Automated Code Optimization with LLMs</title>
    <link href="https://deepmind.google/research/code-opt" />
    <summary>A new technique for compiler optimizations using neural networks.</summary>
    <published>2026-10-18T18:00:00Z</published>
  </entry>
</feed>
"""


@pytest.fixture
def temp_db(tmp_path):
    return Database(tmp_path / "test_research.db")


def test_rss_parsing_and_x_trend_detection(temp_db):
    """Test RSS XML parsing, scoring, and X/Twitter trend identification."""
    feed_config = [
        {
            "name": "Mock AI RSS",
            "url": "https://mock.com/rss",
            "category": "Frontier AI",
            "credibility_weight": 1.2,
        }
    ]
    researcher = TopicResearcher(feeds=feed_config, db=temp_db)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = MOCK_RSS_XML.encode("utf-8")

    with patch("requests.get", return_value=mock_resp):
        topics = researcher.fetch_all_topics(limit_per_feed=5)

        assert len(topics) == 2
        # Check first topic
        t1 = next(t for t in topics if "Multi-Agent" in t["title"])
        assert t1["category"] == "Frontier AI"
        assert t1["score"] > 5.0  # Boosted by keywords "agent", "reasoning", "benchmark"
        assert "novel agent workflows" in t1["summary"]

        # Check second topic (X trend detection)
        t2 = next(t for t in topics if "Discussion on X" in t["title"])
        assert t2["is_x_discussion"] is True
        assert t2["category"] == "X Community Trend"


def test_atom_feed_parsing(temp_db):
    """Test Atom XML feed format parsing."""
    feed_config = [
        {
            "name": "Mock Atom Feed",
            "url": "https://mock.com/atom",
            "category": "DeepMind Research",
            "credibility_weight": 1.2,
        }
    ]
    researcher = TopicResearcher(feeds=feed_config, db=temp_db)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = MOCK_ATOM_XML.encode("utf-8")

    with patch("requests.get", return_value=mock_resp):
        topics = researcher.fetch_all_topics(limit_per_feed=5)

        assert len(topics) == 1
        t = topics[0]
        assert t["title"] == "Scalable Automated Code Optimization with LLMs"
        assert t["source_url"] == "https://deepmind.google/research/code-opt"
        assert "compiler optimizations" in t["summary"]


def test_invalid_feed_url_handled_gracefully(temp_db):
    """Test that HTTP errors or corrupt XML feeds do not crash the pipeline."""
    feed_config = [
        {"name": "Broken Feed", "url": "https://broken.com/rss", "category": "Tech"}
    ]
    researcher = TopicResearcher(feeds=feed_config, db=temp_db)

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.content = b"Server Error"

    with patch("requests.get", return_value=mock_resp):
        topics = researcher.fetch_all_topics()
        assert topics == []


def test_topic_deduplication(temp_db):
    """Test that topics already published or saved in the database are not duplicated."""
    feed_config = [
        {"name": "Deduplication Feed", "url": "https://mock.com/rss", "category": "AI"}
    ]
    researcher = TopicResearcher(feeds=feed_config, db=temp_db)

    # Seed DB with an existing post
    temp_db.create_post(
        commentary="Existing commentary on multi-agent reasoning.",
        topic="Breakthrough in Multi-Agent Reasoning and Architecture",
        source_url="https://example.com/multi-agent-reasoning",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = MOCK_RSS_XML.encode("utf-8")

    with patch("requests.get", return_value=mock_resp):
        topics = researcher.fetch_all_topics()
        # The topic with URL https://example.com/multi-agent-reasoning must be filtered out!
        urls = [t["source_url"] for t in topics]
        assert "https://example.com/multi-agent-reasoning" not in urls
        assert "https://example.com/x-discussion-open-weights" in urls


def test_url_validation():
    """Test URL structure validation helper."""
    assert TopicResearcher.validate_url("https://huggingface.co/blog/new-model") is True
    assert TopicResearcher.validate_url("http://github.com/trending") is True
    assert TopicResearcher.validate_url("not_a_valid_url") is False
    assert TopicResearcher.validate_url("") is False
    assert TopicResearcher.validate_url("ftp://unsupported.com") is False


def test_daily_multi_field_topics_selection(temp_db):
    """Verify get_daily_multi_field_topics returns 3 distinct topics across AI, Tech, and Industry fields."""
    researcher = TopicResearcher(feeds=[], db=temp_db)
    mock_clusters = [
        {
            "canonical_title": "DeepSeek R1 Open Weights Reasoning Breakthrough",
            "summary": "DeepSeek unveils open weights reasoning model rivaling OpenAI o1 on coding and mathematics.",
            "canonical_url": "https://example.com/deepseek-r1",
            "category": "Frontier AI Models",
            "primary_source_name": "AI Lab",
            "sources": [{"name": "AI Lab"}],
            "score": 92.0,
            "representative_title": "DeepSeek R1 Open Weights Reasoning Breakthrough",
        },
        {
            "canonical_title": "CPython 3.14 Removes GIL for Multi-Threaded Developer Scale",
            "summary": "The Python core developers announce free-threading optimizations in the runtime.",
            "canonical_url": "https://example.com/cpython-gil",
            "category": "Developer Tools",
            "primary_source_name": "Python News",
            "sources": [{"name": "Python News"}],
            "score": 88.0,
            "representative_title": "CPython 3.14 Removes GIL for Multi-Threaded Developer Scale",
        },
        {
            "canonical_title": "Global Semiconductor Fab Expansion Drives AI Infrastructure",
            "summary": "Venture capital and chip startups accelerate custom ASIC developments for inference economics.",
            "canonical_url": "https://example.com/semiconductor-ai",
            "category": "Industry Intelligence",
            "primary_source_name": "Tech Economics",
            "sources": [{"name": "Tech Economics"}],
            "score": 85.0,
            "representative_title": "Global Semiconductor Fab Expansion Drives AI Infrastructure",
        },
    ]

    with patch.object(researcher.engine, "discover_and_rank_trends", return_value=mock_clusters):
        topics = researcher.get_daily_multi_field_topics()

    assert len(topics) == 3
    fields = [t["target_field"] for t in topics]
    assert "AI News" in fields
    assert "Tech News" in fields
    assert "Industry & Tech Trends" in fields

    # Verify topics are distinct
    titles = [t["title"] for t in topics]
    assert len(set(titles)) == 3

    # Also verify fallback to evergreen technical concepts when no clusters match
    with patch.object(researcher.engine, "discover_and_rank_trends", return_value=[]):
        fallback_topics = researcher.get_daily_multi_field_topics()
    assert len(fallback_topics) == 3
    fallback_titles = [t["title"] for t in fallback_topics]
    assert len(set(fallback_titles)) == 3


def test_curate_trending_news_with_groq_mocked_success(temp_db):
    """Verify curate_trending_news_with_groq queries Groq and enriches 3 final topics."""
    researcher = TopicResearcher(db=temp_db)

    mock_topics = [
        {"title": "OpenAI Launches Next-Gen Reasoning Model", "category": "Frontier AI", "summary": "Breakthrough in reasoning compute.", "source_url": "https://example.com/1", "source_name": "OpenAI"},
        {"title": "Linux Kernel 6.14 Merges Fast Socket eBPF Acceleration", "category": "Software Engineering", "summary": "Zero-copy networking for high throughput.", "source_url": "https://example.com/2", "source_name": "Linux"},
        {"title": "Discussion on X: Why Postgres with pgvector is replacing standalone vector DBs", "category": "Twitter / X Community Trends", "summary": "Viral thread debating database consolidation.", "source_url": "https://x.com/tech_debate", "source_name": "X Tech", "is_x_discussion": True},
    ]

    mock_groq_json = """[
        {"slot": 1, "field": "AI News", "candidate_id": 1, "rationale": "Key frontier reasoning milestone."},
        {"slot": 2, "field": "Tech News", "candidate_id": 2, "rationale": "Critical Linux performance architecture."},
        {"slot": 3, "field": "Twitter/X Viral Trend", "candidate_id": 3, "rationale": "High-engagement debate among software architects on X."}
    ]"""

    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock(message=MagicMock(content=mock_groq_json))]

    with patch.object(researcher, "fetch_all_topics", return_value=mock_topics):
        with patch("src.config.config.groq_api_key", "gsk_mock_test_key"):
            with patch("groq.Groq") as mock_groq_cls:
                mock_client = MagicMock()
                mock_client.chat.completions.create.return_value = mock_completion
                mock_groq_cls.return_value = mock_client

                curated = researcher.curate_trending_news_with_groq(limit_per_feed=2)

    assert len(curated) == 3
    assert curated[0]["target_field"] == "AI News"
    assert curated[0]["groq_curated"] is True
    assert "reasoning milestone" in curated[0]["curation_rationale"]
    assert curated[2]["target_field"] == "Twitter/X Viral Trend"
    assert "architects on X" in curated[2]["curation_rationale"]


def test_curate_trending_news_with_groq_fallback_on_error(temp_db):
    """Verify graceful fallback to heuristic multi-field selection if Groq fails."""
    researcher = TopicResearcher(db=temp_db)

    with patch.object(researcher, "fetch_all_topics", side_effect=Exception("Network error")):
        with patch.object(researcher.engine, "discover_and_rank_trends", return_value=[]):
            fallback = researcher.curate_trending_news_with_groq()

    assert len(fallback) == 3
    fields = [t["target_field"] for t in fallback]
    assert "AI News" in fields


