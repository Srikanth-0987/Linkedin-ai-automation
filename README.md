# LinkedIn AI Content Automation: AI & Technology Trend Intelligence Engine

Autonomous, AI-driven daily content pipeline and intelligence engine for LinkedIn. Continuously discovers, verifies, normalizes, clusters, and ranks the latest important trends in AI and technology (Frontier AI models, AI labs, LLMs, developer tools, infrastructure, and software engineering), generates concise mobile-optimized posts (80–150 words), creates professional 1200×1200px PNG graphics locally with Pillow, and publishes text and images together on LinkedIn via official REST APIs.

**Total Operating Cost: ₹0** (Uses Groq free tier or 100% offline local Ollama with `qwen3.5:4b`; local Pillow graphics engine; zero paid subscriptions, paid APIs, or external image generation services).

---

## Architecture Overview

```
                                      +------------------------------------+
                                      |    Modular Source Registry (16+)   |
                                      | (OpenAI, DeepMind, Anthropic,      |
                                      |  Mistral, HuggingFace, GitHub,     |
                                      |  arXiv, NVIDIA, Hacker News, TC)   |
                                      +-----------------+------------------+
                                                        |
                                                        v
+-------------------------------+             +---------+------------------+
| AI-Assisted Research Engine   |<----------->| Trend Intelligence Engine  |
| - Local Ollama (qwen3.5:4b)   |             | - URL Normalizer (no UTMs) |
| - Groq Cloud (Free Tier)      |             | - Entity Extractor         |
| - Fail-Safe Heuristic Rules   |             | - Event Clusterer          |
+-------------------------------+             | - Freshness Classifier     |
                                              | - Transparent 0-100 Scorer |
                                              | - Source Health Monitor    |
                                              +---------+------------------+
                                                        |
                                                        v
                                              +---------+------------------+
                                              |    Content Generator       |
                                              | (80-150 words, Mobile Hook)|
                                              +---------+------------------+
                                                        |
                                                        v
+-------------------------------+             +---------+------------------+
| Pillow Local Graphics Engine  |<----------->| Image Quality Validation   |
| (1200x1200px, 4 Layout Types) |             | (Bounds, Non-blank, Text)  |
+-------------------------------+             +---------+------------------+
                                                        |
                                                        v
                                              +---------+------------------+
                                              |  SQLite Local Database     |
                                              |  - source_health           |
                                              |  - trend_clusters          |
                                              |  - research_articles       |
                                              |  - trend_scores            |
                                              |  - posts & images          |
                                              +---------+------------------+
                                                        |
                                                        v (Manual Approval)
+-------------------------------+             +---------+------------------+
| Official LinkedIn REST APIs   |<------------| LinkedIn Publisher Gate    |
| - POST /rest/images?action=.. |             | (DRY_RUN / Rate Limits /   |
| - PUT binary upload           |             |  Duplicate Prevention)     |
| - POST /rest/posts (media)    |             +----------------------------+
+-------------------------------+
```

---

## Features

1. **Continuous Trend Discovery & Modular Source Registry**:
   - Ingests feeds from primary AI labs (OpenAI, Google DeepMind, Anthropic, Mistral, Hugging Face), company engineering newsrooms (GitHub, Python, NVIDIA), research archives (arXiv cs.AI & cs.LG, MIT Tech Review), and tech communities (Hacker News, TechCrunch AI, VentureBeat AI, Ars Technica).
   - Extensible through external JSON configurations (`SOURCES_CONFIG_FILE`).
   - Prioritizes primary sources for claims and benchmarks; uses secondary sources for context.
   - Comprehensive source health tracking: records status (`HEALTHY`, `DEGRADED`, `FAILING`), attempt timestamps, and exact failure diagnostics.
2. **Canonical URL Normalization & Event Clustering**:
   - `URLNormalizer` strips tracking tokens (`utm_*`, `ref`, `fbclid`, `gclid`), strips redundant ports/fragments, and standardizes query order.
   - `EventClusterer` groups articles reporting on the same technological development via token Jaccard similarity and entity intersection.
   - Prevents duplicate reporting from being counted as multiple independent trends.
3. **Time-Aware Freshness Windows & Dynamic Momentum**:
   - Standardizes RFC 822 and ISO 8601 dates with timezone awareness. Capped runtime protection prevents future/corrupted timestamps.
   - Windows: **Breaking** (<24 hours), **Current Developments** (24–72 hours), **Recent Releases** (3–7 days), and **Evergreen** (>7 days).
   - Momentum classification: `rising` (multiple independent sources), `sustained`, `emerging`, and `fading`.
4. **Transparent 0–100 Trend Scoring**:
   - Configurable component weights:
     - Recency: **25 points**
     - Source Credibility: **20 points** (Primary Labs = 1.0 multiplier, Secondary Press = 0.7)
     - Significance & Impact: **20 points** (Model releases, major lab breakthroughs)
     - Coverage & Discussion: **15 points** (Clustered articles & community debates)
     - LinkedIn Audience Relevance: **15 points** (AI, Python, Agents, Systems, Reasoning)
     - Novelty: **5 points**
   - Configurable penalty enforcement:
     - Duplicate reporting inside cluster: **-15 points**
     - Stale content (>7 days): **-20 points**
     - Recently published by our account (14-day lookback): **-30 points**
     - Unverified URL / unsupported claims: **-15 points**
   - Stores transparent component score breakdowns and explanations for every cluster.
5. **AI-Assisted Research with Graceful Local Fallback**:
   - Integrates local Ollama (`qwen3.5:4b`) or optional cloud providers (Groq, Gemini) to extract key verified facts vs speculations.
   - 100% fail-safe: automatically falls back to deterministic entity extraction and rule-based heuristics if AI is offline, rate-limited, or unavailable. Zero paid API dependency.
6. **Short, Engaging Mobile Posts (80–150 words)**:
   - Attention-grabbing opening hook.
   - Clear technical explanation and engineering impact.
   - Concrete takeaway and natural discussion question.
   - 3 to 5 relevant technical hashtags.
7. **Photorealistic 3D Tech Announcement Images & Local Fallback Engine**:
   - **Automated AI Generation (₹0 Cost)**: Produces photorealistic 1200×1200px 3D announcement posters matching the exact tech domain of the post (e.g., cybernetic humanoid robots for Claude/DeepSeek, dual celestial landscape cards for OpenAI, 3D companion robots & IDEs for Copilot/coding agents, glowing silicon microchips for NVIDIA/hardware, diplomatic handshakes & holographic globes for tech policy).
   - **Zero-Cost Multi-Tier Architecture**: First attempts zero-cost online AI generation; if offline or timed out, gracefully falls back to the local Pillow graphic engine (`editorial_highlight`, `architecture_diagram`, `concept_card`). Never fails or halts the publishing pipeline.
   - **X (Twitter) Creator Cross-Posting Tools**:
     - `python -m src.cli image-prompt <post_id>`: Synthesizes and prints the exact ready-to-copy master prompt for Grok on X, Midjourney, or DALL-E 3.
     - `python -m src.cli attach-image <post_id> <path_or_url>`: Seamlessly attaches any externally generated realistic image, auto-standardizing to 1200×1200px PNG with SHA-256 hash verification.
   - **Automated Quality Validation**: Verifies image dimensions (1200×1200px), PNG encoding, contrast variance (stddev > 0), margin bounds, and checks against forbidden placeholder tokens.
8. **Safe Publishing Safeguards**:
   - Defaults: `DRY_RUN=true`, `PUBLISH_ENABLED=false`, `REQUIRE_APPROVAL=true`.
   - Never publishes unapproved drafts or posts with failed/missing graphics.

---

## Prerequisites (Windows)

- Windows 10 or 11 (64-bit)
- Python 3.10+ (Tested on Python 3.14)
- Windows PowerShell 5.1 or 7+
- Free AI Providers:
  - **Local Ollama** (100% free offline with `qwen3.5:4b` or `llama3`)
  - **Groq Cloud API Key** (Free tier from [console.groq.com](https://console.groq.com))
  - **Google Gemini API Key** (Optional free tier)
- LinkedIn Developer Application:
  - Products: **Share on LinkedIn** (`w_member_social`), **Sign In with LinkedIn using OpenID Connect** (`openid`, `profile`, `email`).
  - Redirect URL: `http://localhost:8000/auth/linkedin/callback`

---

## 1. Installation Instructions

Open PowerShell in the project directory:

```powershell
# 1. Clone or navigate to the project directory
cd "C:\Users\ramte\OneDrive\Documents\linkedin automation"

# 2. Create virtual environment (if not already created)
python -m venv .venv

# 3. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 4. Install all free dependencies
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## 2. Configuration (`.env`)

Configure your `.env` file (which is git-ignored and never committed to source control):

```powershell
notepad .env
```

Ensure the safe defaults are preserved:

```ini
# LinkedIn Developer App Credentials
LINKEDIN_CLIENT_ID=your_client_id_here
LINKEDIN_CLIENT_SECRET=your_client_secret_here
LINKEDIN_REDIRECT_URI=http://localhost:8000/auth/linkedin/callback
LINKEDIN_ACCESS_TOKEN=
LINKEDIN_MEMBER_ID=
LINKEDIN_API_VERSION=202601

# AI Provider Configuration (Default: ollama, Options: ollama, groq, gemini)
AI_PROVIDER=ollama

# Local Ollama Configuration (₹0 Budget, 100% Free Offline)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3.5:4b

# Groq Cloud Configuration (Free Tier, Fast LPU Inference)
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=qwen/qwen3.8-27b

# Google Gemini API (Optional Fallback)
GEMINI_API_KEY=your_gemini_api_key_here

# Mandatory Safety Settings (Defaults)
DRY_RUN=true
PUBLISH_ENABLED=false
REQUIRE_APPROVAL=true

# Database
DATABASE_PATH=linkedin_automation.db
```

---

## 3. LinkedIn OAuth Authorization

Authorize your LinkedIn personal account using official OAuth 2.0 with PKCE and state verification:

```powershell
.\.venv\Scripts\python.exe -m src.cli login
```

1. Starts a temporary callback server on `http://localhost:8000/auth/linkedin/callback`.
2. Automatically launches your default browser to LinkedIn's consent page.
3. Upon approval, exchanges the authorization code for a 60-day access token and fetches your member ID.
4. Securely stores the token and member URN in the local SQLite database.

Verify connection status anytime:

```powershell
.\.venv\Scripts\python.exe -m src.cli status
```

---

## 4. AI & Technology Trend Intelligence Commands

### Discover and Rank Top Tech Trends
Continuously discover, normalize, verify, and cluster stories across all registered technology sources:

```powershell
# Display top 10 ranked trends with transparent score explanations:
.\.venv\Scripts\python.exe -m src.cli trends

# Filter by minimum trend score:
.\.venv\Scripts\python.exe -m src.cli trends --limit 5 --min-score 60.0
```

Each ranked trend shows:
- **Canonical Cluster Title & Category**
- **Transparent Score (0–100)**: Recency, Credibility, Significance, Coverage, Relevance, Novelty, and Penalties.
- **Freshness Window**: `BREAKING` (<24h), `CURRENT_DEVELOPMENT` (24–72h), `RECENT_RELEASE` (3–7d), or `EVERGREEN` (>7d).
- **Momentum**: `RISING` (cross-verified across multiple sources), `SUSTAINED`, or `EMERGING`.
- **Evidence Level**: `PRIMARY EVIDENCE` (direct AI lab / company announcement) vs `SECONDARY COVERAGE`.
- **Primary Source URL & Clustered Article Count**.

### Inspect Source Health and Diagnostics
Check the health, success rates, failure counts, and last error logs for all registered technology sources:

```powershell
.\.venv\Scripts\python.exe -m src.cli source-health
```

Displays:
- **Source Name & Source Type** (`primary_lab`, `primary_company`, `research_archive`, `community_discussion`, `secondary_press`)
- **Health Status**: `HEALTHY`, `DEGRADED`, or `FAILING`
- **Success & Failure Counts**
- **Last Attempt Timestamp & Exact Error Messages** (e.g. `HTTP 404`, `HTTP 429`)

### Run Automated Trend-to-Draft Pipeline
Executes discovery, picks the highest-ranked unposted trend, prints its score rationale, and automatically generates a complete draft with 1200×1200 graphic:

```powershell
.\.venv\Scripts\python.exe -m src.cli pipeline --provider groq
```

---

## 5. Generating & Previewing Posts with Images

### Generate a Daily Post Draft with Image
```powershell
# Auto-generate draft on top topic with Groq (with local Ollama fallback):
.\.venv\Scripts\python.exe -m src.cli generate --provider groq

# Or specify a custom topic:
.\.venv\Scripts\python.exe -m src.cli generate --topic "Vector Search with HNSW Indexing" --category "Data Science" --provider groq
```

### Preview the Generated 1200×1200 Graphic
To view the generated infographic directly in Windows Photos or default image viewer:

```powershell
# Preview image for post draft #3:
.\.venv\Scripts\python.exe -m src.cli preview-image 3
```

This validates the image dimensions, file size, content hash, and quality, and launches the Windows image viewer.

### List and Inspect Drafts
```powershell
# List all drafts with image validation status:
.\.venv\Scripts\python.exe -m src.cli list

# View full details (commentary, image path, alt text, hash):
.\.venv\Scripts\python.exe -m src.cli show 3
```

---

## 6. Safe Dry-Run Workflow

Before any live publishing, test in dry-run mode:

```powershell
# 1. Approve post draft #3:
.\.venv\Scripts\python.exe -m src.cli approve 3

# 2. Execute dry-run publish:
.\.venv\Scripts\python.exe -m src.cli publish 3
```

In dry-run mode (`DRY_RUN=true`):
- Verifies post exists and is approved.
- Validates the local 1200×1200 PNG graphic (dimensions, non-blank check, no placeholders).
- Simulates the LinkedIn Images API initialization and binary upload.
- Constructs the full LinkedIn REST Posts API payload with `content.media` (title, image URN, altText).
- **Makes zero outbound network calls to LinkedIn**.

---

## 7. How LinkedIn Image Uploads Work

When live publishing is executed:

1. **Upload Initialization**:
   Sends `POST https://api.linkedin.com/rest/images?action=initializeUpload` with payload:
   ```json
   {
     "initializeUploadRequest": {
       "owner": "urn:li:person:<member_id>"
     }
   }
   ```
   Receives `uploadUrl` and `image` URN (e.g. `urn:li:image:D4E10AQ...`).

2. **Binary Upload**:
   Streams the local PNG bytes via `PUT <uploadUrl>` with header `Content-Type: image/png`.

3. **Post Creation with Media**:
   Sends `POST https://api.linkedin.com/rest/posts` (Version `202601`):
   ```json
   {
     "author": "urn:li:person:<member_id>",
     "commentary": "<concise 80-150 word post>",
     "visibility": "PUBLIC",
     "distribution": {
       "feedDistribution": "MAIN_FEED",
       "targetEntities": [],
       "thirdPartyDistributionChannels": []
     },
     "lifecycleState": "PUBLISHED",
     "isReshareDisabledByAuthor": false,
     "content": {
       "media": {
         "title": "<image headline>",
         "id": "urn:li:image:<image_id>",
         "altText": "<accessible alt text>"
       }
     }
   }
   ```
4. Stores the returned LinkedIn post URN and publication timestamp in SQLite.

---

## 8. Autonomous Daily Multi-Field Publishing (6:00 PM IST)

The system is configured to autonomously publish **3 distinct posts per day** at **6:00 PM IST (18:00)** without any manual intervention or approval clicks:

### The 3 Core Daily Formats:
1. **Post 1: AI News & Frontier Research (With Photorealistic 3D Visual)**:
   - Topic: LLMs, reasoning breakthroughs, frontier lab announcements (Claude, DeepSeek, OpenAI).
   - Graphic: Matching 1200×1200px photorealistic 3D cybernetic robot announcement poster with glassmorphic feature cards and accuracy metrics.
2. **Post 2: General Tech News (With Photorealistic 3D Visual)**:
   - Topic: Developer tooling, runtime internals, Python (CPython GIL / JIT), systems architecture.
   - Graphic: Matching 1200×1200px photorealistic 3D developer workstation with IDE, desktop companion robot, and speedup callouts.
3. **Post 3: Industry & Tech Trends (Scripted Text-Only News Post)**:
   - Topic: Startups, venture capital, AI policy/regulation, semiconductor geopolitics (NVIDIA/TSMC).
   - Graphic: **None (Scripted Text-Only)**. Clean, structured mobile-optimized commentary crafted for direct reading on LinkedIn.

### Execution Command:
```powershell
# Run the autonomous 3-post multi-field pipeline:
.\.venv\Scripts\python.exe -m src.cli daily-run --count 3
```

### Autonomous Configuration (`.env`):
```ini
DRY_RUN=false
PUBLISH_ENABLED=true
REQUIRE_APPROVAL=false
DAILY_POST_COUNT=3
```

---

## 9. Windows Task Scheduler Setup (Daily at 6:00 PM)

The system is scheduled to fire automatically every day at **6:00 PM IST (18:00)**:

### Option A: One-Click Registration via PowerShell (Configured & Ready)
Open PowerShell as Administrator:

```powershell
# Register the 6:00 PM task with Wake-to-Run and Missed-Task Catchup:
powershell -ExecutionPolicy Bypass -File .\scripts\register_task.ps1 -Time "18:00"
```

The script configures:
- **Trigger**: Daily at `18:00` (6:00 PM IST).
- **WakeToRun**: `True` (wakes computer from modern sleep states to execute).
- **StartWhenAvailable**: `True` (if laptop was powered off or asleep at 6:00 PM, catches up immediately upon waking).
- **Batteries**: Enabled on battery power (`AllowStartIfOnBatteries`, `DontStopIfGoingOnBatteries`).

### Option B: Check Scheduled Task Status
```powershell
Get-ScheduledTask -TaskName "LinkedInAIContentAutomation" | Get-ScheduledTaskInfo
```

---

## 10. Running Tests

Run the full automated test suite (70 unit and integration tests with 100% pass rate):

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

Tests cover:
- **Trend Intelligence Engine**:
  - Source ingestion, RFC 822 & ISO 8601 normalization
  - Canonical URL normalization and tracking parameter stripping
  - Near-duplicate token Jaccard similarity & event clustering
  - Missing, invalid, and future-capped timestamp handling
  - Transparent 0–100 trend score calculations & configurable weights
  - Stale-story penalties (>7d) & recent published topic penalties (14d lookback)
  - Primary-source credibility weighting & unsupported claims penalty
  - SQLite persistence and repeated-run idempotency
  - AI-assisted research provider fallback (Ollama offline -> deterministic rules)
  - Source outages (HTTP 500, 429) & health metric logging
- **Post & Image Generation**:
  - 80–150 word post constraint & structure validation
  - Local Pillow image generation across all visual layouts
  - Image quality validation (dimensions, non-blank, text clipping, placeholders)
- **LinkedIn Publishing & Safety**:
  - Official LinkedIn Images & Posts REST APIs (202601)
  - Safety gates (`DRY_RUN`, `PUBLISH_ENABLED`, `REQUIRE_APPROVAL`)
  - Duplicate content & timeout protections

---

## 11. Common Errors & Troubleshooting

| Error | Root Cause | Solution |
| :--- | :--- | :--- |
| `Post cannot be published: Missing generated image` | Text-only publishing blocked by Feature 4 safeguard | Run `python -m src.cli generate` to create post with matching image before publishing. |
| `HTTP 426 Upgrade Required` | Outdated LinkedIn API version (e.g. `202401`) | Verify `LINKEDIN_API_VERSION=202601` in `.env`. |
| `HTTP 401 Unauthorized` | LinkedIn access token expired or missing | Run `python -m src.cli login` to re-authenticate. |
| `HTTP 403 Forbidden` | Missing `w_member_social` permission | Ensure **Share on LinkedIn** product is added in LinkedIn Developer Console. |
| `Could not connect to Ollama at http://localhost:11434` | Ollama service is not running | Run `ollama run qwen3.5:4b` in terminal, or configure `AI_PROVIDER=groq`. |
| `Image validation failed: image appears blank` | Generated image has low pixel variance | The system automatically regenerates; ensure background gradient renders properly. |
| `Duplicate post content detected` | Post content hash matches existing post in SQLite | Choose a different topic or adjust prompt; system prevents duplicate posts. |
