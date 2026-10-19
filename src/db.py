"""SQLite database management for LinkedIn Automation.

Stores OAuth states, tokens, research topics, and post history with duplicate detection.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Any, Generator, Optional


class Database:
    """Manages persistence for OAuth states, tokens, research topics, and content posts."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._init_db()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager that ensures the SQLite connection is closed on exit."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create tables if they do not exist, and apply non-destructive migrations."""
        with self._connection() as conn:
            cursor = conn.cursor()

            # OAuth state table (CSRF defense)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    consumed INTEGER DEFAULT 0
                )
                """
            )

            # OAuth tokens table (Single active token record)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    access_token TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    scope TEXT,
                    member_id TEXT,
                    member_name TEXT,
                    member_email TEXT,
                    updated_at REAL NOT NULL
                )
                """
            )

            # Research topics table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS research_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    category TEXT,
                    source_url TEXT UNIQUE NOT NULL,
                    source_name TEXT,
                    summary TEXT,
                    published_at REAL,
                    score REAL DEFAULT 0.0,
                    used_in_post_id INTEGER,
                    created_at REAL NOT NULL
                )
                """
            )

            # Posts table with content hash for deduplication
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT,
                    category TEXT,
                    commentary TEXT NOT NULL,
                    source_url TEXT,
                    source_name TEXT,
                    ai_provider TEXT,
                    ai_model TEXT,
                    fallback_used INTEGER DEFAULT 0,
                    validation_status TEXT DEFAULT 'VALIDATED',
                    image_path TEXT,
                    image_urn TEXT,
                    image_hash TEXT,
                    image_alt_text TEXT,
                    image_width INTEGER,
                    image_height INTEGER,
                    image_validation_status TEXT,
                    status TEXT NOT NULL DEFAULT 'DRAFT',
                    content_hash TEXT UNIQUE NOT NULL,
                    scheduled_for REAL,
                    published_at REAL,
                    linkedin_post_id TEXT,
                    linkedin_urn TEXT,
                    error_message TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

            # Safe column additions for existing databases
            existing_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(posts)").fetchall()}
            optional_cols = [
                ("category", "TEXT"),
                ("source_name", "TEXT"),
                ("ai_provider", "TEXT"),
                ("ai_model", "TEXT"),
                ("fallback_used", "INTEGER DEFAULT 0"),
                ("validation_status", "TEXT DEFAULT 'VALIDATED'"),
                ("image_path", "TEXT"),
                ("image_urn", "TEXT"),
                ("image_hash", "TEXT"),
                ("image_alt_text", "TEXT"),
                ("image_width", "INTEGER"),
                ("image_height", "INTEGER"),
                ("image_validation_status", "TEXT"),
            ]
            for col_name, col_type in optional_cols:
                if col_name not in existing_columns:
                    cursor.execute(f"ALTER TABLE posts ADD COLUMN {col_name} {col_type}")

            # --- Trend Intelligence Tables ---

            # 1. Source Health table (tracks health, successes, failures, rate limits, and latency)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS source_health (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT UNIQUE NOT NULL,
                    url TEXT NOT NULL,
                    source_type TEXT DEFAULT 'secondary_press',
                    category TEXT,
                    credibility_weight REAL DEFAULT 1.0,
                    last_attempt_at REAL,
                    last_success_at REAL,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    last_error TEXT,
                    status TEXT DEFAULT 'HEALTHY',
                    updated_at REAL NOT NULL
                )
                """
            )

            # 2. Trend Clusters table (deduplicated clusters representing genuine developments)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS trend_clusters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cluster_key TEXT UNIQUE NOT NULL,
                    canonical_title TEXT NOT NULL,
                    category TEXT,
                    event_type TEXT DEFAULT 'original_announcement',
                    primary_source_url TEXT,
                    primary_source_name TEXT,
                    article_count INTEGER DEFAULT 1,
                    entities TEXT,
                    freshness_window TEXT DEFAULT 'breaking',
                    momentum TEXT DEFAULT 'rising',
                    summary TEXT,
                    first_seen_at REAL NOT NULL,
                    last_updated_at REAL NOT NULL
                )
                """
            )

            # 3. Research Articles table (every discovered item with normalized URL)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS research_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    normalized_url TEXT UNIQUE NOT NULL,
                    original_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT,
                    source_name TEXT NOT NULL,
                    source_type TEXT DEFAULT 'secondary_press',
                    author TEXT,
                    published_at REAL,
                    first_seen_at REAL NOT NULL,
                    cluster_key TEXT,
                    entities TEXT,
                    credibility REAL DEFAULT 1.0
                )
                """
            )

            # 4. Trend Scores table (historical breakdown of 0-100 component scores & rationale)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS trend_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cluster_key TEXT NOT NULL,
                    total_score REAL NOT NULL,
                    score_recency REAL NOT NULL,
                    score_credibility REAL NOT NULL,
                    score_significance REAL NOT NULL,
                    score_coverage REAL NOT NULL,
                    score_relevance REAL NOT NULL,
                    score_novelty REAL NOT NULL,
                    penalty_score REAL DEFAULT 0.0,
                    explanation TEXT,
                    calculated_at REAL NOT NULL
                )
                """
            )

            # Performance & Deduplication Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_cluster ON research_articles(cluster_key)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_scores_cluster ON trend_scores(cluster_key)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clusters_updated ON trend_clusters(last_updated_at)")

            conn.commit()

    @staticmethod
    def compute_content_hash(commentary: str) -> str:
        """Compute SHA-256 hash of normalized post commentary."""
        normalized = " ".join(commentary.strip().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    # --- OAuth States ---

    def save_oauth_state(self, state: str, ttl_seconds: int = 600) -> None:
        """Save a new CSRF state with a TTL."""
        now = time.time()
        expires_at = now + ttl_seconds
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO oauth_states (state, created_at, expires_at, consumed) VALUES (?, ?, ?, 0)",
                (state, now, expires_at),
            )
            conn.commit()

    def validate_and_consume_state(self, state: str) -> tuple[bool, str]:
        """Validate state token and atomically mark it as consumed.
        
        Returns:
            (is_valid, reason_message)
        """
        if not state:
            return False, "Empty state parameter"

        now = time.time()
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT state, expires_at, consumed FROM oauth_states WHERE state = ?", (state,))
            row = cursor.fetchone()

            if not row:
                return False, "Unknown or forged OAuth state"

            if row["consumed"] == 1:
                return False, "OAuth state has already been consumed (replay attack prevention)"

            if now > row["expires_at"]:
                return False, "OAuth state has expired"

            # Atomically mark as consumed
            cursor.execute("UPDATE oauth_states SET consumed = 1 WHERE state = ?", (state,))
            conn.commit()
            return True, "Valid state"

    # --- OAuth Tokens ---

    def save_token(
        self,
        access_token: str,
        expires_in: int,
        scope: str = "",
        member_id: str = "",
        member_name: str = "",
        member_email: str = "",
    ) -> None:
        """Store or update the active LinkedIn access token."""
        now = time.time()
        expires_at = now + float(expires_in)
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO oauth_tokens (id, access_token, expires_at, scope, member_id, member_name, member_email, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    access_token = excluded.access_token,
                    expires_at = excluded.expires_at,
                    scope = excluded.scope,
                    member_id = excluded.member_id,
                    member_name = excluded.member_name,
                    member_email = excluded.member_email,
                    updated_at = excluded.updated_at
                """,
                (access_token, expires_at, scope, member_id, member_name, member_email, now),
            )
            conn.commit()

    def get_token(self) -> Optional[dict[str, Any]]:
        """Retrieve the currently stored token, if any."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM oauth_tokens WHERE id = 1")
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)

    def is_token_valid(self, buffer_seconds: int = 300) -> bool:
        """Check if stored token exists and has not expired."""
        token = self.get_token()
        if not token or not token.get("access_token"):
            return False
        return (token["expires_at"] - buffer_seconds) > time.time()

    # --- Research Topics ---

    def save_research_topic(
        self,
        title: str,
        source_url: str,
        source_name: str = "",
        category: str = "Technology",
        summary: str = "",
        published_at: Optional[float] = None,
        score: float = 0.0,
    ) -> Optional[int]:
        """Save a discovered research topic. Returns topic ID or None if already exists."""
        now = time.time()
        with self._connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO research_topics (title, category, source_url, source_name, summary, published_at, score, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (title, category, source_url, source_name, summary, published_at or now, score, now),
                )
                conn.commit()
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                # URL already exists in database
                return None

    def get_top_unposted_topics(self, limit: int = 10) -> list[dict[str, Any]]:
        """Retrieve highest scored topics that haven't been turned into posts yet."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM research_topics 
                WHERE used_in_post_id IS NULL 
                ORDER BY score DESC, published_at DESC 
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def mark_topic_used(self, topic_id: int, post_id: int) -> bool:
        """Link a research topic to its generated post."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE research_topics SET used_in_post_id = ? WHERE id = ?",
                (post_id, topic_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def is_topic_already_covered(self, title: str, source_url: str = "") -> bool:
        """Check if a topic or URL has already been recorded or published."""
        with self._connection() as conn:
            cursor = conn.cursor()
            if source_url:
                cursor.execute("SELECT id FROM posts WHERE source_url = ?", (source_url,))
                if cursor.fetchone():
                    return True
                cursor.execute("SELECT id FROM research_topics WHERE source_url = ? AND used_in_post_id IS NOT NULL", (source_url,))
                if cursor.fetchone():
                    return True

            normalized_title = " ".join(title.strip().lower().split())
            cursor.execute("SELECT id, topic FROM posts")
            for row in cursor.fetchall():
                if row["topic"] and " ".join(row["topic"].strip().lower().split()) == normalized_title:
                    return True

            return False

    def is_topic_duplicate(self, title: str, source_url: str = "") -> bool:
        """Alias for is_topic_already_covered."""
        return self.is_topic_already_covered(title=title, source_url=source_url)

    # --- Posts Management ---

    def create_post(
        self,
        commentary: str,
        topic: str = "",
        category: str = "Technology",
        source_url: str = "",
        source_name: str = "",
        ai_provider: str = "",
        ai_model: str = "",
        fallback_used: bool = False,
        validation_status: str = "VALIDATED",
        scheduled_for: Optional[float] = None,
    ) -> int:
        """Create a new post draft.
        
        Raises:
            ValueError: If identical content already exists.
        """
        content_hash = self.compute_content_hash(commentary)
        now = time.time()
        with self._connection() as conn:
            cursor = conn.cursor()
            # Check duplicate
            cursor.execute("SELECT id, status FROM posts WHERE content_hash = ?", (content_hash,))
            existing = cursor.fetchone()
            if existing:
                raise ValueError(
                    f"Duplicate post content detected: Matches existing post #{existing['id']} with status '{existing['status']}'."
                )

            cursor.execute(
                """
                INSERT INTO posts (
                    topic, category, commentary, source_url, source_name,
                    ai_provider, ai_model, fallback_used, validation_status,
                    status, content_hash, scheduled_for, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?, ?)
                """,
                (
                    topic,
                    category,
                    commentary,
                    source_url,
                    source_name,
                    ai_provider,
                    ai_model,
                    1 if fallback_used else 0,
                    validation_status,
                    content_hash,
                    scheduled_for,
                    now,
                    now,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def approve_post(self, post_id: int) -> bool:
        """Approve a draft post for publishing (also allows retrying FAILED posts)."""
        now = time.time()
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE posts SET status = 'APPROVED', error_message = NULL, updated_at = ? WHERE id = ? AND status IN ('DRAFT', 'FAILED')",
                (now, post_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def mark_post_published(self, post_id: int, linkedin_post_id: str, linkedin_urn: str = "") -> bool:
        """Mark post as published and record post ID."""
        now = time.time()
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE posts 
                SET status = 'PUBLISHED', 
                    published_at = ?, 
                    linkedin_post_id = ?, 
                    linkedin_urn = ?, 
                    error_message = NULL, 
                    updated_at = ? 
                WHERE id = ?
                """,
                (now, linkedin_post_id, linkedin_urn, now, post_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def mark_post_failed(self, post_id: int, error_message: str) -> bool:
        """Record post failure."""
        now = time.time()
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE posts SET status = 'FAILED', error_message = ?, updated_at = ? WHERE id = ?",
                (error_message, now, post_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_post(self, post_id: int) -> Optional[dict[str, Any]]:
        """Fetch post record by ID."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def attach_image_to_post(
        self,
        post_id: int,
        image_path: str,
        image_hash: str,
        image_alt_text: str,
        image_width: int = 1200,
        image_height: int = 1200,
        validation_status: str = "VALIDATED",
    ) -> bool:
        """Associate a generated image and its metadata with a post draft."""
        now = time.time()
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE posts 
                SET image_path = ?, 
                    image_hash = ?, 
                    image_alt_text = ?, 
                    image_width = ?, 
                    image_height = ?, 
                    image_validation_status = ?, 
                    updated_at = ? 
                WHERE id = ?
                """,
                (
                    image_path,
                    image_hash,
                    image_alt_text,
                    image_width,
                    image_height,
                    validation_status,
                    now,
                    post_id,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_post_image_urn(self, post_id: int, image_urn: str) -> bool:
        """Record the uploaded LinkedIn image URN."""
        now = time.time()
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE posts SET image_urn = ?, updated_at = ? WHERE id = ?",
                (image_urn, now, post_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def is_image_hash_duplicate(self, image_hash: str) -> bool:
        """Check if an identical image has already been generated or published."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM posts WHERE image_hash = ? AND status = 'PUBLISHED'", (image_hash,))
            return cursor.fetchone() is not None

    def list_posts(self, status: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        """List posts, optionally filtered by status."""
        with self._connection() as conn:
            cursor = conn.cursor()
            if status:
                cursor.execute(
                    "SELECT * FROM posts WHERE status = ? ORDER BY id DESC LIMIT ?",
                    (status.upper(), limit),
                )
            else:
                cursor.execute("SELECT * FROM posts ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # --- Trend Intelligence & Source Registry Methods ---

    def record_source_attempt(
        self,
        source_name: str,
        url: str,
        source_type: str = "secondary_press",
        category: str = "Technology",
        credibility_weight: float = 1.0,
        success: bool = True,
        error: str = "",
    ) -> None:
        """Track source health, fetch attempts, successes, failures, and errors."""
        now = time.time()
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO source_health (
                    source_name, url, source_type, category, credibility_weight,
                    last_attempt_at, last_success_at, success_count, failure_count,
                    last_error, status, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_name) DO UPDATE SET
                    url = excluded.url,
                    source_type = excluded.source_type,
                    category = excluded.category,
                    credibility_weight = excluded.credibility_weight,
                    last_attempt_at = excluded.last_attempt_at,
                    last_success_at = CASE WHEN excluded.last_success_at IS NOT NULL THEN excluded.last_success_at ELSE source_health.last_success_at END,
                    success_count = source_health.success_count + (CASE WHEN ? = 1 THEN 1 ELSE 0 END),
                    failure_count = source_health.failure_count + (CASE WHEN ? = 0 THEN 1 ELSE 0 END),
                    last_error = CASE WHEN ? != '' THEN ? ELSE source_health.last_error END,
                    status = CASE 
                        WHEN ? = 1 THEN 'HEALTHY' 
                        WHEN source_health.failure_count >= 3 THEN 'FAILING'
                        ELSE 'DEGRADED' 
                    END,
                    updated_at = excluded.updated_at
                """,
                (
                    source_name,
                    url,
                    source_type,
                    category,
                    credibility_weight,
                    now,
                    now if success else None,
                    1 if success else 0,
                    0 if success else 1,
                    error if not success else None,
                    "HEALTHY" if success else "DEGRADED",
                    now,
                    1 if success else 0,
                    0 if success else 1,
                    error,
                    error,
                    1 if success else 0,
                ),
            )
            conn.commit()

    def list_sources_health(self) -> list[dict[str, Any]]:
        """Retrieve health status records for all configured sources."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM source_health ORDER BY status ASC, source_name ASC")
            return [dict(row) for row in cursor.fetchall()]

    def is_normalized_url_present(self, normalized_url: str) -> bool:
        """Check if an article with the normalized URL has already been ingested."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM research_articles WHERE normalized_url = ?", (normalized_url,))
            return cursor.fetchone() is not None

    def save_article(
        self,
        normalized_url: str,
        original_url: str,
        title: str,
        summary: str,
        source_name: str,
        source_type: str = "secondary_press",
        author: str = "",
        published_at: Optional[float] = None,
        cluster_key: str = "",
        entities: Optional[dict[str, Any]] = None,
        credibility: float = 1.0,
    ) -> bool:
        """Save a normalized article record. Returns True if newly inserted, False if duplicate."""
        now = time.time()
        import json
        entities_json = json.dumps(entities or {})
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO research_articles (
                    normalized_url, original_url, title, summary, source_name,
                    source_type, author, published_at, first_seen_at, cluster_key,
                    entities, credibility
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_url,
                    original_url,
                    title,
                    summary,
                    source_name,
                    source_type,
                    author,
                    published_at or now,
                    now,
                    cluster_key,
                    entities_json,
                    credibility,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def save_trend_cluster(
        self,
        cluster_key: str,
        canonical_title: str,
        category: str = "Technology",
        event_type: str = "original_announcement",
        primary_source_url: str = "",
        primary_source_name: str = "",
        article_count: int = 1,
        entities: Optional[dict[str, Any]] = None,
        freshness_window: str = "breaking",
        momentum: str = "rising",
        summary: str = "",
    ) -> bool:
        """Create or update a trend cluster."""
        now = time.time()
        import json
        entities_json = json.dumps(entities or {})
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO trend_clusters (
                    cluster_key, canonical_title, category, event_type,
                    primary_source_url, primary_source_name, article_count,
                    entities, freshness_window, momentum, summary, first_seen_at, last_updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cluster_key) DO UPDATE SET
                    canonical_title = excluded.canonical_title,
                    category = excluded.category,
                    event_type = CASE WHEN excluded.event_type = 'original_announcement' THEN excluded.event_type ELSE trend_clusters.event_type END,
                    primary_source_url = CASE WHEN excluded.primary_source_url != '' THEN excluded.primary_source_url ELSE trend_clusters.primary_source_url END,
                    primary_source_name = CASE WHEN excluded.primary_source_name != '' THEN excluded.primary_source_name ELSE trend_clusters.primary_source_name END,
                    article_count = trend_clusters.article_count + excluded.article_count,
                    entities = excluded.entities,
                    freshness_window = excluded.freshness_window,
                    momentum = excluded.momentum,
                    summary = CASE WHEN length(excluded.summary) > length(trend_clusters.summary) THEN excluded.summary ELSE trend_clusters.summary END,
                    last_updated_at = excluded.last_updated_at
                """,
                (
                    cluster_key,
                    canonical_title,
                    category,
                    event_type,
                    primary_source_url,
                    primary_source_name,
                    article_count,
                    entities_json,
                    freshness_window,
                    momentum,
                    summary,
                    now,
                    now,
                ),
            )
            conn.commit()
            return True

    def save_trend_score(
        self,
        cluster_key: str,
        total_score: float,
        score_recency: float,
        score_credibility: float,
        score_significance: float,
        score_coverage: float,
        score_relevance: float,
        score_novelty: float,
        penalty_score: float = 0.0,
        explanation: str = "",
    ) -> int:
        """Record transparent scoring breakdown for a cluster."""
        now = time.time()
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO trend_scores (
                    cluster_key, total_score, score_recency, score_credibility,
                    score_significance, score_coverage, score_relevance, score_novelty,
                    penalty_score, explanation, calculated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cluster_key,
                    total_score,
                    score_recency,
                    score_credibility,
                    score_significance,
                    score_coverage,
                    score_relevance,
                    score_novelty,
                    penalty_score,
                    explanation,
                    now,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_top_ranked_trends(self, limit: int = 15, min_score: float = 0.0) -> list[dict[str, Any]]:
        """Retrieve top ranked trend clusters with their latest component scores."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT c.*, s.total_score, s.score_recency, s.score_credibility,
                       s.score_significance, s.score_coverage, s.score_relevance,
                       s.score_novelty, s.penalty_score, s.explanation, s.calculated_at
                FROM trend_clusters c
                JOIN (
                    SELECT cluster_key, total_score, score_recency, score_credibility,
                           score_significance, score_coverage, score_relevance,
                           score_novelty, penalty_score, explanation, calculated_at,
                           ROW_NUMBER() OVER(PARTITION BY cluster_key ORDER BY calculated_at DESC) as rn
                    FROM trend_scores
                ) s ON c.cluster_key = s.cluster_key AND s.rn = 1
                WHERE s.total_score >= ?
                ORDER BY s.total_score DESC, c.last_updated_at DESC
                LIMIT ?
                """,
                (min_score, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_trend_cluster(self, cluster_key: str) -> Optional[dict[str, Any]]:
        """Retrieve a specific cluster by its unique key."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trend_clusters WHERE cluster_key = ?", (cluster_key,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_cluster_articles(self, cluster_key: str) -> list[dict[str, Any]]:
        """Retrieve all articles grouped in a specific cluster."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM research_articles WHERE cluster_key = ? ORDER BY published_at DESC", (cluster_key,))
            return [dict(row) for row in cursor.fetchall()]

    def get_recent_published_topics(self, lookback_days: int = 14) -> list[str]:
        """Retrieve titles/topics of posts published or drafted within lookback window."""
        cutoff = time.time() - (lookback_days * 86400)
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT topic FROM posts WHERE created_at >= ? AND topic IS NOT NULL AND topic != ''", (cutoff,))
            return [row["topic"] for row in cursor.fetchall()]
