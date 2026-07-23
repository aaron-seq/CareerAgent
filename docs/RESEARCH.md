# Research Dossier: Building CareerAgent into a Full Automated Job-Search-and-Application Platform

> Status: Research reference (Phase 0). This document captures the platform
> research that informs the roadmap. It is a **reference**, not a spec — all
> free-tier quotas, legal summaries, and API facts must be re-verified against
> official sources at build time. See `ROADMAP.md` for the phased plan derived
> from this research and `PROGRESS.md` for current status.

## TL;DR
- **CareerAgent today is a single-file Streamlit prototype (~818-line `app.py`) with a modular `core/` package** built around local Ollama LLMs, DuckDuckGo search, PyPDF2/pdfplumber CV parsing, and Gmail draft creation — it does outreach-drafting, not job ingestion or auto-apply, and has no database, no real tests, and unreliable web-scraping via DuckDuckGo.
- **The strongest free foundation is API-first job ingestion** (ATS public APIs: Greenhouse/Lever/Ashby require no auth; Adzuna free tier; The Muse 3,600 req/hr keyed; Remotive/RemoteOK/Himalayas no-auth) **plus JSON-LD `JobPosting` extraction**, with headless scraping reserved as a fallback and full unattended LinkedIn auto-apply avoided entirely.
- **Recommended architecture: keep Python, migrate to FastAPI + Postgres (Supabase/Neon free) + pgvector, use human-in-the-loop autofill (Manifest V3 extension) instead of unattended mass-apply,** and ship in ~10 phased sessions tracked via ROADMAP.md/PROGRESS.md/CLAUDE.md with ADRs.

---

## STEP 1 — The Existing Repository

**Repo:** `github.com/aaron-seq/CareerAgent` — Public, MIT license, Python 95.2% / CSS 4.2% / Dockerfile 0.6%, 6 commits, 0 stars, 1 open PR. Created under user `aaron-seq`.

### Stated purpose
"A local AI-powered career assistant for personalized job outreach. This application automates the process of finding contacts, generating tailored email drafts, and managing your job search workflow using local LLMs." The emphasis is privacy (local inference) and outreach, NOT high-volume job aggregation or auto-application.

### Tech stack (from README + ARCHITECTURE.md + app.py)
- **Frontend/UI:** Streamlit 1.29+ (single `app.py`, 5 screens: Onboarding, Discovery, Contacts, Draft Studio, Export). Custom CSS in `assets/style.css`.
- **LLM:** Ollama local inference; models offered in UI selectbox: `llama3.1:8b`, `llama3.2:3b`, `qwen2.5:7b`, `mistral:7b`. Custom `LocalLLMClient` in `core/llm.py` with JSON parsing + retry.
- **Data validation:** Pydantic 2.5+ (`core/models.py`: `SearchQuery`, `CVProfile`, `JobPosting`, `ContactCandidate`, `EmailDraft`).
- **PDF parsing:** PyPDF2 + pdfplumber (`core/cv_parser.py`).
- **Search:** `duckduckgo-search` library (`core/job_finder.py`, `core/contact_finder.py`).
- **Email:** Google Gmail API for draft creation (`core/gmail_drafts.py`); WhatsApp click-to-chat URL generation (`core/whatsapp.py`).
- **Storage:** local filesystem JSON (`core/storage.py`, `careeragent_data/` directory) + ZIP export.
- **Infra:** Dockerfile + docker-compose.yml (bundles Streamlit + Ollama), `.github/workflows/` present, `.streamlit/` config, `requirements.txt` + `requirements-test.txt`, `.env.example`.

### Module layout (`core/`)
`llm.py` (Ollama client), `models.py` (Pydantic), `validators.py` (draft quality checks), `cv_parser.py`, `job_finder.py`, `contact_finder.py`, `personalization.py`, `gmail_drafts.py`, `whatsapp.py`, `prompts.py`, `storage.py`. Plus top-level `app.py`, `ARCHITECTURE.md`, `CONTRIBUTING.md`, `tests/`.

### What's implemented vs stubbed vs missing
**Implemented (working code visible in app.py):**
- CV upload (PDF or pasted text) → LLM extraction into `CVProfile` (name, email, experiences, projects, skills).
- Job discovery via 3 modes: DuckDuckGo web search, paste job URL (fetch+parse), paste job description.
- Contact discovery: DuckDuckGo-based hiring-manager search + email permutation generation + manual contact entry with confidence scoring (`email_confidence`, `confidence_score`).
- Draft Studio: LLM email generation with 3 angles (technical/impact/product), regenerate, editable subject/body.
- Draft validation: 7 quality gates (has metric, project link, company hook, clear CTA, under 180 words, no emojis, no bullet dashes) with a percentage quality score.
- Gmail draft creation + local save + WhatsApp link.
- Export screen: draft history + ZIP bundle.

**Weak / fragile:**
- **Job discovery relies entirely on `duckduckgo-search`** — unstructured, rate-limited, brittle, returns search snippets not structured postings. No dedicated job-board integrations.
- **Contact finding is DuckDuckGo + email permutation guessing** — no verification (no MX/SMTP check), high bounce risk.
- No salary, seniority, remote/onsite, posting-date fields populated from real sources.

**Missing entirely:**
- No relational database (JSON files only) — no dedup, no pipeline tracking, no historical analytics.
- No real job-board/ATS API integrations.
- No auto-apply or autofill of any kind.
- No resume tailoring/generation (only parsing) — no JSON Resume, no PDF rendering.
- No embeddings / semantic job-to-CV matching / scoring.
- No auth/multi-user (single-user local app).
- No PII encryption at rest (resumes stored as plaintext JSON).
- No email verification, no deliverability infra (SPF/DKIM/DMARC), no send scheduling.
- No visa/sponsorship filtering, no company enrichment, no alerting.

### Code quality / testing / CI / docs
- `app.py` is monolithic (818 lines) mixing UI, orchestration, and business logic; state managed via `st.session_state` — hard to test, no separation of API layer.
- `tests/` directory + `requirements-test.txt` + pytest referenced, but the repo is early (6 commits) and test coverage is almost certainly minimal/skeletal.
- `.github/workflows/` present but content unknown — likely minimal or a stub CI.
- Docs are actually decent for a prototype: README + a genuinely detailed ARCHITECTURE.md (with mermaid diagrams, component tables, design decisions) + CONTRIBUTING.md.
- No `CLAUDE.md`, no ROADMAP.md, no PROGRESS.md, no ADRs.
- `.dict()` used on Pydantic model (deprecated in Pydantic v2 → should be `.model_dump()`).

**Verdict:** A clean, well-documented but narrow prototype. The `core/` module boundaries are a good scaffold to build on. The biggest liabilities to fix first: replace DuckDuckGo job discovery with real APIs, add a database, and add PII encryption. The outreach engine (personalization + validators + Gmail drafts) is genuinely reusable.

---

## STEP 2 — Tooling Landscape (free/open-source first)

### A. Job data sources / aggregation

**ATS public job-board APIs (no auth, JSON, best free source of employer-direct jobs):**

| ATS | Endpoint | Auth | Salary data | Notes |
|---|---|---|---|---|
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | none | rarely | `?content=true` gives full HTML JD; Stripe returns 500+ jobs; one response, no pagination |
| Lever | `https://api.lever.co/v0/postings/{company}?mode=json` | none | sometimes | `descriptionPlain` clean text; `workplaceType` for remote; supports team/location/commitment filters |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true` | none | usually (best) | GraphQL underneath but this REST feed accepts unauthenticated queries; cleanest compensation support |
| SmartRecruiters | `https://api.smartrecruiters.com/v1/companies/{company}/postings` | none | rarely | paginated (limit/offset); **returns HTTP 200 totalFound:0 for wrong slug** — require totalFound>0 before trusting detection |
| Recruitee | `https://{company}.recruitee.com/api/offers/` | none | rarely | per-company subdomain; wrong slug = DNS error not 404, handle connection errors |
| Workable | public careers layer, split endpoints | none | sometimes | main endpoint returns account+jobs; companion endpoints for locations/departments |
| Personio | public board endpoint | none | sometimes | popular with EU scale-ups |

**ATS detection from a company careers URL — regex signatures:**
```
greenhouse:      boards\.greenhouse\.io/([\w-]+)
lever:           jobs\.lever\.co/([\w-]+)
ashby:           jobs\.ashbyhq\.com/([\w.-]+)
smartrecruiters: careers\.smartrecruiters\.com/([\w-]+)
workday:         ([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/([\w-]+)
```
Fetch the careers page HTML, regex for these, then hit the corresponding public API. Warning from practitioners running this across 42 large employers: most big companies are NOT on a modern ATS — many use Workday/Taleo/iCIMS/SuccessFactors which are harder (Workday needs per-tenant JSON POST to `/wday/cxs/...`, no clean public feed).

**Aggregator / job-board APIs (verified free-tier facts, July 2026):**

| API | Base URL | Auth | Free-tier limit | Commercial use |
|---|---|---|---|---|
| **Adzuna** | `api.adzuna.com/v1/api/jobs/{country}/search/{page}` | `app_id`+`app_key` (query params) | Free tier documented as ~1,000 calls/month (≈33/day) per Adzuna developer field guides; official ToS also lists 25/min & 50 results/call. **Note conflict:** a read of the ToS cited 250/day, 2,500/month — re-verify the live ToS at build time. | Non-publisher commercial use "permitted subject to a 14 day trial period… It may not be used… to deliver any ongoing work or research… without written consent." |
| **The Muse** | `www.themuse.com/api/public/v2/jobs` | optional `api_key` query param | Docs: up to **3600 requests per hour** with a registered key; **500 requests per hour** unregistered (20 results/page) | App registration + display terms |
| **USAJOBS** | `data.usajobs.gov/api/Search` | `Authorization-Key` header + `User-Agent`=email + `Host` header | No req-rate published; max 10,000 rows/query, 500/page | Restricted — data for registering company only, no resale w/o OPM approval |
| **Reed** | `www.reed.co.uk/api/1.0/search` | HTTP Basic (API key as username, empty password) | No numeric limit published; max 100 results/search | Free key via signup |
| **Jooble** | `jooble.org/api/{API_KEY}` (POST only) | API key in URL path | No numeric limit documented | Signup form required |
| **Arbeitsagentur** (DE) | `rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs` | static header `X-API-Key: jobboerse-jobsuche` | No signup, no documented limit (community-documented, bundesAPI) | Unofficial API, no published terms |
| **Findwork.dev** | `findwork.dev/api/jobs/` | `Authorization: Token {key}` | Free w/ key, no numeric limit documented; no CORS | Personal token required |
| **Remotive** | `remotive.com/api/remote-jobs` | none | Cache; max ~4×/day, blocked if >2×/min; 24h delayed | Must link back + credit Remotive; no resubmission to 3rd-party sites |
| **RemoteOK** | `remoteok.com/api` | none | ~100 most recent jobs; no numeric limit | **Attribution legally required: direct link, no redirects** |
| **Himalayas** | `himalayas.app/jobs/api` (search `/jobs/api/search`) | none | Public JSON, no key required | Remote jobs, salary/location/timezone |
| **Arbeitnow / Jobicy** | public JSON feeds | none | free | remote aggregators |
| **JSearch** (RapidAPI) | `jsearch.p.rapidapi.com/search` | RapidAPI key | ~200 free req/month (Basic), then paid | Wraps Google-for-Jobs (Indeed/LinkedIn/ZipRecruiter/Glassdoor); RapidAPI ~30% markup; no ATS coverage |
| We Work Remotely | RSS feed | none | free | RSS only |
| Careerjet | partner API | key | affiliate model | — |

**LinkedIn / Indeed / Glassdoor — legal reality (2022–2025):**
- **hiQ v. LinkedIn:** 9th Circuit (April 2022, reaffirming 2019, post-*Van Buren* remand) held that scraping **publicly available** data likely does NOT violate the CFAA ("without authorization" doesn't apply to public sites). **BUT** in Nov 2022, the N.D. Cal. district court ruled hiQ **breached LinkedIn's User Agreement** (contract claim) via scraping + fake accounts, and the parties settled with a consent judgment/permanent injunction.
- **Takeaway:** Scraping public data ≠ CFAA crime, but violates the site's **contract/ToS**, which is separately enforceable. LinkedIn/Indeed/Glassdoor ToS all prohibit automated access. Logged-in scraping (using your account) is contract breach AND risks the account.
- **Van Buren v. US (2021):** narrowed CFAA "exceeds authorized access" to accessing areas you're not permitted to — reinforces that public access isn't a CFAA violation.
- **Safe:** official APIs, JSON-LD extraction from public pages you're allowed to read, ATS public APIs. **Risky:** logged-in LinkedIn scraping, mass automated Indeed/Glassdoor scraping against ToS. **Compliant alternatives:** JSearch/Google-for-Jobs aggregation, ATS APIs, Adzuna/Muse for volume.

### B. Scraping & crawling infrastructure (free/OSS first)

- **JSON-LD `schema.org/JobPosting` extraction is the single highest-value technique** — Web Data Commons found `title` and `datePosted` appear in ~99% of JSON-LD job postings; `baseSalary`/`employmentType` in ~80%. Required fields for Google-for-Jobs: `title`, `description`, `datePosted`, `hiringOrganization`, `jobLocation` (+ recommended `baseSalary`, `employmentType`, `validThrough`, `jobLocationType`). Parse `<script type="application/ld+json">` blocks first before any DOM heuristics — most career pages and boards emit it for SEO.
- **Extraction libs (Python):** `extruct` (JSON-LD/microdata/RDFa), `trafilatura` (main-content text), `readability-lxml`, BeautifulSoup, `selectolax` (fast), `httpx`/`aiohttp` (async fetch).
- **Headless browsers:** Playwright (recommended, best API), Puppeteer (Node), Selenium (legacy). Stealth: `playwright-stealth`, `undetected-chromedriver`. Crawlers: Crawlee (Apify, Python+JS), Scrapy.
- **LLM-reader services:** **Jina AI Reader** (`r.jina.ai/{url}`) — free 20 RPM no key, **500 RPM with free key**, prepend to URL → clean markdown; new accounts get 10M tokens trial (Elastic acquired Jina Oct 2025). **Firecrawl** — free 1,000 credits, Hobby $16/mo 5,000 credits, Standard $83/mo 100k (AGPL-3.0 core, self-hostable). **Crawl4AI** — fully free/OSS, Playwright-based, LLM-aware chunking (best self-hosted). **ScrapeGraphAI** — NL→structured JSON. Diffbot — 10,000 free calls/month.
- **Polite crawling:** respect `robots.txt` (use `urllib.robotparser` or `reppy`), per-domain rate limits + jitter, ETag/Last-Modified caching, exponential backoff on 429/5xx, per-company error isolation, delta logic (only process new/changed via stable IDs).
- **Schema-constrained LLM extraction:** feed cleaned HTML/markdown + a Pydantic schema to an LLM (Gemini/Groq/local) with JSON mode / function-calling for arbitrary pages lacking JSON-LD.

### C. Autofill / auto-apply

**Manifest V3 extension architecture:** content scripts (DOM access, injected per-domain), service worker (background, event-driven, no DOM), `chrome.storage` (local PII), message passing (content ↔ worker via `chrome.runtime.sendMessage`), permissions model (prefer per-site activation via `webext-permission-toggle` + `webext-dynamic-content-scripts` rather than `<all_urls>`).

**How existing tools work:**
- **Simplify Jobs** (Chrome extension): profile-based autofill; "Autofill all fields with AI" answers unique questions from profile; "Continuously autofill multipage forms" walks multi-page apps; optimized for Greenhouse/Ashby/Lever/Workday DOM structures. **Human-in-the-loop by default** (click Autofill per page unless enabled).
- **Job Form Autofiller** (OSS): fuzzy matching so "First Name"/"firstname"/"given_name" map to one field; data stored locally in `chrome.storage`, never leaves browser.
- **AIHawk / Auto_Jobs_Applier / linkedin-easyapply bots** (Python + Selenium/undetected-chromedriver): drive logged-in LinkedIn session; use sleep intervals + stealth to reduce detection.

**Field detection strategies (layered):** (1) `autocomplete` attributes (spec-defined: `given-name`, `email`, etc.), (2) `<label>`/`aria-label`/`aria-labelledby`, (3) `name`/`id` fuzzy matching, (4) placeholder text, (5) heuristic scoring across signals, (6) LLM field mapping for arbitrary/unknown forms (send field context → get profile-key mapping).

**ATS form specifics:** Greenhouse/Lever/Ashby have stable, well-structured DOMs (most fillable, file upload via `<input type=file>`); Workday = multi-step wizard, React, harder, shadow DOM-ish; iCIMS/Taleo = legacy, iframe-heavy, brittle; SmartRecruiters = moderate. Custom EEO/demographic questions and free-text "why do you want to work here" need LLM answers or skip.

**Playwright-driven vs extension-driven auto-apply tradeoffs:**
- **Extension (human-in-loop):** runs in the user's real browser session, uses their real cookies/fingerprint → **lowest ban risk**; user clicks submit → stays on right side of ToS/ethics. Recommended.
- **Playwright unattended:** scales but creates detectable automated session activity; on LinkedIn/Indeed = ToS violation + account restriction risk.
- **LinkedIn Easy Apply automation:** all OSS bots carry explicit disclaimers — LinkedIn actively detects automation; accounts get restricted/soft-banned; no automation is undetectable. The realest risk is binary: **only tools that drive your logged-in session risk bans**; postings-layer/API tools produce zero account activity.

### D. Resume / CV tooling

- **Parsing:** `pyresparser`, `pdfplumber`/PyMuPDF(`fitz`)/`python-docx`/`unstructured.io` for text; spaCy/HuggingFace NER; **LLM structured parsing into JSON Resume schema** (most robust). Affinda free tier for hosted parsing.
- **JSON Resume standard** (`jsonresume.org`): open JSON schema (`basics`, `work`, `education`, `skills`, `projects`, etc.), CLI + large theme ecosystem, git-versionable. Convert to RenderCV: `npx @jsonresume/jsonresume-to-rendercv resume.json`.
- **Generation/rendering:** **RenderCV** — MIT-licensed, renders one YAML source to PDF, LaTeX, Markdown, HTML and PNG. Also Typst (fast modern LaTeX alt), LaTeX (moderncv/Awesome-CV), WeasyPrint (HTML→PDF), Puppeteer print-to-PDF, `python-docx`/`docxtpl` (DOCX), react-pdf. **OpenResume** (browser-local, instant ATS score), **Reactive-Resume** (OSS, no watermark).
- **ATS-friendliness (evidence-based):** single-column layout only; NO tables, text boxes, multi-column, headers/footers (contact info in header/footer is skipped by ~25% of ATS), images/logos/icons (read as garbage), progress bars/skill graphics. Standard fonts (Arial/Calibri/Georgia/Garamond 10–12pt). Standard section headings ("Experience", "Education", "Skills" — not "My Journey"). Selectable text (never image/scanned PDF). DOCX generated from Word most compatible; text-based PDF acceptable. Standard date format ("Jan 2020 – Present").
- **JD matching:** free embeddings via **sentence-transformers `all-MiniLM-L6-v2`** — a 6-layer MiniLM encoder with ~22.7M parameters, ~80MB, mapping text to a 384-dimensional L2-normalized vector. Alternatives: `all-MiniLM-L12-v2` (33M), `bge-small`. Cosine similarity between resume and JD embeddings; store in pgvector/FAISS/Chroma. Also TF-IDF + KeyBERT + RapidFuzz for keyword-gap analysis. Local via Ollama embeddings; Voyage/Cohere free tiers (Cohere 1,000 calls/mo).
- **OSS to learn from:** Resume-Matcher, OpenResume, Reactive-Resume, RenderCV, JobFunnel.

### E. Cold outreach / email

**Contact finding (free tiers):**
| Tool | Free tier |
|---|---|
| Hunter.io | 25 searches + 50 verifications/month, no card, source-cited, best dev API |
| Apollo.io | ~10,000 credits/month (fair-use), but only 10 CSV exports/month; largest DB |
| Snov.io | 50 credits/month, includes LinkedIn extraction + drip campaigns |
| Skrapp | 100 rollover credits |
| Clearbit | now HubSpot Breeze Intelligence (ecosystem-only) |
| RocketReach / Proxycurl / PDL | limited/paid |

**Email permutation + verification (free/OSS):** generate `{first}@`, `{first}.{last}@`, `{f}{last}@`, etc.; verify with **`dnspython`** (MX lookup), **`email-validator`** (syntax + deliverability), SMTP handshake (RCPT TO without send — but many servers block/greylist). Verifalia free tier.

**Sending (free tiers):** Gmail API (free within Google quotas, ~500 recipients/day consumer / 2,000 Workspace), Resend (free 3,000 emails/mo, 100/day), Brevo/Sendinblue (300/day free), Mailgun (limited trial), SMTP via personal Gmail, Nodemailer (Node) / `smtplib` (Python).

**Deliverability:** SPF + DKIM + DMARC records on sending domain, domain warmup, low send-rate + jitter, reply detection (IMAP poll or Gmail API threads), threading (`In-Reply-To`/`References` headers).

**CRITICAL — legal layer (verified 2024–2026):**
- **CAN-SPAM (US):** no consent needed; require accurate From/Reply-To, honest subject, **physical postal address**, functioning opt-out honored within 10 business days. Violations up to **$53,088 per non-compliant email** (FTC inflation-adjusted maximum effective January 17, 2025); the FTC states CAN-SPAM "makes no exception for business-to-business email."
- **GDPR (EU):** B2B cold email legal under **Article 6(1)(f) legitimate interest** (Recital 47 explicitly names direct marketing); requires a documented **Legitimate Interest Assessment (LIA)** per campaign (purpose/necessity/balancing tests), opt-out in every email, sender identification + postal address, honor opt-outs (remove within 30 days, ideally before next send). B2C requires consent. Fines up to €20M or 4% global revenue.
- **Country specifics:** Germany (UWG §7) strictest — effectively double opt-in even B2B; France (CNIL) permissive for profession-related B2B to corporate addresses; UK (PECR Reg 22) treats corporate subscribers more leniently but individuals need consent. Regulators do enforce (e.g. CNIL's €50M Orange sanction, 14 Nov 2024, under Article L.34-5 CPCE).
- **CASL (Canada):** requires consent BEFORE first send; penalties up to $10M/violation.
- **India DPDP Act (2023):** consent-based regime for personal data processing.
- **Practical build:** treat recruiter/hiring-manager outreach as B2B legitimate-interest; ALWAYS include identification + physical address + one-click opt-out; store a suppression list and check it before every send; document a per-campaign LIA; default conservative send caps; never use B2C/personal addresses.

### F. Orchestration, AI & infra (free-tier)

**LLM options (verified free tiers, 2026):**
- **Google Gemini** — permanent free tier, Gemini 2.5 Flash ~1,500 req/day, Pro ~5 RPM/100 RPD/250k TPM, 1M context. Best free frontier baseline.
- **Groq** — fastest inference, Llama 3.3 70B ~14,400 req/day free, 30k TPM.
- **Cerebras** — 1M tokens/day free, no card.
- **OpenRouter** — some `:free` models (changes monthly; verify at openrouter.ai/models).
- **Mistral** — 1B tokens/month free (but prompts may train models).
- **Cohere** — 1,000 calls/month (eval only).
- **Together** — $100 signup credits (not permanent).
- **Anthropic Claude / OpenAI** — no meaningful permanent free tier (trial credits only).
- **Local via Ollama** — Llama 3.x, Qwen 2.5, Mistral (already in CareerAgent); $0, private, sufficient for CV parsing, field mapping, draft generation, extraction. Use local for PII-heavy tasks (resumes), cloud free tiers for scale bursts.

**Agent frameworks:** For a single-dev app, **prefer plain function-calling / Pydantic AI** (type-safe, MIT, model-agnostic, lowest cost) over heavier LangGraph (best for complex cyclic/stateful workflows with checkpointing) or CrewAI (fast multi-agent role prototypes). Recommendation: **start with plain Pydantic AI + structured outputs; add LangGraph only if you need durable multi-step checkpointed workflows.**

**Job queues / scheduling:** APScheduler (simplest in-process), RQ (Redis, simple), Celery+Redis (heavier), **GitHub Actions cron (free, great for periodic scraping/digests)**, BullMQ (Node), Temporal/Inngest (free tiers, durable).

**Databases (free tiers):** **Supabase** (500MB Postgres, Auth 50k MAU, 1GB storage, 500k edge fn calls, 2 projects, pauses after 7 days inactivity) vs **Neon** (0.5GB/project, 100 CU-hours/mo, up to 100 projects, scale-to-zero, branching, no pause). SQLite for local/dev; **pgvector** for embeddings in Postgres; Chroma/Qdrant (free tier) for standalone vector; DuckDB for analytics.

**Deployment free tiers:** Vercel (frontend/serverless), Render (web svc, but free Postgres deleted after 30 days), Fly.io, Railway, Cloudflare Workers (10k neurons/day AI), Hugging Face Spaces (Streamlit/Gradio hosting — natural fit for current app), Oracle Cloud always-free (real VM), or self-host on home machine (needed anyway if using Ollama).

**Secrets & PII:** never commit secrets (`.env` + `.gitignore` already present); use platform secret stores; **encrypt resumes/PII at rest** (Postgres `pgcrypto` or app-level Fernet/`cryptography`); auth via Supabase Auth / Auth.js / Clerk free tiers.

### G. Additional high-value features
- **Dedup across boards:** fuzzy match on normalized (title + company + location), canonical URL resolution, stable ATS IDs; the same role appears 3–4× (Greenhouse + LinkedIn + Indeed + Glassdoor).
- **Scoring/ranking:** embedding cosine similarity (resume ↔ JD) + rules (seniority, location, must-have skills) → explainable score with matched/missing keywords.
- **Salary enrichment:** Adzuna salary histogram API, Levels.fyi, Glassdoor, BLS, H-1B LCA wage data.
- **Company enrichment:** funding/headcount, Glassdoor rating, **layoffs.fyi** (layoff data), hiring velocity from ATS job counts over time.
- **Application tracking:** kanban pipeline (saved→applied→screen→interview→offer), status, follow-up reminders.
- **Interview prep:** generate likely questions from JD; mock-interview Q&A via LLM.
- **Referral finding:** alumni/network overlap.
- **Tailored cover letters + resume variants** (A/B tested).
- **Follow-up sequences + reply detection.**
- **Analytics:** application→response funnel.
- **Visa sponsorship filtering (free public datasets):** US — **USCIS H-1B Employer Data Hub**, **DOL OFLC LCA disclosure files** (h1bdata.info indexes millions of records), MyVisaJobs. UK — **data.gov.uk / Home Office Register of Licensed Sponsors** (downloadable). Filter jobs by whether employer appears in sponsor datasets.
- **New-grad/internship filtering**, **ghost-job detection** (repost frequency, stale `datePosted`, reposting signals), **duplicate-application prevention**, **company blacklist**.
- **Alerting:** Telegram bot, Discord webhook, email digest, RSS output (all free).

---

## STEP 3 — Risk, Ethics & Policy

**Unambiguously fine (build freely):**
- Official job-board/ATS APIs (Greenhouse/Lever/Ashby/Adzuna/Muse/USAJOBS/Remotive with attribution).
- JSON-LD extraction from public pages you're permitted to view.
- Resume parsing/tailoring/rendering; ATS keyword analysis.
- Application tracking, scoring, interview prep, analytics.
- **Human-in-the-loop autofill** (assist a human who reviews + clicks submit).

**Gray (proceed with care, respect robots.txt + rate limits + ToS):**
- Headless scraping of public job pages lacking APIs (legal under hiQ/CFAA re: public data, but may breach site ToS/contract — prefer APIs, honor robots.txt, throttle, cache).
- Contact enrichment / email permutation (verify before send, low volume, B2B legitimate-interest framing).

**Real risk (avoid or heavily constrain):**
- **Fully unattended mass auto-apply** — quality collapse, employer irritation, wasted applications.
- **LinkedIn/Indeed logged-in automation** — ToS breach + account restriction/ban (hiQ district-court contract ruling; all OSS bots disclaim ban risk).
- **Unsolicited bulk email at scale** — CAN-SPAM/GDPR/CASL exposure; deliverability + reputation damage.
- **Misrepresenting the candidate** — fabricating experience/credentials in auto-filled answers or cover letters.

**Concrete design choices to stay on the right side:**
1. **Human-in-the-loop confirmation before every submit** (autofill fills, user reviews + clicks).
2. **Per-site rate limits + jitter + caching**, respect `robots.txt`, `User-Agent` identifying the tool.
3. **Prefer official APIs**; scraping only as fallback; never logged-in scraping of social platforms.
4. **Honor opt-outs** (persistent suppression list), include identification + postal address in every outreach email, documented LIA.
5. **Never fabricate** experience/credentials — LLM answers must draw only from the user's real profile; flag anything it can't answer truthfully for human input.
6. **Encrypt PII at rest**, local-first for resume data, explicit user consent for any cloud send.
7. **Disclosure norms** — don't impersonate; outreach should be honest about being from the candidate.

---

## STEP 4 — Recommended Architecture & Phased Roadmap

### Recommended stack (opinionated, free-tier, single-dev maintainable)
- **Language:** stay Python (repo is 95% Python, Ollama/pydantic already there).
- **Backend:** **FastAPI** (typed, async, testable) as an API layer; extract business logic out of `app.py` into services. Keep Streamlit OR move UI to it later.
- **UI:** keep **Streamlit** initially (fast, already built); optionally add a Manifest V3 **browser extension** for autofill (separate sub-project).
- **DB:** **Postgres via Supabase or Neon free tier** + **pgvector** for embeddings; SQLite for local dev. Replace JSON-file storage.
- **ORM/migrations:** SQLModel or SQLAlchemy + Alembic.
- **LLM:** Ollama local (default, PII-safe) + Gemini/Groq free tiers for burst; **Pydantic AI** for structured extraction/agents.
- **Embeddings:** sentence-transformers `all-MiniLM-L6-v2` (local, free) → pgvector.
- **Job ingestion:** ATS public APIs + Adzuna/Muse/Remotive + JSON-LD (`extruct`) + Jina Reader/Crawl4AI fallback.
- **Scheduling:** APScheduler locally / GitHub Actions cron for digests.
- **Auth (when multi-user):** Supabase Auth.
- **Email:** Gmail API (drafts already work) + verification via dnspython/email-validator.
- **Autofill:** Manifest V3 extension, human-in-the-loop.
- **Deploy:** HF Spaces or self-host (Ollama needs local compute); GitHub Actions for scheduled jobs.
- **Testing:** pytest + `respx`/`vcr.py` for API mocking; ruff + mypy; GitHub Actions CI.

### Stateful resumption / repo hygiene
- **`CLAUDE.md`** — conventions file.
- **`ROADMAP.md`** — the phase list with acceptance criteria.
- **`PROGRESS.md`** — living log: current phase, what's done, next action, blockers, updated at end of each session.
- **`docs/adr/`** — Architecture Decision Records (one MD per significant decision, numbered).
- **GitHub issue templates** — one per phase with acceptance-criteria checklist.
- **Conventional commits** + a branch per phase.

### Phased delivery roadmap (~10 phases, each ~one focused session, shippable, tested)

**Phase 0 — Foundation & hygiene.** Add CLAUDE.md, ROADMAP.md, PROGRESS.md, ADR folder, issue templates; set up ruff+mypy+pytest+CI in `.github/workflows`; fix Pydantic v2 deprecations; add `.env` schema. *AC:* CI green, lint clean, docs present.

**Phase 1 — Data layer.** Introduce Postgres (Supabase/Neon) + SQLModel + Alembic; migrate models (`CVProfile`, `JobPosting`, `Contact`, `EmailDraft`, `Application`) from JSON to DB; add PII encryption for resume fields. *AC:* CRUD + migration tests pass; JSON import path works.

**Phase 2 — Real job ingestion (APIs).** Replace DuckDuckGo discovery with an ingestion service: Greenhouse/Lever/Ashby public APIs + Adzuna + The Muse + Remotive; normalize into a canonical `JobPosting` schema; store with source + fetched-at. *AC:* pulls ≥N real jobs from ≥3 sources into DB with tests (mocked HTTP).

**Phase 3 — ATS detection + JSON-LD extraction + polite fetcher.** Company-domain → ATS detection (regex signatures); `extruct` JSON-LD `JobPosting` parser; robots.txt + rate-limit + cache layer; Jina Reader/Crawl4AI fallback for pages without JSON-LD. *AC:* given a careers URL, returns structured jobs; robots.txt honored; tests with fixtures.

**Phase 4 — Dedup + embeddings + scoring.** Fuzzy dedup (title+company+location, canonical URL); sentence-transformers embeddings → pgvector; resume↔JD cosine score + keyword-gap (KeyBERT/RapidFuzz) with explainability. *AC:* duplicate jobs collapse; each job gets an explainable match score vs the CV.

**Phase 5 — Resume tooling.** LLM parse into **JSON Resume schema**; ATS-friendliness linter (flag tables/columns/headers/icons); render via RenderCV (YAML→PDF); tailored-variant generation per JD (truthful, no fabrication). *AC:* upload → JSON Resume → ATS-clean PDF; tailoring cites only real profile data.

**Phase 6 — Application tracking pipeline.** Kanban states (saved→applied→screening→interview→offer/rejected); follow-up reminders; duplicate-application prevention; company blacklist. *AC:* full lifecycle tracked; reminders fire; no double-apply.

**Phase 7 — Outreach engine hardening (compliance).** Reuse existing personalization + validators + Gmail drafts; add email verification (dnspython/email-validator), suppression list, per-campaign LIA record, postal address + opt-out in every template, send caps + jitter, reply detection. *AC:* no send without verification + suppression check; compliance fields enforced by tests.

**Phase 8 — Human-in-the-loop autofill extension.** Manifest V3 extension: profile in `chrome.storage`, content-script field detection (autocomplete→ARIA→label→fuzzy→LLM fallback), per-site activation, fills but **user reviews + submits**; optimized for Greenhouse/Lever/Ashby. *AC:* fills a real Greenhouse form correctly; never auto-submits.

**Phase 9 — Enrichment, filters, alerting.** Salary (Adzuna salary API), company enrichment (layoffs.fyi, Glassdoor rating), **visa sponsorship filter** (USCIS H-1B Data Hub / DOL LCA / UK sponsor register), ghost-job detection, new-grad/intern filter; alerting via Telegram/Discord/email digest/RSS (GitHub Actions cron). *AC:* jobs annotated with salary/visa/company signals; daily digest delivered.

**Phase 10 — Analytics + polish + deploy.** Application→response funnel, A/B resume-variant tracking; interview-prep generation from JD; deploy (HF Spaces / self-host + scheduled Actions); docs + onboarding. *AC:* dashboard renders funnel; deployment reproducible; README updated.

---

## Recommendations
1. **First session (Phase 0–1):** Establish repo hygiene + move off JSON to Postgres. This unblocks everything and is low-risk. Benchmark to proceed: CI green + DB migration tested.
2. **Prioritize API-first ingestion (Phase 2–3) over any scraping.** The ATS public APIs + Adzuna/Muse/Remotive + JSON-LD give you the bulk of job coverage with zero legal risk and no proxies. Only add headless scraping (Crawl4AI) when a target lacks both an API and JSON-LD.
3. **Build autofill as human-in-the-loop from day one (Phase 8) — never unattended mass-apply.** This is the single most important design decision for staying on the right side of ToS/ethics and avoiding account bans.
4. **Keep resume PII local + encrypted.** Use Ollama for resume parsing/tailoring; reserve cloud LLM free tiers for non-PII scale tasks (job extraction, dedup).
5. **Treat outreach as regulated (Phase 7).** Bake CAN-SPAM/GDPR compliance into the data model (suppression list, postal address, opt-out, LIA) rather than bolting it on.
6. **Thresholds that change the plan:** if job volume needs exceed free-tier quotas (e.g., Adzuna's monthly cap), shift to more ATS direct pulls + JSON-LD rather than paying; if you need multi-user/hosted, add Supabase Auth + move Ollama to a hosted GPU or swap to Gemini/Groq free tiers.

## Caveats
- **Repo internals:** module-level code was partly inferred from README + ARCHITECTURE.md + `app.py`; verify exact dependency versions and test coverage directly.
- **Free tiers change frequently** — re-verify all quotas at build time against official docs (API facts verified July 2026; scraping/LLM tiers ~May–July 2026).
- **Adzuna quota conflict:** developer field guides cite ~1,000 calls/month while a read of the official ToS suggested 250/day–2,500/month. Both agree on 25 req/min and 50 results/call and on the 14-day commercial trial restriction. **Re-verify the live Terms of Service before relying on a specific monthly number.**
- **Legal is not advice:** hiQ/CFAA analysis and CAN-SPAM/GDPR summaries are practical engineering guidance, not legal counsel. ToS still binds you. Consult counsel before any scraping or bulk-outreach at scale.
- **Arbeitsagentur and some feeds are unofficial/community-reverse-engineered** (no published terms) — use cautiously.
- Some rate-limit numbers (Reed Jobseeker, Jooble, USAJOBS request-rate, Findwork, RemoteOK) are **not publicly documented**; only Adzuna and The Muse publish hard numeric limits.
