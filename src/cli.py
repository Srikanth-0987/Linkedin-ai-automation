"""Command Line Interface for LinkedIn AI Content Automation.

Manage OAuth, check credentials, research trends, generate AI posts, approve drafts, and publish safely.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time
import webbrowser

# Ensure clean UTF-8 encoding across Windows terminal environments
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from loguru import logger

from src.callback_server import start_callback_server
from src.config import config, redact_secret
from src.db import Database
from src.generator import ContentGenerator
from src.image_generator import (
    ImageGenerator,
    ImageValidator,
    extract_image_elements,
    synthesize_realistic_poster_prompt,
)
from src.oauth import LinkedInOAuth
from src.publisher import LinkedInPublisher, PublisherError
from src.researcher import TopicResearcher


def cmd_status(args: argparse.Namespace) -> None:
    """Display configuration, AI providers, database statistics, and token status."""
    db = Database(config.database_path)
    token = db.get_token()

    print("\n" + "=" * 65)
    print("       LINKEDIN AI AUTOMATION - SYSTEM STATUS")
    print("=" * 65)

    print("\n[SAFETY SETTINGS]")
    print(f"  DRY_RUN:          {config.dry_run} (Simulates publishing without API calls)")
    print(f"  PUBLISH_ENABLED:  {config.publish_enabled} (Must be true for live posts)")
    print(f"  REQUIRE_APPROVAL: {config.require_approval} (Drafts must be explicitly approved)")

    print("\n[AI PROVIDER SETTINGS]")
    print(f"  Active Provider:  {config.ai_provider.upper()} (Options: ollama, groq, gemini)")
    print(f"  Local Ollama:     {config.ollama_base_url} (Model: {config.ollama_model})")
    print(f"  Groq Cloud:       Model: {config.groq_model} | Key: {redact_secret(config.groq_api_key)}")
    print(f"  Gemini API:       Key: {redact_secret(config.gemini_api_key)}")

    print("\n[LINKEDIN CONFIGURATION]")
    print(f"  Client ID:        {redact_secret(config.linkedin_client_id)}")
    print(f"  Client Secret:    {redact_secret(config.linkedin_client_secret)}")
    print(f"  Redirect URI:     {config.linkedin_redirect_uri}")
    print(f"  API Version:      {config.linkedin_api_version}")

    print("\n[AUTHENTICATION STATUS]")
    if token and token.get("access_token"):
        expires_at = token["expires_at"]
        remaining_days = max(0.0, (expires_at - time.time()) / 86400)
        is_valid = remaining_days > 0

        status_str = "VALID" if is_valid else "EXPIRED"
        print(f"  Token Status:     {status_str}")
        print(f"  Member ID (sub):  {token.get('member_id', 'Unknown')}")
        print(f"  Member Name:      {token.get('member_name', 'Unknown')}")
        print(f"  Member Email:     {token.get('member_email', 'Unknown')}")
        print(f"  Scopes Granted:   {token.get('scope', 'Unknown')}")
        print(f"  Expires In:       {remaining_days:.1f} days ({time.ctime(expires_at)})")
    else:
        print("  Token Status:     NO TOKEN STORED")
        print("  Run 'python -m src.cli login' to connect your LinkedIn account.")

    print("\n[DATABASE & CONTENT STATS]")
    posts = db.list_posts(limit=100)
    drafts = sum(1 for p in posts if p["status"] == "DRAFT")
    approved = sum(1 for p in posts if p["status"] == "APPROVED")
    published = sum(1 for p in posts if p["status"] == "PUBLISHED")
    failed = sum(1 for p in posts if p["status"] == "FAILED")
    unposted_topics = len(db.get_top_unposted_topics(limit=50))

    print(f"  Database Path:    {config.database_path}")
    print(f"  Research Topics:  {unposted_topics} fresh, unposted topics queued")
    print(f"  Total Posts:      {len(posts)}")
    print(f"  - Drafts:         {drafts}")
    print(f"  - Approved:       {approved}")
    print(f"  - Published:      {published}")
    print(f"  - Failed:         {failed}")
    print("=" * 65 + "\n")


def cmd_login(args: argparse.Namespace) -> None:
    """Start local callback server and launch browser for LinkedIn OAuth login."""
    db = Database(config.database_path)
    oauth = LinkedInOAuth(config, db)

    try:
        auth_url, state = oauth.generate_authorization_url()
    except Exception as e:
        print(f"\n[ERROR] Unable to generate authorization URL: {e}\n")
        sys.exit(1)

    print("\n" + "=" * 65)
    print("           LINKEDIN OAUTH AUTHORIZATION")
    print("=" * 65)
    print("\n1. Starting local callback server on http://localhost:8000/auth/linkedin/callback")
    print("2. Opening your browser to LinkedIn authorization page...\n")
    print(f"If your browser does not open automatically, visit this URL:\n\n{auth_url}\n")
    print("Waiting for callback from LinkedIn... (Press Ctrl+C to cancel)\n")

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    try:
        result = start_callback_server(oauth_service=oauth, port=8000)
        print("\n" + "=" * 65)
        print("SUCCESS! LINKEDIN ACCOUNT CONNECTED")
        print("=" * 65)
        print(f"  Member:     {result.get('member_name')}")
        print(f"  Member ID:  {result.get('member_id')}")
        print(f"  Scopes:     {result.get('scope')}")
        print(f"  Token TTL:  {result.get('expires_in', 0) // 86400} days")
        print("\nToken is safely stored in the local SQLite database.")
        print("You can verify with: python -m src.cli status\n")
    except Exception as e:
        print(f"\n[ERROR] OAuth flow failed: {e}\n")
        sys.exit(1)


def cmd_auth_url(args: argparse.Namespace) -> None:
    """Print the authorization URL without starting the server."""
    db = Database(config.database_path)
    oauth = LinkedInOAuth(config, db)
    try:
        auth_url, state = oauth.generate_authorization_url()
        print(f"\nAuthorization URL:\n{auth_url}\n")
    except Exception as e:
        print(f"\n[ERROR] {e}\n")
        sys.exit(1)


def cmd_research(args: argparse.Namespace) -> None:
    """Fetch, score, and deduplicate trending technology & AI topics."""
    db = Database(config.database_path)
    researcher = TopicResearcher(db=db)
    topics = researcher.fetch_all_topics(limit_per_feed=args.limit)

    print(f"\nDiscovered {len(topics)} scored tech topics (Ranked by Freshness & Relevance):\n")
    for i, t in enumerate(topics[: args.limit * 3], 1):
        x_badge = " [X Community Trend]" if t.get("is_x_discussion") else ""
        print(f"[{i}] [{t['score']:.1f} pts] {t['title']}{x_badge}")
        print(f"    Category: {t['category']} | Source: {t['source_name']}")
        print(f"    Summary:  {t['summary'][:140]}...")
        print(f"    Link:     {t['source_url']}\n")


def cmd_trends(args: argparse.Namespace) -> None:
    """Discover, cluster, and display top ranked AI & technology trends."""
    db = Database(config.database_path)
    from src.trend_engine import TrendIntelligenceEngine
    engine = TrendIntelligenceEngine(cfg=config, db=db)

    limit = getattr(args, "limit", 10)
    min_score = getattr(args, "min_score", 0.0)
    print("\n" + "=" * 75)
    print("      AI & TECHNOLOGY TREND INTELLIGENCE - TOP RANKED TRENDS")
    print("=" * 75)
    print("Discovering, verifying, and clustering tech developments across verified sources...\n")

    trends = engine.discover_and_rank_trends(limit_per_feed=3, min_score=min_score)
    if not trends:
        print("No trend clusters met the scoring threshold.")
        print("=" * 75 + "\n")
        return

    for i, t in enumerate(trends[:limit], 1):
        fresh = t.get("freshness_window", "breaking").upper()
        momentum = t.get("momentum", "emerging").upper()
        evidence = "PRIMARY EVIDENCE" if t.get("has_primary_evidence") else "SECONDARY COVERAGE"
        print(f"[{i}] {t['title']}")
        print(f"    Score:       {t['score']:.1f}/100  |  Window: {fresh}  |  Momentum: {momentum}")
        print(f"    Category:    {t['category']}  |  {evidence}")
        print(f"    Source:      {t['source_name']} ({t.get('article_count', 1)} related articles clustered)")
        print(f"    Primary URL: {t['source_url']}")
        print(f"    Explanation: {t.get('score_explanation', 'N/A')}")
        if t.get("entities", {}).get("models"):
            print(f"    Models:      {', '.join(t['entities']['models'])}")
        if t.get("entities", {}).get("companies"):
            print(f"    Companies:   {', '.join(t['entities']['companies'])}")
        print("")
    print("=" * 75 + "\n")


def cmd_source_health(args: argparse.Namespace) -> None:
    """Display health metrics and diagnostics for all registered technology sources."""
    db = Database(config.database_path)
    sources = db.list_sources_health()

    print("\n" + "=" * 80)
    print("          REGISTERED TECHNOLOGY SOURCES & HEALTH DIAGNOSTICS")
    print("=" * 80)
    if not sources:
        print("No source health records found. Run 'python -m src.cli trends' or 'research' first.")
        print("=" * 80 + "\n")
        return

    print(f"{'Source Name':<30} | {'Type':<18} | {'Status':<10} | {'OK':<4} | {'Fail':<4} | {'Last Fetch'}")
    print("-" * 80)
    for s in sources:
        last_fetch = time.ctime(s["last_attempt_at"]) if s.get("last_attempt_at") else "Never"
        status = s.get("status", "HEALTHY").upper()
        print(f"{s['source_name'][:29]:<30} | {s.get('source_type', 'N/A')[:17]:<18} | {status:<10} | {s.get('success_count', 0):<4} | {s.get('failure_count', 0):<4} | {last_fetch}")
        if s.get("last_error"):
            print(f"   |-- Last Error: {s['last_error']}")
    print("=" * 80 + "\n")


def cmd_pipeline(args: argparse.Namespace) -> None:
    """Run full automated research-to-draft pipeline: discover top topic and generate draft."""
    db = Database(config.database_path)
    researcher = TopicResearcher(db=db)
    generator = ContentGenerator(config, db=db)

    print("\n[PIPELINE] 1. Discovering, clustering, and ranking latest technology trends...")
    top_topic = researcher.get_top_topic()
    if not top_topic:
        print("[ERROR] No new unposted topics or trends discovered.")
        return

    print(f"\n[PIPELINE] 2. Selected top topic (Score: {top_topic.get('score', 0):.1f} pts):")
    print(f"           '{top_topic['title']}' ({top_topic.get('source_name', 'N/A')})")
    if top_topic.get("score_explanation"):
        print(f"           Explanation: {top_topic['score_explanation']}")

    provider = args.provider or config.ai_provider
    print(f"\n[PIPELINE] 3. Generating post draft via provider '{provider}' (with Ollama fallback)...")

    context = top_topic.get("summary", "")
    if top_topic.get("entities", {}).get("models"):
        context += f" | Key Models: {', '.join(top_topic['entities']['models'])}"

    draft = generator.generate_draft(
        topic=top_topic["title"],
        context=context,
        category=top_topic.get("category", "Technology"),
        source_url=top_topic.get("source_url", ""),
        source_name=top_topic.get("source_name", ""),
        provider=provider,
    )

    print("\n" + "=" * 65)
    print(f"DRAFT #{draft['post_id']} CREATED (Status: {draft['status']})")
    print(f"Provider: {draft['ai_provider']} ({draft['ai_model']}) | Fallback Used: {draft['fallback_used']}")
    print("=" * 65)
    print(f"\n{draft['commentary']}\n")
    print("=" * 65)
    print(f"To approve this draft: python -m src.cli approve {draft['post_id']}")
    print(f"To dry-run publish:    python -m src.cli publish {draft['post_id']}\n")


def cmd_generate(args: argparse.Namespace) -> None:
    """Generate a LinkedIn post draft using Groq, Ollama, or Gemini."""
    db = Database(config.database_path)
    generator = ContentGenerator(config, db=db)

    topic = args.topic
    category = args.category or "Technology"
    source_url = args.source_url or ""
    source_name = args.source_name or ""
    context = args.context or ""

    if not topic:
        researcher = TopicResearcher(db=db)
        top = researcher.get_top_topic()
        if top:
            topic = top["title"]
            context = top["summary"]
            category = top["category"]
            source_url = top["source_url"]
            source_name = top["source_name"]
        else:
            topic = "Frontier AI Reasoning Models & Agentic Workflows"
            context = "How recent advances in reasoning models are changing engineering tools."

    provider = args.provider or config.ai_provider
    print(f"\nGenerating post draft for topic: '{topic}' using provider '{provider}'...")

    try:
        draft = generator.generate_draft(
            topic=topic,
            context=context,
            category=category,
            source_url=source_url,
            source_name=source_name,
            provider=provider,
        )
        print("\n" + "=" * 65)
        print(f"DRAFT #{draft['post_id']} CREATED (Status: {draft['status']})")
        print(f"Provider: {draft['ai_provider']} ({draft['ai_model']}) | Fallback: {draft['fallback_used']}")
        print("=" * 65)
        print(f"\n{draft['commentary']}\n")
        print("=" * 65)
        print(f"To approve this draft:  python -m src.cli approve {draft['post_id']}")
        print(f"To publish (dry-run):   python -m src.cli publish {draft['post_id']}\n")
    except Exception as e:
        print(f"\n[ERROR] Content generation failed: {e}\n")
        sys.exit(1)


def cmd_list(args: argparse.Namespace) -> None:
    """List posts from the database with image status."""
    db = Database(config.database_path)
    posts = db.list_posts(status=args.status, limit=args.limit)

    print(f"\nListing posts (Status filter: {args.status or 'ALL'}):\n")
    if not posts:
        print("No posts found in database.")
        return

    for p in posts:
        prov_info = f" | AI: {p.get('ai_provider', 'N/A')}" if p.get("ai_provider") else ""
        img_badge = f" | IMG: {p.get('image_validation_status') or 'NONE'}"
        print(f"ID #{p['id']} | Status: {p['status']} | Created: {time.ctime(p['created_at'])}{prov_info}{img_badge}")
        print(f"  Topic:    {p['topic'] or 'N/A'} ({p.get('category', 'Technology')})")
        if p.get("image_path"):
            print(f"  Image:    {Path(p['image_path']).name}")
        if p["status"] == "PUBLISHED":
            print(f"  LinkedIn: {p['linkedin_post_id']}")
            print(f"  Date:     {time.ctime(p['published_at'])}")
        elif p["status"] == "FAILED":
            print(f"  Error:    {p['error_message']}")
        preview = p["commentary"].replace("\n", " ")[:120]
        print(f"  Preview:  {preview}...\n")


def cmd_show(args: argparse.Namespace) -> None:
    """Show the full content, image details, and metadata of a specific post."""
    db = Database(config.database_path)
    post = db.get_post(args.post_id)
    if not post:
        print(f"\n[ERROR] Post #{args.post_id} does not exist.\n")
        return

    print("\n" + "=" * 65)
    print(f"POST #{post['id']} DETAILS (Status: {post['status']})")
    print(f"Topic:       {post.get('topic') or 'N/A'}")
    print(f"Category:    {post.get('category') or 'N/A'}")
    print(f"Source:      {post.get('source_name') or 'N/A'} ({post.get('source_url') or 'N/A'})")
    if post.get("ai_provider"):
        print(f"AI Model:    {post.get('ai_provider')} ({post.get('ai_model')})")
    
    print("\n[IMAGE DETAILS]")
    if post.get("image_path"):
        img_path = Path(post["image_path"])
        exists_str = "EXISTS" if img_path.exists() else "MISSING"
        print(f"  File Path:    {img_path.resolve()} ({exists_str})")
        print(f"  Dimensions:   {post.get('image_width', 1200)}x{post.get('image_height', 1200)} PNG")
        print(f"  Content Hash: {post.get('image_hash') or 'N/A'}")
        print(f"  Status:       {post.get('image_validation_status') or 'N/A'}")
        print(f"  Alt Text:     {post.get('image_alt_text') or 'N/A'}")
        if post.get("image_urn"):
            print(f"  LinkedIn URN: {post['image_urn']}")
    else:
        print("  No image attached to this post draft.")

    print("=" * 65)
    print(f"\n{post['commentary']}\n")
    print("=" * 65)
    if post.get("image_path"):
        print(f"To preview image: python -m src.cli preview-image {post['id']}")
    if post["status"] == "DRAFT":
        print(f"To approve post:  python -m src.cli approve {post['id']}")
    elif post["status"] == "APPROVED":
        print(f"To publish post:  python -m src.cli publish {post['id']}")
    print("")


def cmd_preview_image(args: argparse.Namespace) -> None:
    """Preview the locally generated graphic for a post draft in the default image viewer."""
    db = Database(config.database_path)
    post = db.get_post(args.post_id)
    if not post:
        print(f"\n[ERROR] Post #{args.post_id} does not exist in database.\n")
        return

    image_path = post.get("image_path")
    if not image_path or not Path(image_path).exists():
        print(f"\n[ERROR] No image file found for Post #{args.post_id}. (Path: {image_path})\n")
        return

    path = Path(image_path)
    is_valid, reason = ImageValidator.validate(path)

    print("\n" + "=" * 65)
    print(f"       PREVIEW IMAGE FOR POST #{args.post_id}")
    print("=" * 65)
    print(f"  File Path:      {path.resolve()}")
    print(f"  File Size:      {path.stat().st_size / 1024:.1f} KB")
    print(f"  Dimensions:     {post.get('image_width', 1200)}x{post.get('image_height', 1200)} PNG")
    print(f"  Content Hash:   {post.get('image_hash') or 'N/A'}")
    print(f"  Quality Status: {'PASSED' if is_valid else 'FAILED'} ({reason})")
    print(f"  Alt Text:       {post.get('image_alt_text') or 'N/A'}")
    if post.get("image_urn"):
        print(f"  LinkedIn URN:   {post['image_urn']}")
    print("=" * 65 + "\n")

    # Launch in system default image viewer
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))
            print("Opened image in default Windows viewer.")
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])
            print("Opened image in default viewer.")
    except Exception as e:
        print(f"Could not automatically launch image viewer: {e}")
        print(f"You can view the image file directly at:\n{path.resolve()}\n")


def cmd_image_prompt(args: argparse.Namespace) -> None:
    """Generate and display ready-to-use photorealistic announcement poster prompt for Grok on X or Midjourney."""
    db = Database(config.database_path)
    post = db.get_post(args.post_id)
    if not post:
        print(f"\n[ERROR] Post #{args.post_id} not found in database.\n")
        sys.exit(1)

    headline, points = extract_image_elements(
        topic=post.get("topic") or "",
        context="",
        commentary=post.get("commentary") or "",
    )

    prompt = synthesize_realistic_poster_prompt(
        topic=post.get("topic") or "",
        category=post.get("category") or "Technology",
        source_name=post.get("source_name") or "",
        headline=headline,
        points=points,
        for_midjourney_or_grok=True,
    )

    print("\n" + "=" * 70)
    print(f"   REALISTIC TECH ANNOUNCEMENT POSTER PROMPT - POST #{args.post_id}")
    print("=" * 70)
    print(f"Topic:    {post.get('topic')}")
    print(f"Category: {post.get('category')}")
    print(f"Headline: {headline}")
    print("\n[READY-TO-USE PROMPT FOR GROK (ON X), MIDJOURNEY, OR DALL-E 3]")
    print("-" * 70)
    print(prompt)
    print("-" * 70)
    print("\nHOW TO USE THIS:")
    print("1. Copy the prompt above and paste it directly into Grok on X (Twitter) or Midjourney.")
    print("2. Once generated, attach the image directly to this LinkedIn post with:")
    print(f"   python -m src.cli attach-image {args.post_id} <path_or_url_to_image>\n")


def cmd_attach_image(args: argparse.Namespace) -> None:
    """Attach an externally generated realistic image (from X/Twitter, Midjourney, etc.) to a draft post."""
    db = Database(config.database_path)
    post = db.get_post(args.post_id)
    if not post:
        print(f"\n[ERROR] Post #{args.post_id} not found in database.\n")
        sys.exit(1)

    image_gen = ImageGenerator(config)
    headline, _ = extract_image_elements(
        topic=post.get("topic") or "",
        context="",
        commentary=post.get("commentary") or "",
    )

    try:
        print(f"\nProcessing and attaching realistic image to Post #{args.post_id}...")
        meta = image_gen.attach_custom_image(
            post_id=args.post_id,
            source_path_or_url=args.image_source,
            headline=headline,
            category=post.get("category") or "Technology",
        )
        db.attach_image_to_post(
            post_id=args.post_id,
            image_path=meta["image_path"],
            image_hash=meta["image_hash"],
            image_alt_text=meta["image_alt_text"],
            image_width=meta["image_width"],
            image_height=meta["image_height"],
            validation_status=meta["validation_status"],
        )
        print("\n" + "=" * 70)
        print(f"SUCCESS: REALISTIC IMAGE ATTACHED TO POST #{args.post_id}")
        print("=" * 70)
        print(f"  Source Input:    {args.image_source}")
        print(f"  Standardized To: {meta['image_path']}")
        print(f"  Dimensions:      {meta['image_width']} x {meta['image_height']} (PNG)")
        print(f"  SHA-256 Hash:    {meta['image_hash']}")
        print(f"  Alt Text:        {meta['image_alt_text']}")
        print(f"  Validation:      {meta['validation_status']}")
        print("\nDraft is now updated with your custom realistic visual.")
        print(f"Preview with: python -m src.cli preview-image {args.post_id}")
        print(f"Approve with: python -m src.cli approve {args.post_id}\n")
    except Exception as e:
        print(f"\n[ERROR] Failed to attach image: {e}\n")
        sys.exit(1)


def cmd_approve(args: argparse.Namespace) -> None:
    """Approve a post draft for publishing."""
    db = Database(config.database_path)
    success = db.approve_post(args.post_id)
    if success:
        print(f"\n[SUCCESS] Post #{args.post_id} approved for publication.\n")
    else:
        post = db.get_post(args.post_id)
        if not post:
            print(f"\n[ERROR] Post #{args.post_id} does not exist.\n")
        else:
            print(f"\n[INFO] Post #{args.post_id} is currently in status '{post['status']}'. Only 'DRAFT' can be approved.\n")


def cmd_publish(args: argparse.Namespace) -> None:
    """Publish an approved post with its verified image."""
    publisher = LinkedInPublisher(config)
    try:
        result = publisher.publish_post(args.post_id)
        if result.get("dry_run"):
            print("\n" + "=" * 65)
            print("                [DRY-RUN COMPLETE]")
            print("=" * 65)
            print(f"Post #{result['post_id']} validated successfully with image.")
            print(f"Target Author: {result['author']}")
            print(f"Image Path:    {result.get('image_path')}")
            print(f"Image URN:     {result.get('image_urn')}")
            print(f"\nPreview Commentary:\n{result['commentary']}\n")
            print("Safety Note: No real API request was sent because DRY_RUN=true.")
            print("To enable live publishing:")
            print("1. Set DRY_RUN=false in .env")
            print("2. Set PUBLISH_ENABLED=true in .env")
            print(f"3. Run: python -m src.cli publish {args.post_id}\n")
        else:
            print("\n" + "=" * 65)
            print("          [LIVE POST PUBLISHED TO LINKEDIN]")
            print("=" * 65)
            print(f"Post #{result['post_id']} is live with image!")
            print(f"LinkedIn Post ID: {result['linkedin_post_id']}")
            print(f"LinkedIn Image:   {result.get('image_urn')}")
            print(f"Published At:     {time.ctime(result['published_at'])}\n")
    except PublisherError as e:
        print(f"\n[PUBLISH BLOCKED / ERROR] {e}\n")
        sys.exit(1)


def cmd_daily_run(args: argparse.Namespace) -> None:
    """Execute complete automated daily workflow: Discover 2-3 distinct posts across fields -> Generate -> Realistic Image -> Publish."""
    db = Database(config.database_path)
    researcher = TopicResearcher(db=db)
    generator = ContentGenerator(config, db=db)
    publisher = LinkedInPublisher(config, db=db)

    print("\n" + "=" * 70)
    print("   DAILY AUTOMATION RUN - MULTI-FIELD LINKEDIN CONTENT PIPELINE")
    print("=" * 70)
    print(f"Time:     {time.ctime()} (Asia/Kolkata timezone)")
    print(f"Mode:     {'DRY RUN' if config.dry_run else 'LIVE'} | Publish Enabled: {config.publish_enabled} | Require Approval: {config.require_approval}")
    print("Strategy: 3 Targeted Fields -> [1] AI News  [2] Tech News  [3] Industry Trends")
    print("=" * 70)

    # Step 1: Discover topics across Twitter/X and tech feeds with Groq intelligence
    print("\n[STEP 1/4] Discovering trending discussions on Twitter/X and verified feeds, curated with Groq...")
    topics = researcher.curate_trending_news_with_groq()

    target_count = getattr(args, "count", 3) or 3
    selected_topics = topics[:target_count]

    results_summary = []

    used_backgrounds: list[str] = []
    template_sequence = [
        "photorealistic_poster",
        "architecture_blueprint",
        "editorial_spotlight",
        "benchmark_comparison",
    ]

    for idx, topic_info in enumerate(selected_topics, 1):
        field_label = topic_info.get("target_field") or f"Field #{idx}"
        print("\n" + "-" * 70)
        print(f"[{idx}/{len(selected_topics)}] PROCESSING POST: {field_label.upper()}")
        print("-" * 70)
        print(f"Topic:    {topic_info['title']}")
        print(f"Category: {topic_info.get('category')} | Source: {topic_info.get('source_name', 'N/A')}")
        if topic_info.get("curation_rationale"):
            clean_rationale = str(topic_info['curation_rationale']).encode("ascii", "replace").decode("ascii")
            print(f"Curated:  {clean_rationale}")
        elif topic_info.get("score"):
            print(f"Score:    {topic_info['score']} pts")

        # Step 2: Generate Post Draft
        # Distinct visual types for each post: Post 1 & 2 -> Dynamic AI Generated Images with Unique Seed, Post 3 -> Dedicated Scripted News
        should_generate_image = (idx <= 2)
        assigned_template = template_sequence[(idx - 1) % len(template_sequence)]

        # Pause briefly between multi-image generations to respect free AI rate limits
        if idx > 1 and should_generate_image:
            print("\n[Rate-Limit Cooldown] Waiting 25s for next AI image generation slot...")
            time.sleep(25)

        print(f"\n-> Generating 80-150 word post draft via AI ({args.provider or config.ai_provider})...")
        if should_generate_image:
            print(f"-> Generating distinct AI photorealistic visual format #{idx} (seed randomized)...")
        else:
            print(f"-> Formatting Post #{idx} as a dedicated scripted text-only news story (no image)...")

        try:
            draft = generator.generate_draft(
                topic=topic_info["title"],
                context=topic_info.get("summary", ""),
                category=topic_info.get("category", "Technology"),
                source_url=topic_info.get("source_url", ""),
                source_name=topic_info.get("source_name", ""),
                provider=args.provider or config.ai_provider,
                topic_id=topic_info.get("id"),
                generate_image=should_generate_image,
                image_template=assigned_template,
                post_index=idx,
                exclude_backgrounds=used_backgrounds,
            )
        except Exception as e:
            logger.error(f"Post generation failed for '{topic_info['title']}': {e}")
            print(f"[ERROR] Post generation failed: {e}")
            continue

        post_id = draft["post_id"]
        print(f"Draft #{post_id} created ({draft['ai_provider']} / {draft['ai_model']})")

        # Track background used so subsequent posts pick a different background
        bg_used = draft.get("image", {}).get("background_used")
        tmpl_used = draft.get("image", {}).get("template_used")
        if bg_used:
            used_backgrounds.append(bg_used)
            print(f"Visual Template: {tmpl_used} | Background: {bg_used}")

        # Step 3: Verify realistic image (if generated)
        post = db.get_post(post_id)
        image_path = post.get("image_path")

        if should_generate_image:
            if not image_path or not Path(image_path).exists():
                print(f"[ERROR] Image missing for post #{post_id}. Skipping publish.")
                continue

            is_valid, reason = ImageValidator.validate(image_path)
            print(f"Image validated: {Path(image_path).name} (Status: {'VALID' if is_valid else 'FAILED'} - {reason})")
            if not is_valid:
                print(f"[ERROR] Image failed quality checks: {reason}. Draft preserved for review.")
                continue
        else:
            print(f"Scripted news post verified: Text-only story formatted for direct LinkedIn reading.")

        # Step 4: Publishing logic
        post_status = "DRAFT"
        pub_info = {}

        if config.require_approval:
            post_status = "SAVED DRAFT (APPROVAL REQUIRED)"
            print(f"Draft #{post_id} created and saved. (Review mode active)")
            if image_path:
                print(f"  Preview image: python -m src.cli preview-image {post_id}")
            print(f"  Approve post:  python -m src.cli approve {post_id}")
        elif config.dry_run:
            post_status = "DRY-RUN SIMULATED"
            db.approve_post(post_id)
            pub_info = publisher.publish_post(post_id)
            print(f"Draft #{post_id} simulated for publication ({'with realistic image' if should_generate_image else 'scripted text-only'}).")
        elif config.publish_enabled:
            print(f"Publishing post #{post_id} ({'with photorealistic image' if should_generate_image else 'as scripted text-only post'}) live to LinkedIn...")
            db.approve_post(post_id)
            pub_info = publisher.publish_post(post_id)
            post_status = "PUBLISHED LIVE"
            print(f"SUCCESS: Post #{post_id} is LIVE on LinkedIn!")
            print(f"  Post ID:   {pub_info.get('linkedin_post_id')}")
            if pub_info.get("image_urn"):
                print(f"  Image URN: {pub_info.get('image_urn')}")

            # Polite spacing between LinkedIn API publish calls
            if idx < len(selected_topics):
                print("Waiting 15 seconds before posting next field to respect rate limits...")
                time.sleep(15)

        results_summary.append({
            "index": idx,
            "field": field_label,
            "post_id": post_id,
            "title": topic_info["title"],
            "image": Path(image_path).name if image_path else "None (Scripted Text-Only)",
            "status": post_status,
            "linkedin_id": pub_info.get("linkedin_post_id", "N/A"),
        })

    # Summary Table
    print("\n" + "=" * 70)
    print("                 DAILY AUTOMATION SUMMARY")
    print("=" * 70)
    for r in results_summary:
        print(f"[{r['index']}] {r['field']}: Post #{r['post_id']} - {r['status']}")
        print(f"    Topic:    {r['title'][:55]}...")
        print(f"    Image:    {r['image']}")
        if r.get("linkedin_id") and r["linkedin_id"] != "N/A":
            print(f"    LinkedIn: {r['linkedin_id']}")
    print("=" * 70 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LinkedIn AI Content Automation CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # status
    subparsers.add_parser("status", help="Show system, AI provider, token, and database status")

    # login
    subparsers.add_parser("login", help="Start OAuth login flow via browser")

    # auth-url
    subparsers.add_parser("auth-url", help="Display OAuth authorization URL")

    # research
    p_research = subparsers.add_parser("research", help="Discover, score, and deduplicate tech topics")
    p_research.add_argument("--limit", type=int, default=3, help="Max topics per feed")

    # pipeline
    p_pipe = subparsers.add_parser("pipeline", help="Run automated research-to-draft workflow")
    p_pipe.add_argument("--provider", choices=["groq", "ollama", "gemini"], help="Override AI provider")

    # generate
    p_gen = subparsers.add_parser("generate", help="Generate a new post draft with image")
    p_gen.add_argument("--topic", type=str, help="Post topic/headline")
    p_gen.add_argument("--category", type=str, help="Topic category")
    p_gen.add_argument("--context", type=str, help="Additional context or article text")
    p_gen.add_argument("--source-url", type=str, help="Reference URL")
    p_gen.add_argument("--source-name", type=str, help="Source publication name")
    p_gen.add_argument("--provider", choices=["groq", "ollama", "gemini"], help="Override AI provider")

    # list
    p_list = subparsers.add_parser("list", help="List posts")
    p_list.add_argument("--status", choices=["DRAFT", "APPROVED", "PUBLISHED", "FAILED"], help="Filter by status")
    p_list.add_argument("--limit", type=int, default=20, help="Max posts to list")

    # show
    p_show = subparsers.add_parser("show", help="View full content and image info of a specific post")
    p_show.add_argument("post_id", type=int, help="ID of the post to view")

    # preview-image
    p_prev = subparsers.add_parser("preview-image", help="Preview locally generated graphic in default viewer")
    p_prev.add_argument("post_id", type=int, help="ID of the post whose image to preview")

    # image-prompt
    p_prompt = subparsers.add_parser("image-prompt", help="Display photorealistic announcement poster prompt for Grok on X or Midjourney")
    p_prompt.add_argument("post_id", type=int, help="ID of the post draft")

    # attach-image
    p_attach = subparsers.add_parser("attach-image", help="Attach an external realistic image (from X/Twitter, Midjourney, etc.) to a draft post")
    p_attach.add_argument("post_id", type=int, help="ID of the post draft")
    p_attach.add_argument("image_source", type=str, help="Local file path or image URL")

    # approve
    p_app = subparsers.add_parser("approve", help="Approve a draft post")
    p_app.add_argument("post_id", type=int, help="ID of the post to approve")

    # publish
    p_pub = subparsers.add_parser("publish", help="Publish a post with image (subject to safety settings)")
    p_pub.add_argument("post_id", type=int, help="ID of the post to publish")

    # trends
    p_trends = subparsers.add_parser("trends", help="Discover, cluster, and rank tech trends")
    p_trends.add_argument("--limit", type=int, default=10, help="Max trend clusters to display")
    p_trends.add_argument("--min-score", type=float, default=0.0, help="Minimum trend score filter")

    # source-health
    subparsers.add_parser("source-health", help="Display health and reliability of technology sources")

    # daily-run
    p_daily = subparsers.add_parser("daily-run", help="Run full daily automated pipeline across AI, Tech, and Industry fields")
    p_daily.add_argument("--provider", choices=["groq", "ollama", "gemini"], help="Override AI provider")
    p_daily.add_argument("--count", type=int, default=3, help="Number of distinct field posts to publish (default: 3)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "status": cmd_status,
        "login": cmd_login,
        "auth-url": cmd_auth_url,
        "research": cmd_research,
        "trends": cmd_trends,
        "source-health": cmd_source_health,
        "pipeline": cmd_pipeline,
        "generate": cmd_generate,
        "list": cmd_list,
        "show": cmd_show,
        "preview-image": cmd_preview_image,
        "image-prompt": cmd_image_prompt,
        "attach-image": cmd_attach_image,
        "approve": cmd_approve,
        "publish": cmd_publish,
        "daily-run": cmd_daily_run,
    }

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
