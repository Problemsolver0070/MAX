# Research: OpenClaw AI Agent Platform

**Date:** 2026-04-04

## What is OpenClaw?

OpenClaw (formerly Clawdbot/Moltbot) is a free, open-source autonomous AI agent created by Peter Steinberger (Austria). Published November 2025, it became the fastest-growing open-source project on GitHub (310k+ stars, 58k+ forks, 1200+ contributors). Steinberger joined OpenAI in Feb 2026; project moved to an open-source foundation.

## Core Architecture

- **Gateway**: Single WebSocket server (port 18789) — central control plane for all operations
- **Agent Runtime (Pi)**: RPC mode with tool streaming and block streaming
- **Session Model**: `main` for direct chats, group isolation, activation modes, queue modes
- **Monorepo**: pnpm workspaces — `apps/`, `packages/`, `extensions/`, `skills/`, `ui/`, `src/`
- **Tech Stack**: Node.js 22.16+/24, TypeScript, Vitest, oxlint
- **License**: MIT
- **Codebase**: ~430,000 lines, ~400MB runtime

## Key Features

### Messaging (24+ channels)
WhatsApp (Baileys), Telegram (grammY), Slack (Bolt), Discord (discord.js), Google Chat, Signal, iMessage/BlueBubbles, IRC, MS Teams, Matrix, Feishu, LINE, Mattermost, Nextcloud Talk, Nostr, and more.

### Tools & Automation
- Browser control (dedicated Chrome/Chromium with CDP)
- File system read/write, shell command execution
- Cron jobs, webhooks, Gmail Pub/Sub
- Web search (Brave, Perplexity, Gemini, Grok, Firecrawl)
- Voice wake words, Talk Mode (ElevenLabs + system TTS)
- Live Canvas (A2UI - Agent-to-UI)

### Skills System
- Three tiers: Bundled, Managed (ClawHub registry), Workspace (local)
- Skills discovered via SOUL.md files with frontmatter metadata
- Selective injection — only relevant skills injected per turn
- Self-improving skills: agents reflect on output and improve over time
- **Problem**: ClawHub had ~20% malicious skills (800+ out of registry)

### Memory System
- **File-first philosophy**: Markdown files as source of truth
- SQLite index at `~/.openclaw/memory/{agentId}.sqlite`
- Hybrid search: Vector (cosine similarity via sqlite-vec) + Keyword (FTS5)
- Write-Ahead Logging (WAL) + Markdown compaction
- Automatic memory flush before context compaction
- Sliding window chunking with overlap preservation
- 5 components: Session Store, Embedding Cache, Memory Index, Compaction Engine, Memory File System

### Apps
- macOS: Menu bar companion
- iOS: Canvas, Voice Wake, camera, screen recording
- Android: Chat, voice, Canvas, camera, device commands
- Web: WebChat + Control UI

### Model Support
- 35+ providers: Anthropic, OpenAI, Google, self-hosted (vLLM, SGLang, Ollama)
- Model failover and session pruning

## Strengths

1. **Massive ecosystem** — 24+ messaging channels, 100+ prebuilt skills
2. **Model agnostic** — works with any LLM provider
3. **Self-hosted & private** — all data stays on your infrastructure
4. **Rich automation** — cron, webhooks, event-driven workflows
5. **Active community** — fastest-growing OSS project ever
6. **Sophisticated memory** — hybrid search, compaction, auto-flush
7. **Cross-platform** — macOS, iOS, Android, Windows (WSL2), Linux
8. **Agent-to-Agent** — session discovery, history, inter-agent messaging

## Weaknesses & Problems

### Security (CRITICAL)
- 512 vulnerabilities found in Jan 2026 audit (8 critical)
- 9 CVEs in 4 days (March 2026), one scored 9.9/10 CVSS
- CVE-2026-25253: One-click RCE via cross-site WebSocket hijack
- 800+ malicious skills in ClawHub (~20% of registry)
- ClawHavoc campaign: 341 malicious skills delivering credential stealers
- 42,665 exposed instances found, 5,194 actively vulnerable
- Prompt injection attacks via email signatures exfiltrating AWS credentials

### Stability
- 13 point releases in March 2026 alone (~1 every 2 days)
- Frequent breaking changes; users spend 48+ hours fixing after updates
- 5,000+ open issues and 5,000+ open PRs on GitHub

### Performance & Cost
- "Heartbeat tax" — background LLM requests even when idle
- Runaway API costs when tasks get stuck
- 430k lines of code, 400MB runtime — heavy
- Higher token usage from autonomous reasoning loops

### Usability
- Steep learning curve for advanced workflows
- Complex configuration (DM policies, routing, session modes, activation modes)
- Debugging is hard: must debug intent + reasoning + tool selection + prompts
- WSL2 required on Windows (no native support)

### Architecture
- Single-user design only
- WhatsApp via Baileys (unofficial, fragile against Meta API changes)
- Large surface area (24+ channels) = maintenance burden
- Uncertain future after Steinberger left for OpenAI

## Alternatives Landscape (2026)

| Tool | Focus | Key Differentiator |
|------|-------|--------------------|
| **Nanobot** | Lightweight | 4,000 lines Python (99% smaller than OpenClaw) |
| **NanoClaw** | Security | Container-isolated, secure by default |
| **Moltworker** | Serverless | Cloudflare Workers, no local access |
| **memU** | Memory | Proactive agent with long-term knowledge graph |
| **Manus AI** | Cloud | Meta-acquired, $39-199/mo, fully managed |
| **SuperAGI** | Framework | Open-source, CRM + sales/marketing tools |
| **OpenFang** | Agent OS | Rust-based, 7 specialized modules |
| **n8n** | Workflows | Visual drag-and-drop, deterministic execution |
| **Agent S3** | GUI | Controls computers via GUI, human-level performance |

## Key Takeaway

OpenClaw is powerful but bloated, insecure, and unstable. The core ideas are excellent (Gateway architecture, skills system, hybrid memory, multi-channel support), but the implementation has severe security gaps, a massive attack surface, and a codebase that's difficult to maintain. There's a clear opportunity to build something that takes the best architectural ideas while being leaner, more secure, more stable, and more focused.

---

### Sources
- [KDnuggets - OpenClaw Explained](https://www.kdnuggets.com/openclaw-explained-the-free-ai-agent-tool-going-viral-already-in-2026)
- [Wikipedia - OpenClaw](https://en.wikipedia.org/wiki/OpenClaw)
- [GitHub - openclaw/openclaw](https://github.com/openclaw/openclaw)
- [OpenClaw Docs - Features](https://docs.openclaw.ai/concepts/features)
- [DigitalOcean - What is OpenClaw](https://www.digitalocean.com/resources/articles/what-is-openclaw)
- [Medium - Don't Use OpenClaw](https://medium.com/data-science-in-your-pocket/dont-use-openclaw-a6ea8645cfd4)
- [OpenClawAI - Nine CVEs in Four Days](https://openclawai.io/blog/openclaw-cve-flood-nine-vulnerabilities-four-days-march-2026)
- [DigitalOcean - OpenClaw Security Challenges](https://www.digitalocean.com/resources/articles/openclaw-security-challenges)
- [Kaspersky - OpenClaw Vulnerabilities](https://www.kaspersky.com/blog/openclaw-vulnerabilities-exposed/55263/)
- [DeepWiki - Architecture Deep Dive](https://deepwiki.com/openclaw/openclaw/15.1-architecture-deep-dive)
- [Gitbook - Memory System Deep Dive](https://snowan.gitbook.io/study-notes/ai-blogs/openclaw-memory-system-deep-dive)
- [Emergent - 6 OpenClaw Competitors](https://emergent.sh/learn/best-openclaw-alternatives-and-competitors)
- [o-mega - Top 10 Alternatives](https://o-mega.ai/articles/top-10-openclaw-alternatives-2026)

---

# Research: Telegram & WhatsApp Python Libraries (Phase 3 — Communication Layer)

**Date:** 2026-04-04

## Telegram Bot Libraries

### 1. python-telegram-bot

| Attribute | Details |
|-----------|---------|
| **Package** | `python-telegram-bot` |
| **Latest Version** | v22.7 (March 16, 2026) |
| **Bot API Support** | Telegram Bot API 9.5 |
| **Python** | 3.10+ |
| **License** | LGPL-3.0 |
| **GitHub Stars** | ~29,000 |
| **Core Dependency** | httpx (>=0.27, <0.29) |

**Async Support:** Fully async since v20.0. Built entirely on Python's `asyncio`. Uses `httpx` as HTTP backend. Not thread-safe by design (asyncio is single-threaded). Tested with Python 3.14 free threading but thread safety not guaranteed.

**Key Features:**
- Complete static type annotations
- Shortcut methods (e.g., `Message.reply_text`)
- Seamless webhook and polling integration
- Customizable/extendable architecture
- Extensive documentation, wiki, and 50+ examples
- 132 total releases; very mature project (since 2015)

**Optional Extras (install via pip extras):**
- `[rate-limiter]` — `aiolimiter` for built-in `AIORateLimiter`
- `[webhooks]` — `tornado` for webhook serving
- `[callback-data]` — `cachetools` for arbitrary callback data
- `[job-queue]` — `APScheduler` for scheduled tasks
- `[passport]` — `cryptography` for Telegram Passport
- `[socks]` — SOCKS5 proxy support
- `[http2]` — HTTP/2 support
- `[all]` — everything

**Strengths:** Largest community, most documentation, most StackOverflow answers. Extremely stable. Modular extras system.

**Weaknesses:** Async was retrofitted onto a historically synchronous codebase (v20 was a major rewrite). LGPL-3.0 license is more restrictive than MIT. ConversationHandler is complex. API types/methods are manually maintained (slower to track Telegram API updates).

---

### 2. aiogram (RECOMMENDED)

| Attribute | Details |
|-----------|---------|
| **Package** | `aiogram` |
| **Latest Version** | v3.27.0 (April 3, 2026) |
| **Bot API Support** | Telegram Bot API 9.6 |
| **Python** | 3.10 - 3.14, PyPy |
| **License** | MIT |
| **GitHub Stars** | ~5,600 |
| **Core Dependency** | aiohttp |

**Async Support:** Async-first from the ground up. Built on `asyncio` + `aiohttp`. Never had a synchronous version — every design decision assumes async.

**Key Features:**
- **Router System (Blueprints):** Modular handler organization across files/components
- **Dual Middleware:** Intercepts both inbound updates AND outbound API calls
- **Finite State Machine (FSM):** Built-in conversation state management
- **Magic Filters:** Declarative, composable filter DSL for handler matching
- **Auto-generated API code:** Uses [tg-codegen](https://github.com/aiogram/tg-codegen) to auto-generate types/methods from Telegram's spec — tracks API updates faster than any manual library
- **I18n/L10n:** Built-in with GNU Gettext or Fluent
- **Webhook replies:** Can respond directly within webhook requests for lower latency
- Full type hints (mypy compatible)
- Monthly release cadence (very active: 3.24 Jan, 3.25 Feb, 3.26 Mar, 3.27 Apr 2026)

**Optional Extras:**
- `[fast]` — uvloop + msgspec for maximum performance
- `[redis]` — Redis-backed FSM storage
- `[mongo]` — MongoDB-backed FSM storage
- `[proxy]` — proxy support
- `[i18n]` — internationalization
- `[cli]` — command-line tools

**Strengths:** True async-first design. Auto-generated API layer means fastest tracking of new Telegram Bot API features. Router/blueprint system is perfect for modular agent architecture. Dual middleware is powerful for logging, auth, rate limiting. FSM is cleaner than ConversationHandler. MIT license.

**Weaknesses:** Smaller community than python-telegram-bot (~5.6K vs ~29K stars). Less StackOverflow coverage. Learning curve for magic filters. Fewer pre-built examples.

---

### 3. Telethon

| Attribute | Details |
|-----------|---------|
| **Package** | `telethon` |
| **Latest Version** | v1.42.0 (November 5, 2025) |
| **Protocol** | MTProto (NOT Bot API) |
| **Python** | 3.5+ |
| **License** | MIT |

**What It Is:** A full Telegram **client** library using the MTProto protocol directly. It can operate as both a user account and a bot account, bypassing the Bot API entirely.

**Async Support:** Fully async, built on `asyncio`.

**Key Differences from Bot API Libraries:**
- Connects via MTProto (Telegram's native protocol) — not the HTTP Bot API
- Can act as a **user client** (not just a bot)
- Access to features unavailable via Bot API (reading chat history, managing groups as admin, scraping, etc.)
- Higher rate limits (MTProto vs Bot API)
- More complex setup (requires API ID + API hash from my.telegram.org)

**When to Use:** Only if you need user-client capabilities (reading all messages in a group, managing channels as a user, etc.). For standard bot functionality, Bot API libraries are simpler and more appropriate.

**Verdict:** Not recommended for Max's bot use case. Overkill, more complex, and user-client features aren't needed. Could be useful later if Max needs to act as a Telegram user (e.g., monitoring channels).

---

### Telegram Library Comparison Matrix

| Feature | aiogram 3.x | python-telegram-bot 22.x | Telethon 1.x |
|---------|------------|-------------------------|--------------|
| **Async-first** | Yes (always was) | Yes (since v20, retrofitted) | Yes |
| **Protocol** | Bot API (HTTP) | Bot API (HTTP) | MTProto |
| **API tracking speed** | Auto-generated (fastest) | Manual (slower) | N/A (raw protocol) |
| **Bot API version** | 9.6 | 9.5 | N/A |
| **Router/Blueprints** | Built-in | No (handler groups) | No |
| **Middleware** | Dual (updates + API) | Limited | No |
| **FSM** | Built-in | ConversationHandler | No |
| **License** | MIT | LGPL-3.0 | MIT |
| **HTTP backend** | aiohttp | httpx | asyncio raw |
| **Community size** | Medium (~5.6K stars) | Large (~29K stars) | Large (~10K+ stars) |
| **Release frequency** | Monthly | ~Quarterly | ~Quarterly |
| **Python version** | 3.10-3.14 | 3.10+ | 3.5+ |

---

### Telegram Rate Limits

**Per-Chat:**
- Private chats: ~1 message/second (short bursts tolerated, then 429 errors)
- Group chats: max 20 messages/minute

**Bulk/Broadcast:**
- Free tier: ~30 messages/second for notifications
- Paid tier (via @BotFather): up to 1,000 messages/second at 0.1 Stars/message
  - Requires 100,000+ Stars balance and 100,000+ monthly active users
  - Only successfully delivered messages are charged

**File Limits:**
- Downloads (getFile): max 20 MB
- Uploads (sendDocument etc.): max 50 MB

**Polling:**
- getUpdates returns max 100 unconfirmed updates per call

**Best Practices:**
1. Respect per-chat pacing (1 msg/sec private, 20 msg/min groups)
2. Handle 429 errors with exponential backoff
3. Spread bulk sends over 8-12 hours if not using paid broadcasts
4. Use webhooks — responding directly within webhook requests reduces outbound API calls
5. Use `offset` parameter correctly in getUpdates to avoid reprocessing

---

### Webhook vs Long-Polling Trade-offs

| Aspect | Webhook | Long-Polling (getUpdates) |
|--------|---------|--------------------------|
| **Latency** | Lower (push-based, instant delivery) | Higher (pull interval) |
| **Infrastructure** | Requires public HTTPS endpoint | No public endpoint needed |
| **SSL/TLS** | TLS 1.2+ required, valid/self-signed cert | None |
| **Ports** | 443, 80, 88, or 8443 only | Any |
| **IP** | IPv4 only (no IPv6) | Any |
| **Firewall** | Must allow 149.154.160.0/20 and 91.108.4.0/22 | Outbound only |
| **Scaling** | Better (no polling overhead) | Simpler at small scale |
| **CPU** | Lower (event-driven) | Higher (constant polling) |
| **Response optimization** | Can reply directly in webhook response | Must make separate API call |
| **Development** | Harder (need HTTPS, tunnels for local dev) | Easier (works anywhere) |
| **Reliability** | Telegram retries failed deliveries | You control retry logic |

**Recommendation for Max:** Use **long-polling for development** (simpler, no tunnel needed) and **webhooks for production** (lower latency, less CPU, can reply within webhook response). aiogram supports both seamlessly.

---

## WhatsApp Libraries

### 1. PyWa (RECOMMENDED)

| Attribute | Details |
|-----------|---------|
| **Package** | `pywa` (sync) / `pywa_async` (async) |
| **Latest Stable** | v3.9.0 (March 11, 2026) |
| **Pre-release** | v4.0.0b3 (April 1, 2026) — includes BSUID migration support |
| **API** | WhatsApp Cloud API |
| **Python** | 3.10 - 3.14 |
| **License** | MIT |
| **GitHub Stars** | ~526 |
| **Maintainer** | david-lev (very active: 1,259 commits) |

**Async Support:** Full async via separate import path — `from pywa_async import WhatsApp`. API surface identical to sync version; all methods become awaitable. Native FastAPI integration.

**Message Types Supported:**
- Text messages
- Images (with captions)
- Audio files
- Video files
- Documents/files
- Locations
- Contacts
- Interactive buttons (`Button` with title + callback_data)
- Flow buttons (`FlowButton`)
- Template messages (with named parameters, headers, footers, URL buttons, phone buttons, quick replies)
- Reactions
- Read receipts
- Delivery receipts

**Handler System (decorator-based):**
- `@wa.on_message(filter)` — incoming messages
- `@wa.on_callback_button(filter)` — button clicks
- `@wa.on_flow_completion` — completed flow responses
- `@wa.on_call_event` — call events
- Composable filters: `filters.matches("Hello", "Hi")`, `filters.text`, etc.

**Listener System (unique feature):**
```python
age = msg.reply(text="What's your age?").wait_for_reply(filters=filters.text).text
```
Allows inline waiting for user responses — powerful for conversation flows.

**Flow Builder:**
Declarative WhatsApp Flows using Python classes: `FlowJSON`, `Screen`, `Layout`, `TextInput`, `TextHeading`, `Footer`, `CompleteAction`. No raw JSON needed.

**Webhook Integration:**
Native FastAPI and Flask support via `server` parameter. Auto-registers webhook routes.

**Installation Extras:**
- `pywa[fastapi]` — FastAPI webhook dependencies
- `pywa[flask]` — Flask webhook dependencies
- `pywa[cryptography]` — Flow request decryption/response encryption

**BSUID Migration:** WhatsApp is transitioning to Business-Scoped User IDs by March 31, 2026. v4.0.0b3 has full support. This is a breaking change in user ID handling — must plan for this.

**Strengths:** Most comprehensive WhatsApp Cloud API wrapper in Python. Typed (PEP 561). Active maintainer with frequent releases. Listener system is unique. Flow builder avoids raw JSON. MIT license. FastAPI-native async.

**Weaknesses:** Smaller community (~526 stars). Relatively young project. Async requires separate import path (not seamless). BSUID migration in v4.0 is a breaking change.

---

### 2. whatsapp-python

| Attribute | Details |
|-----------|---------|
| **Package** | `whatsapp-python` |
| **Latest Version** | v4.3.0 (November 25, 2024) |
| **API** | WhatsApp Cloud API |
| **Python** | 3.10 - 3.14 |
| **License** | AGPL-3.0 |
| **Status** | Beta |

**Async Support:** Yes — "modern interface using async and await."

**Features:** Sending messages, media (images, audio, video, documents), locations, contacts, interactive buttons, template messages, reactions, replies, read receipts, Graph API error handling.

**Weaknesses:** AGPL-3.0 license (viral, problematic for proprietary use). Beta status. Last update November 2024 (5 months stale). Forked from Neurotech-HQ/heyoo. Less comprehensive than PyWa (no flow builder, no listener system).

**Verdict:** Not recommended. AGPL license is problematic, less actively maintained, and fewer features than PyWa.

---

### 3. Twilio WhatsApp API (Alternative Approach)

| Attribute | Details |
|-----------|---------|
| **Package** | `twilio` |
| **API** | Twilio Programmable Messaging (wraps WhatsApp Business API) |
| **License** | MIT |

**What It Is:** Twilio wraps the WhatsApp Business API through their Programmable Messaging platform. Same API used for SMS/MMS works for WhatsApp.

**Advantages:** Unified API for SMS + WhatsApp. TwiML support. Managed webhook handling. Console management. Large company backing.

**Disadvantages:** Additional cost layer (Twilio charges on top of Meta's charges). Less direct control. Vendor lock-in. SDK is synchronous by default. Adds latency (messages route through Twilio's servers). One WABA per Twilio account.

**Verdict:** Not recommended for Max. Adds unnecessary cost, latency, and vendor dependency. Direct Cloud API via PyWa is better for a self-hosted autonomous system.

---

### WhatsApp Cloud API — Technical Requirements

**Setup Requirements:**
1. Facebook Developer Account
2. Meta Business Account (formerly Facebook Business Manager)
3. Create a Business-type app in Meta Developer Dashboard
4. Configure WhatsApp product
5. Add a phone number (cannot be tied to existing WhatsApp account)
   - New **Coexistence** feature allows same number on Business App + API (with limitations)
6. Verify phone number via 6-digit code
7. Set up webhook with Callback URL + Verify Token
8. Subscribe to Message webhook events

**Meta Business Verification:**
- Required to unlock higher messaging tiers
- Without verification: max 250 unique contacts per 7-day rolling period
- With verification: 2,000 unique contacts per rolling 6-hour period (starting tier)
- Further tiers available after sustained quality messaging

**Messaging Limits (Business-Initiated, per 24-hour rolling window):**
| Tier | Unique Contacts |
|------|----------------|
| Unverified | 250 / 7 days |
| Tier 1 (after verification) | 1,000 / 24 hours |
| Tier 2 | 10,000 / 24 hours |
| Tier 3 | 100,000 / 24 hours |
| Unlimited | No cap |

Tier upgrades happen automatically based on sustained volume and quality (low block/report rates).

**Customer-Initiated Messages:** Unlimited — no cap on responding to users who message you first.

**Pricing Model (per-message, charged on delivery):**
| Category | Description | Cost |
|----------|-------------|------|
| Marketing | Promotions, offers, product recs | Highest rate (varies by country) |
| Utility | Order confirmations, delivery updates | Medium rate |
| Authentication | OTPs, verification codes | Lower rate |
| Service | Customer support replies within 24hr window | **Free** |

**Free Tier:**
- Service conversations (user-initiated): Free within 24-hour window
- Utility templates within 24-hour window: Free
- Click-to-WhatsApp ad responses: Free for 72 hours
- 1,000 free service conversations per month (per WABA)

**Webhook Requirements:**
- HTTPS endpoint (TLS required)
- Must handle GET verification requests (challenge-response with verify token)
- Must handle POST notification requests (incoming messages, status updates)
- Must respond with 200 OK within 20 seconds
- Must be publicly accessible

**Message Types via Cloud API:**
- Text (with preview URLs)
- Images (JPEG, PNG — max 5 MB)
- Audio (MP3, AAC, OGG, AMR — max 16 MB)
- Video (MP4, 3GPP — max 16 MB)
- Documents (PDF, DOC, etc. — max 100 MB)
- Stickers (WebP — max 100 KB static, 500 KB animated)
- Location (latitude, longitude, name, address)
- Contacts (vCard format)
- Interactive messages: Buttons (max 3), Lists (max 10 sections, 10 rows each)
- Template messages (pre-approved by Meta)
- Reactions (emoji reactions to messages)

**On-Premises API Deprecation:** Being deprecated after October 2025. Cloud API is the only path forward.

---

## Final Recommendations

### Telegram: aiogram 3.x

**Package:** `aiogram>=3.27.0`
**Install:** `pip install aiogram[fast,redis]`

**Rationale:**
1. **True async-first** — designed for asyncio from day one, not retrofitted
2. **Auto-generated API layer** — tracks Telegram Bot API updates faster than any competitor (already on 9.6 vs python-telegram-bot's 9.5)
3. **Router/Blueprint system** — perfect for Max's modular agent architecture (each agent module can register its own handlers)
4. **Dual middleware** — intercept both inbound updates AND outbound API calls (critical for logging, rate limiting, auth)
5. **Built-in FSM** — cleaner conversation state management than ConversationHandler
6. **MIT license** — no LGPL restrictions
7. **Monthly releases** — extremely active development
8. **Performance extras** — uvloop + msgspec via `[fast]` extra
9. **Redis FSM storage** — production-ready state persistence via `[redis]` extra
10. **Webhook reply optimization** — can respond directly in webhook response, reducing API calls

### WhatsApp: PyWa (pywa_async)

**Package:** `pywa>=3.9.0` (stable) or `pywa>=4.0.0b3` (with BSUID support)
**Install:** `pip install "pywa[fastapi,cryptography]"`

**Rationale:**
1. **Most comprehensive** WhatsApp Cloud API wrapper in Python — no competitor comes close
2. **Full async support** via `pywa_async` import path
3. **Native FastAPI integration** — webhook routes auto-registered
4. **Typed codebase** (PEP 561) — works with mypy
5. **Listener system** — unique `wait_for_reply` pattern for inline conversation flows
6. **Flow builder** — declarative WhatsApp Flows without raw JSON
7. **Rich message types** — buttons, lists, templates, media, locations, contacts, reactions
8. **MIT license** — no restrictions
9. **Active maintainer** — 1,259 commits, frequent releases
10. **BSUID ready** — v4.0 beta already supports the March 2026 migration

### Architecture Notes for Max

**Shared Infrastructure:**
- Both libraries support webhooks — a single FastAPI server can handle both Telegram and WhatsApp webhooks
- Both are asyncio-native — fits Max's async-everywhere architecture
- Both support Python 3.10-3.14 — compatible with Max's Python 3.12+ requirement

**Suggested Stack:**
```
FastAPI (webhook server)
├── aiogram 3.x (Telegram bot handlers)
├── pywa_async (WhatsApp message handlers)
├── uvloop (event loop optimization)
└── Redis (FSM state + session storage)
```

**Development vs Production:**
- Development: Telegram long-polling + WhatsApp webhook via ngrok/cloudflared tunnel
- Production: Both on webhooks behind reverse proxy (nginx/caddy) with TLS

---

### Sources
- [PyPI - aiogram 3.27.0](https://pypi.org/project/aiogram/)
- [PyPI - Telethon 1.42.0](https://pypi.org/project/telethon/)
- [PyPI - PyWa 3.9.0](https://pypi.org/project/pywa/)
- [PyPI - whatsapp-python 4.3.0](https://pypi.org/project/whatsapp-python/)
- [GitHub - python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- [GitHub - aiogram](https://github.com/aiogram/aiogram)
- [GitHub - PyWa](https://github.com/david-lev/pywa)
- [Telegram Bot API FAQ - Rate Limits](https://core.telegram.org/bots/faq)
- [Telegram Webhooks Guide](https://core.telegram.org/bots/webhooks)
- [WhatsApp Business Platform Pricing](https://business.whatsapp.com/products/platform-pricing)
- [respond.io - WhatsApp Cloud API Guide](https://www.respond.io/blog/whatsapp-cloud-api)
- [Twilio - WhatsApp API Docs](https://www.twilio.com/docs/whatsapp/api)
