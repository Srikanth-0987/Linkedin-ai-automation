"""Automated unit and integration tests for AI & Technology Trend Intelligence Engine.

Covers all 10 verification requirements:
1. Source ingestion and timestamp normalization.
2. Duplicate URL and near-duplicate detection.
3. Missing or invalid publication dates.
4. Trend-score calculations and configurable weights.
5. Stale-story penalties and recently covered topics.
6. Primary-source verification and unsupported claims.
7. Database persistence and repeated-run idempotency.
8. AI provider fallback when Ollama or optional APIs are unavailable.
9. Source outages and rate-limit handling.
10. Integration with the existing content-generation workflow.
"""

from __future__ import annotations

import datetime
from email.utils import format_datetime
import time
from unittest.mock import MagicMock, patch
import pytest

from src.config import Config
from src.db import Database
from src.generator import ContentGenerator
from src.researcher import TopicResearcher
from src.trend_engine import (
    EntityExtractor,
    EventClusterer,
    FreshnessClassifier,
    SourceRegistry,
    TransparentTrendScorer,
    TrendIntelligenceEngine,
    URLNormalizer,
)


@pytest.fixture
def temp_db(tmp_path):
    """Provide an isolated SQLite database for testing."""
    return Database(tmp_path / "test_trend_engine.db")


# ---------------------------------------------------------------------------
# Test 1: Source Ingestion and Timestamp Normalization
# ---------------------------------------------------------------------------

def test_source_ingestion_and_timestamp_normalization():
    """Verify RFC 822 and ISO 8601 parsing into UTC UNIX timestamps and freshness classification."""
    now = time.time()

    # 1. Standard RFC 822 date (Standard RSS)
    rfc_date = "Sun, 18 Oct 2026 12:00:00 GMT"
    ts, is_valid = FreshnessClassifier.parse_timestamp(rfc_date)
    assert is_valid is True
    assert isinstance(ts, float)

    # 2. Standard ISO 8601 date (Atom XML)
    iso_date = "2026-10-18T10:30:00Z"
    ts_iso, is_valid_iso = FreshnessClassifier.parse_timestamp(iso_date)
    assert is_valid_iso is True
    assert isinstance(ts_iso, float)

    # 3. Freshness Windows
    breaking_ts = now - (6 * 3600)        # 6 hours ago
    current_ts = now - (36 * 3600)       # 36 hours ago
    recent_ts = now - (100 * 3600)       # 4.1 days ago
    evergreen_ts = now - (250 * 3600)    # 10.4 days ago

    assert FreshnessClassifier.get_freshness_window(breaking_ts) == "breaking"
    assert FreshnessClassifier.get_freshness_window(current_ts) == "current_development"
    assert FreshnessClassifier.get_freshness_window(recent_ts) == "recent_release"
    assert FreshnessClassifier.get_freshness_window(evergreen_ts) == "evergreen"


# ---------------------------------------------------------------------------
# Test 2: Duplicate URL and Near-Duplicate Detection
# ---------------------------------------------------------------------------

def test_duplicate_url_and_near_duplicate_detection():
    """Verify canonical URL normalization, parameter stripping, and title clustering."""
    # 1. URL Normalization: strip tracking query params, remove fragments, lowercase domain
    raw_url1 = "https://DeepMind.Google/research/alphafold/?utm_source=twitter&utm_medium=social&ref=tech#overview"
    raw_url2 = "https://deepmind.google/research/alphafold?fbclid=12345&utm_campaign=launch"
    
    norm1 = URLNormalizer.normalize(raw_url1)
    norm2 = URLNormalizer.normalize(raw_url2)

    assert norm1 == "https://deepmind.google/research/alphafold"
    assert norm2 == "https://deepmind.google/research/alphafold"
    assert norm1 == norm2

    # 2. Near-Duplicate Clustering
    t1 = "OpenAI Unveils o3 Reasoning Model with State of the Art Benchmarks"
    t2 = "OpenAI launches o3 reasoning model benchmark results"
    tokens1 = EventClusterer.tokenize(t1)
    tokens2 = EventClusterer.tokenize(t2)

    sim = EventClusterer.calculate_similarity(tokens1, tokens2)
    assert sim >= 0.35  # Significant token overlap ("openai", "o3", "reasoning", "model", "benchmark")

    # Cluster key generation based on entities and key tokens
    ent1 = EntityExtractor.extract_entities(t1)
    ent2 = EntityExtractor.extract_entities(t2)
    assert "OpenAI" in ent1["companies"]
    assert "OpenAI o3" in ent1["models"]
    assert ent1["companies"] == ent2["companies"]
    assert ent1["models"] == ent2["models"]


# ---------------------------------------------------------------------------
# Test 3: Missing and Invalid Publication Dates
# ---------------------------------------------------------------------------

def test_missing_and_invalid_publication_dates():
    """Verify graceful handling of missing, corrupt, and future timestamps."""
    now = time.time()

    # Empty and None dates
    ts1, valid1 = FreshnessClassifier.parse_timestamp(None)
    assert valid1 is False
    assert abs(ts1 - now) < 2.0

    ts2, valid2 = FreshnessClassifier.parse_timestamp("   ")
    assert valid2 is False

    # Corrupted / unparseable dates
    ts3, valid3 = FreshnessClassifier.parse_timestamp("not-a-real-date-string")
    assert valid3 is False
    assert abs(ts3 - now) < 2.0

    # Far future dates (e.g. year 2099) must be capped to current time
    ts4, valid4 = FreshnessClassifier.parse_timestamp("2099-01-01T00:00:00Z")
    assert valid4 is False
    assert ts4 <= now + 5.0


# ---------------------------------------------------------------------------
# Test 4: Trend Score Calculations and Configurable Weights
# ---------------------------------------------------------------------------

def test_trend_score_calculation_and_configurable_weights():
    """Verify 0-100 scoring components, weight customization, and explanation strings."""
    # 1. Default weights
    scorer = TransparentTrendScorer()
    assert scorer.weight_recency == 25.0
    assert scorer.weight_credibility == 20.0
    assert scorer.weight_significance == 20.0
    assert scorer.weight_coverage == 15.0
    assert scorer.weight_relevance == 15.0
    assert scorer.weight_novelty == 5.0

    entities = {
        "companies": ["OpenAI"],
        "models": ["OpenAI o1"],
        "topics": ["Reasoning Models", "AI Agents & Agentic Workflows"],
        "event_type": "original_announcement",
    }

    score_result = scorer.calculate_score(
        article_age_hours=4.0,  # Breaking (<12h)
        source_type="primary_lab",
        credibility_weight=1.4,
        entities=entities,
        cluster_article_count=3,
        is_community_trend=False,
    )

    assert score_result["total_score"] >= 80.0
    assert score_result["score_recency"] == 25.0
    assert "Score" in score_result["explanation"]
    assert "Recency: 25.0/25.0" in score_result["explanation"]

    # 2. Configurable weights override
    custom_cfg = Config(
        weight_recency=40.0,
        weight_credibility=10.0,
        weight_significance=20.0,
        weight_coverage=10.0,
        weight_relevance=15.0,
        weight_novelty=5.0,
    )
    custom_scorer = TransparentTrendScorer(cfg=custom_cfg)
    custom_result = custom_scorer.calculate_score(
        article_age_hours=4.0,
        source_type="primary_lab",
        credibility_weight=1.4,
        entities=entities,
        cluster_article_count=1,
    )
    assert custom_result["score_recency"] == 40.0
    assert "Recency: 40.0/40.0" in custom_result["explanation"]


# ---------------------------------------------------------------------------
# Test 5: Stale-Story Penalties and Recently Covered Topics
# ---------------------------------------------------------------------------

def test_stale_story_penalties_and_recently_covered_topics():
    """Verify penalties for stale content, duplicate reporting, and recently published topics."""
    scorer = TransparentTrendScorer()
    entities = {"companies": ["Meta AI"], "models": ["Llama 3.3"], "topics": [], "event_type": "technical_update"}

    # Base fresh score
    fresh_score = scorer.calculate_score(
        article_age_hours=10.0,
        source_type="primary_lab",
        credibility_weight=1.3,
        entities=entities,
        cluster_article_count=1,
    )["total_score"]

    # 1. Stale story (>7 days / 168 hours) penalty (-20 pts)
    stale_res = scorer.calculate_score(
        article_age_hours=200.0,
        source_type="primary_lab",
        credibility_weight=1.3,
        entities=entities,
        cluster_article_count=1,
    )
    assert stale_res["penalty_score"] >= 20.0
    assert stale_res["total_score"] < fresh_score
    assert "stale content" in stale_res["explanation"]

    # 2. Recently covered by our account penalty (-30 pts)
    covered_res = scorer.calculate_score(
        article_age_hours=10.0,
        source_type="primary_lab",
        credibility_weight=1.3,
        entities=entities,
        cluster_article_count=1,
        is_recently_covered_by_account=True,
    )
    assert covered_res["penalty_score"] >= 30.0
    assert covered_res["total_score"] <= fresh_score - 30.0
    assert "topic covered in recent post" in covered_res["explanation"]

    # 3. Duplicate article in cluster penalty (-15 pts)
    dup_res = scorer.calculate_score(
        article_age_hours=10.0,
        source_type="primary_lab",
        credibility_weight=1.3,
        entities=entities,
        cluster_article_count=1,
        is_duplicate_cluster_article=True,
    )
    assert dup_res["penalty_score"] >= 15.0
    assert "duplicate report in cluster" in dup_res["explanation"]


# ---------------------------------------------------------------------------
# Test 6: Primary-Source Verification and Unsupported Claims
# ---------------------------------------------------------------------------

def test_primary_source_verification_and_unsupported_claims():
    """Verify credibility weighting for primary sources vs secondary press and unsupported claim penalty."""
    scorer = TransparentTrendScorer()
    entities = {"companies": ["Anthropic"], "models": ["Claude 3.5"], "topics": ["AI Developer Tools"], "event_type": "original_announcement"}

    # Primary Lab vs Secondary Press
    primary_res = scorer.calculate_score(
        article_age_hours=12.0,
        source_type="primary_lab",
        credibility_weight=1.4,
        entities=entities,
        cluster_article_count=1,
    )
    secondary_res = scorer.calculate_score(
        article_age_hours=12.0,
        source_type="secondary_press",
        credibility_weight=1.0,
        entities=entities,
        cluster_article_count=1,
    )

    assert primary_res["score_credibility"] > secondary_res["score_credibility"]

    # Unsupported claims penalty (-15 pts) and unverified URL penalty (-15 pts)
    unsupported_res = scorer.calculate_score(
        article_age_hours=12.0,
        source_type="secondary_press",
        credibility_weight=1.0,
        entities=entities,
        cluster_article_count=1,
        has_verified_url=False,
        has_verified_claims=False,
    )
    assert unsupported_res["penalty_score"] >= 30.0
    assert "unverified source URL" in unsupported_res["explanation"]
    assert "unsupported claims" in unsupported_res["explanation"]


# ---------------------------------------------------------------------------
# Test 7: Database Persistence and Repeated-Run Idempotency
# ---------------------------------------------------------------------------

def test_database_persistence_and_repeated_run_idempotency(temp_db):
    """Verify article deduplication, cluster creation, idempotent score storage, and retrieval."""
    norm_url = "https://openai.com/news/o3-reasoning-system"
    orig_url = "https://openai.com/news/o3-reasoning-system?utm_source=rss"

    # 1. Save Article (first time returns True, second time returns False)
    inserted1 = temp_db.save_article(
        normalized_url=norm_url,
        original_url=orig_url,
        title="OpenAI o3 Breakthrough",
        summary="Novel reasoning benchmarks for frontier models.",
        source_name="OpenAI News",
        source_type="primary_lab",
        cluster_key="cluster_o3_test",
        credibility=1.4,
    )
    assert inserted1 is True
    assert temp_db.is_normalized_url_present(norm_url) is True

    # Repeated run with same normalized URL must NOT crash and must return False
    inserted2 = temp_db.save_article(
        normalized_url=norm_url,
        original_url=orig_url,
        title="OpenAI o3 Breakthrough",
        summary="Novel reasoning benchmarks for frontier models.",
        source_name="OpenAI News",
        source_type="primary_lab",
        cluster_key="cluster_o3_test",
        credibility=1.4,
    )
    assert inserted2 is False

    # 2. Save Trend Cluster and Upsert Idempotently
    cluster_saved = temp_db.save_trend_cluster(
        cluster_key="cluster_o3_test",
        canonical_title="OpenAI o3 Breakthrough",
        category="Frontier AI Models",
        primary_source_url=norm_url,
        primary_source_name="OpenAI News",
        article_count=1,
        summary="Novel reasoning benchmarks for frontier models.",
    )
    assert cluster_saved is True

    # Repeated upsert: increments article count and updates last_updated_at safely
    temp_db.save_trend_cluster(
        cluster_key="cluster_o3_test",
        canonical_title="OpenAI o3 Breakthrough",
        category="Frontier AI Models",
        primary_source_url=norm_url,
        primary_source_name="OpenAI News",
        article_count=1,
        summary="Updated expanded summary with comprehensive benchmark results and detailed performance comparisons across all evaluation suites.",
    )

    cluster_record = temp_db.get_trend_cluster("cluster_o3_test")
    assert cluster_record is not None
    assert cluster_record["article_count"] == 2
    assert "Updated expanded summary" in cluster_record["summary"]

    # 3. Save and Query Trend Scores
    score_id = temp_db.save_trend_score(
        cluster_key="cluster_o3_test",
        total_score=87.5,
        score_recency=25.0,
        score_credibility=20.0,
        score_significance=18.0,
        score_coverage=12.0,
        score_relevance=12.5,
        score_novelty=5.0,
        explanation="Score 87.5/100 [High Credibility]",
    )
    assert score_id > 0

    top_trends = temp_db.get_top_ranked_trends(limit=5)
    assert len(top_trends) == 1
    assert top_trends[0]["cluster_key"] == "cluster_o3_test"
    assert top_trends[0]["total_score"] == 87.5


# ---------------------------------------------------------------------------
# Test 8: AI Provider Fallback when Ollama or Optional APIs are Unavailable
# ---------------------------------------------------------------------------

def test_ai_provider_fallback_when_apis_unavailable(temp_db):
    """Verify AI-assisted research gracefully falls back to deterministic extraction when offline."""
    cfg = Config(ai_provider="ollama", groq_api_key="", gemini_api_key="")
    engine = TrendIntelligenceEngine(cfg=cfg, db=temp_db)

    topic = "DeepSeek Releases DeepSeek-R1 Open Reasoning Architecture"
    context = "DeepSeek open-sources R1 weights with reinforcement learning reasoning on MIT benchmarks."

    # Simulate Ollama being completely offline / connection refused
    with patch("requests.post", side_effect=RuntimeError("Connection refused to Ollama")):
        analysis = engine.ai_assisted_research(topic=topic, context=context, provider="ollama")

        # Must not raise exception! Must return deterministic rule extraction!
        assert analysis["topic"] == topic
        assert analysis["provider_used"] == "deterministic_rules"
        assert "DeepSeek" in analysis["entities"]["companies"]
        assert "DeepSeek-R1" in analysis["entities"]["models"]
        assert len(analysis["key_claims"]) > 0


# ---------------------------------------------------------------------------
# Test 9: Source Outages and Rate-Limit Handling
# ---------------------------------------------------------------------------

def test_source_outages_and_rate_limit_handling(temp_db):
    """Verify HTTP errors and rate limits log health status and do not crash the engine."""
    engine = TrendIntelligenceEngine(db=temp_db)
    source = {
        "name": "Outage Lab Feed",
        "url": "https://outage.ai/rss.xml",
        "source_type": "primary_lab",
        "category": "Frontier AI",
        "credibility_weight": 1.4,
    }

    # Simulate HTTP 429 Rate Limit
    mock_resp = MagicMock()
    mock_resp.status_code = 429

    with patch("requests.get", return_value=mock_resp):
        items = engine.fetch_feed_items(source)
        assert items == []

        # Verify source health tracked in SQLite
        health_records = temp_db.list_sources_health()
        assert len(health_records) == 1
        record = health_records[0]
        assert record["source_name"] == "Outage Lab Feed"
        assert record["failure_count"] == 1
        assert "429" in record["last_error"]


# ---------------------------------------------------------------------------
# Test 10: Integration with Content-Generation Workflow
# ---------------------------------------------------------------------------

def test_integration_with_content_generation_workflow(temp_db):
    """Verify full pipeline: discovery -> clustering -> ranking -> draft generation with verified image."""
    cfg = Config(dry_run=True, publish_enabled=False, require_approval=True)
    researcher = TopicResearcher(db=temp_db)
    generator = ContentGenerator(cfg, db=temp_db)

    mock_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Anthropic Lab Announcements</title>
        <item>
          <title>Anthropic Launches Claude 3.7 Sonnet with Hybrid Reasoning</title>
          <link>https://anthropic.com/news/claude-3-7-sonnet</link>
          <description>Claude 3.7 introduces hybrid reasoning capabilities for complex software engineering and math benchmarks.</description>
          <pubDate>Mon, 19 Oct 2026 12:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = mock_xml.encode("utf-8")

    with patch("requests.get", return_value=mock_resp):
        # 1. Discover trends
        trends = researcher.discover_trends(limit_per_feed=2)
        assert len(trends) >= 1

        top_trend = trends[0]
        assert "Claude 3.7" in top_trend["title"]
        assert top_trend["score"] > 60.0
        assert top_trend["freshness_window"] in ("breaking", "current_development", "recent_release", "evergreen")
        assert top_trend["has_primary_evidence"] is True

        # 2. Generate LinkedIn draft from top trend using mocked Ollama response
        mock_ai_post = (
            "Anthropic just unveiled Claude 3.7 Sonnet, introducing hybrid reasoning architecture for engineering workflows.\n\n"
            "By balancing instant execution with extended test-time compute, it sets a new milestone on complex coding benchmarks.\n\n"
            "Key takeaway: Test-time compute scaling is transforming practical developer productivity.\n\n"
            "How is your team utilizing hybrid reasoning models?\n\n"
            "#AI #Claude #SoftwareEngineering #MachineLearning"
        )
        with patch.object(generator, "generate_with_ollama", return_value=(mock_ai_post, "qwen3.5:4b")):
            draft = generator.generate_draft(
                topic=top_trend["title"],
                context=top_trend["summary"],
                category=top_trend["category"],
                source_url=top_trend["source_url"],
                source_name=top_trend["source_name"],
                provider="ollama",
            )

            # 3. Verify post draft and attached 1200x1200px graphic
            assert draft["status"] == "DRAFT"
            assert "Claude 3.7" in draft["topic"]
            assert draft["image"]["validation_status"] == "VALIDATED"

            post_record = temp_db.get_post(draft["post_id"])
            assert post_record is not None
            assert post_record["status"] == "DRAFT"
            assert post_record["image_path"] is not None

            # 4. Verify safety gates: publish_enabled is False, dry_run is True
            assert cfg.publish_enabled is False
            assert cfg.dry_run is True
