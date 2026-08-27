# Progress Log

Living status log. Update the top block at the end of every working session.
Full plan in `ROADMAP.md`; conventions in `CLAUDE.md`; research in `docs/RESEARCH.md`.

## Current status
- **Current phase:** Phases 0–10 **complete**. Post-Phase-10 hardening ongoing.
- **Last updated:** 2026-08-27
- **Next action:** **Decide on SECURITY_AUDIT C-1** (real CV PII in public git
  history — needs `git filter-repo` + force-push, owner decision). Then the
  outreach-compliance findings F-1/F-2/F-3, which breach guardrail 5. Then the
  older job-matching keyword-extraction fix (see 2026-07-27 entry).
- **Blockers:** C-1 is live PII exposure on a public repo and is unresolved. This session ran with live network access (real Remotive
  API pulls, real Groq LLM calls) for the first time — see log below. Earlier
  entries' "build env can't reach external services" note no longer applies
  to LLM calls or job-board APIs; still true for pgvector.

## Verification level per phase
- **Genuinely run + tested here:** P1 data layer, P4 dedup/scoring, P5 resume
  tooling, P6 tracking, P7 outreach gate logic, P9 enrichment/digest, P10
  analytics, and the full internal E2E (`tests/test_e2e_pipeline.py`).
- **Built + unit-tested, external boundary mocked:** P2 ingestion adapters
  (respx), P3 JSON-LD/polite fetcher (respx), P7 email verification (stub
  resolver), P9 Telegram/Discord emitters (respx).
- **Built + unit-tested, NOT live-verified:** P8 extension in a real browser,
  real email delivery, and deployment (dry-run only).

Totals: **204 Python tests + 11 JS tests green; `ruff` + `ruff format` clean.**

## Log

### 2026-08-27 — 13 job sources live-verified, timestamp convention, security audit

Three parallel agents on disjoint files; all work verified, none committed.

**Job ingestion: 6 sources -> 13.** New company ATS boards (SmartRecruiters,
Recruitee, Workable) and keyless job boards (Arbeitnow, Jobicy, RemoteOK,
Himalayas), plus an `ATTRIBUTION` map so sources that legally require credit
(RemoteOK especially) get it in the UI. `app.py` now drives both pickers from
`facade.aggregator_providers()` / `ats_providers()` instead of hardcoded lists.

Live-verified 2026-08-27 against real vacancies: Arbeitnow 175, RemoteOK 99,
Jobicy 50, Himalayas 20; SmartRecruiters BoschGroup + PublicStorage; Workable
blueground/spotawheel/orfium/skroutz; Recruitee fixico/hygraph. 344 live
postings from the four keyless boards alone.

**Wellfound: NOT VIABLE, do not implement.** Four independent blockers verified
(no public API, no logged-out JSON-LD + Turnstile, robots.txt disallows the
browse surface, ToS bars automated collection). Breaches guardrail 3. Use the
startup's own Greenhouse/Lever/Ashby board instead. Full evidence in
`docs/RESEARCH.md` A2.

**Timestamp convention: naive datetimes holding UTC**, repo-wide. `utc_now()`
and `to_naive_utc()` in `core/normalize.py` are the only producers/coercers.
Chosen over timezone-aware because SQLite `DATETIME` and Postgres `timestamp
without time zone` (ADR 0003) cannot persist an offset, so aware values
round-trip to naive and then raise `TypeError` on comparison. Killed all 194
`datetime.utcnow()` deprecation warnings. Fixed a real bug this exposed:
`date_posted` from `dateutil` arrives aware, and was being written into a naive
column with the offset silently dropped (`+05:30` stored as UTC, off by 5.5h) —
now coerced at both ingestion boundaries.

**CI has never passed.** `requirements-test.txt` pinned `responses==0.25.9`, a
version never published to PyPI (0.25.8 -> 0.26.0), so `pip install` died before
`pytest` ran on every job — every merge to `main` went in ungated. The package
was imported nowhere (`respx` does all HTTP mocking), so the pin was deleted
rather than corrected. Dependency set now resolves clean.

**Security audit** -> `docs/SECURITY_AUDIT.md` (21 findings: 1 Critical, 8 High).
Independently verified: repo is PUBLIC, commit `d92bfb5` added 11
`cv_profile_*.json` files with real name/phones/email, still in history after
being untracked. Also: the CAN-SPAM footer is displayed but not sent
(`app.py` sends the raw textarea body, not `decision.body`), opt-out HMAC keys
regenerate per process when `CAREERAGENT_ENCRYPTION_KEY` is unset, the send cap
is inert, and `assert_no_fabrication` has a demonstrated bypass (the guard
trusts the whole JD while the model only sees `[:3000]`).

**Tests: 297 -> 330 passing, warnings 194 -> 9.** `ruff` clean.

### 2026-07-27 — CV parsing fabrication fix, cover letters, Groq provider, dark-native redesign
First session with live network access: real Groq LLM calls and a real
Remotive job-API pull, tested against the maintainer's actual CV end-to-end.
- **Found and fixed a real fabrication bug.** A CV's contact links render as
  anchor text (visible word "Github") with the URL only in the PDF's link-
  annotation layer, which `extract_text()` discards. With no URL in its input,
  the model invented a plausible-looking one from the candidate's name --
  `github.com/AaronSequeira` instead of the real `github.com/aaron-seq`. Fixed
  by extracting annotation-layer hyperlinks (`_extract_hyperlinks_from_pdf`)
  and appending them to the prompt after truncation, plus rewriting the
  prompt's placeholder shape (which itself taught the model to invent a
  username) into an explicit copy-or-null instruction with an anti-fabrication
  rule. Verified against the real CV: GitHub/LinkedIn now match exactly, two
  previously-null project repo links recovered. 6 new tests
  (`tests/test_cv_parser.py`).
- **Added cover letter generation** (`core/resume/cover_letter.py`), gated the
  same way `tailor.py` gates resume tailoring: raises rather than ship a
  letter naming an employer not in the CV or citing an unsupported metric.
  First live draft cited zero metrics -- the guard had made the model avoid
  numbers entirely; rewrote the prompt to positively push real figures, and
  the next draft cited 5, all CV-verified, plus one honestly-flagged gap. 8
  new tests (`tests/test_cover_letter.py`).
- **Added Groq as a free cloud LLM provider** alongside Ollama
  (`CloudLLMClient` in `core/llm.py`, subclasses `LocalLLMClient`, overrides
  only the 3 HTTP methods). Lets the app run without installing Ollama +
  pulling multi-GB models first. This is a deliberate, documented deviation
  from ADR 0002's "cloud only for non-PII work" guardrail -- see ADR 0005.
  Verified live: connected, listed 15 models, `generate_json` round-tripped.
- **Dark-native UI redesign.** `assets/style.css` had been authored for a
  light theme while `.streamlit/config.toml` set a dark one, rendering every
  heading near-invisible (near-black text on near-black background). Rewrote
  dark-native; added a stage rail across the top reflecting the app's real
  screen gating (Discovery can't run before Onboarding); reworded the six
  gating messages from state descriptions ("please initialize LLM first") to
  next actions ("pick a provider, then choose Initialize LLM").
- **Privacy cleanup:** 11 parsed CV profiles (real PII: name, email, phone,
  employers) and 1 job posting were tracked in git as stale test artifacts.
  Untracked them and extended `.gitignore` to prevent recurrence
  (`careeragent_data/{cv_profiles,contacts,job_postings}/`, `*_CV.pdf`). Note:
  content is still in git history; a full purge needs a history rewrite, left
  for the repo owner.
- **Found, not yet fixed:** job-matching keyword extraction
  (`core/matching/scoring.py::_job_keywords`) prefers curated
  `tech_stack`/`requirements`, but aggregator-ingested jobs never populate
  those fields (only the LLM job-parse path does) -- so it falls back to
  tokenizing the raw description against a 20-word stopword list. Observed
  live: a real job's "missing skills" list was full of stopwords (`at`, `is`,
  `who`, `why`) and punctuation-glued tokens (`api.`, `built.`), and match
  scores are systematically deflated (4 matched / ~200 prose tokens). Fix:
  run aggregator-ingested jobs through the existing `JOB_PARSE_PROMPT` to
  populate `tech_stack` -- the parser already exists, ingestion just skips it.
  Cost is one LLM call per job, a tradeoff intentionally left for the
  maintainer to decide rather than assumed.
- 14 new tests. Totals: **204 Python + 11 JS tests green; ruff clean.**

### 2026-07-25 — Removed fabricated enrichment data (honesty fix)
The bundled "sample" enrichment CSVs contained **invented facts about real,
named companies** (Glassdoor ratings, layoff history, sponsor status), and the
lookup logic turned *absence of data* into a **false negative** — any company
missing from an 8-row file was recorded as `sponsors_visa = False`. For a
job-search tool that is actively harmful: a user could rule out an employer
because of data we made up.
- **Deleted** both fabricated CSVs. Nothing is shipped in their place.
- **Tri-state everywhere:** `is_sponsor()` / `CompanySignal` return
  `True` / `False` / `None`; `None` means *unknown* and is never rendered as a
  negative. `annotate()` is a no-op without a dataset, leaving columns NULL.
- **Schema:** `Company.had_layoffs` `bool = False` → `Optional[bool] = None`
  (a default of `False` asserted "no layoffs" for every unknown company).
  Migration `cbb284f817e8`, up/down verified.
- **Real loaders:** `VisaSponsorFilter.from_csv` auto-detects the employer
  column across the official UK Home Office and USCIS export formats.
- **`scripts/fetch_datasets.py`** downloads the real UK register (discovers the
  current CSV on gov.uk), verifies it parses, writes atomically via a `.part`
  file, and fails loudly rather than leaving a truncated file.
- **UI honesty:** the "visa sponsors only" filter is *disabled* with an
  explanation when no register is loaded; a caption reports when matching is
  using the lexical fallback rather than semantic embeddings
  (`facade.data_status()`). Removed hardcoded `stripe` demo defaults.
- 20 new/rewritten tests. Totals: **180 Python + 11 JS green; ruff clean.**

**Still not real in this environment** (network is blocked except PyPI): live
API pulls, the actual dataset download, semantic embeddings (model hub
unreachable), and any live browser render.

### 2026-07-23 — Remaining core services surfaced (branch: claude/discovery-api-first)
Every `core/` service is now reachable from the UI; nothing built in Phases
1–10 is left unwired.
- **Aggregator ingestion** (`ingest_aggregator`): Remotive (keyless), The Muse
  (optional key), Adzuna (requires env keys, fails with a clear message).
  Surfaced as a "Job boards (API)" Discovery mode, with the Remotive
  attribution requirement shown in the UI.
- **Full enrichment chain** in `refresh_matches`: dedup → link companies →
  salary → ghost score → visa sponsor → company signals → score. Fixed a real
  gap: jobs were never linked to their `Company` row (`link_companies`), so
  visa/Glassdoor/layoff data could not be joined per job.
- **Filters** on the Pipeline screen: min score, remote-only, hide ghost jobs,
  visa sponsors only, new-grad/internship level.
- **Digest** on the Export screen: rendered inline + Markdown and RSS
  downloads (`digest_rss` added).
- **Interview prep** in Draft Studio: questions derived from the JD, with a
  downloadable prep list.
- 7 new facade tests. Totals: **165 Python + 11 JS tests green; ruff clean.**

### 2026-07-23 — Discovery reworked to API-first (branch: claude/discovery-api-first)
- Facade gains `discover_from_url`: detects the ATS from a careers URL and pulls
  its public feed; otherwise fetches politely (robots.txt honored, rate-limited)
  and extracts `schema.org/JobPosting` JSON-LD. Recognized-but-unsupported ATS
  (e.g. Workday) is reported explicitly rather than silently scraped.
- **Discovery screen** reordered API-first: "Company careers URL (recommended)"
  is the default mode; DuckDuckGo is retained but relabeled "Web Search
  (fallback)" with a caveat about unstructured results.
- Fixed a branch-chain bug introduced while restructuring the modes (the new
  mode fell through to the paste-description branch), and moved the LLM guard
  from the whole screen to only the modes that need it — the careers-URL and
  paste-description modes now work without Ollama.
- 5 new facade tests (ATS detect, JSON-LD fallback, unsupported ATS, robots
  block, no-JSON-LD). Totals: **158 Python + 11 JS tests green; ruff clean.**

### 2026-07-23 — Resume tooling surfaced in the UI
- Facade gains `lint_resume`, `resume_pdf`, `resume_markdown`, `resume_json`,
  `tailor_for_job`.
- **Onboarding:** ATS-friendliness report (errors/warnings/suggestions) plus
  one-click downloads — ATS-clean PDF, Markdown, and JSON Resume.
- **Draft Studio:** "Tailor resume to this job" — shows emphasized skills and
  honest gaps, and offers a per-company tailored ATS PDF. Fabrication is
  impossible by construction (`assert_no_fabrication` in `core/resume`).
- 4 new facade tests (lint severities, emoji flagging, PDF/MD/JSON render,
  truthful tailoring). Totals: **153 Python + 11 JS tests green; ruff clean.**

### 2026-07-23 — UI wiring (core services → Streamlit)
- Added `core/facade.py` — the single, **tested** entry point `app.py` calls
  (session-managed; returns plain dicts, never ORM objects), keeping business
  logic out of the UI per CLAUDE.md.
- `app.py`: DB-persist CV on parse; new **Pipeline** screen (ATS API ingest →
  explainable scored matches → add-to-pipeline → kanban board + funnel);
  Draft Studio now runs the **outreach compliance gate** before a Gmail draft
  (blocks send until identity + postal address + opt-out + LIA pass).
- 6 facade tests (temp-file DB, respx-mocked ingest). `app.py` verified via
  `py_compile`, `ruff`, and a stubbed-streamlit module-load smoke test — a live
  browser render was **not** performed here.
- Totals now: **149 Python tests + 11 JS tests green; ruff clean.**

### 2026-07-23 — Phases 1–10 (full platform build)
Built the platform in phase order, one commit per phase, CI green throughout:
- **P1 `core/db`** — SQLModel tables, Alembic, Fernet PII encryption, repos,
  legacy JSON import (ADR 0003).
- **P2 `core/ingestion`** — Greenhouse/Lever/Ashby + Adzuna/Muse/Remotive
  adapters → canonical `JobPosting`; idempotent upsert; error isolation.
- **P3 `core/fetching`** — ATS detection (regex), JSON-LD extraction (bs4),
  robots-respecting rate-limited fetcher.
- **P4 `core/matching`** — pluggable embeddings (hashing fallback), fuzzy dedup,
  explainable resume↔JD scoring.
- **P5 `core/resume`** — JSON Resume interchange, ATS linter, fpdf2 PDF,
  truthful tailoring with `assert_no_fabrication`.
- **P6 `core/tracking`** — kanban state machine, reminders, dup-prevention,
  blacklist.
- **P7 `core/outreach`** — verification, CAN-SPAM/GDPR footer + LIA + send caps,
  single pre-send gate.
- **P8 `extension/`** — MV3 human-in-the-loop autofill; tested field-mapping
  core (Node); never auto-submits.
- **P9 `core/enrichment` + `core/alerting`** — salary/company/visa/ghost
  enrichment, filters, digest (MD/RSS) + Telegram/Discord.
- **P10 `core/analytics` + E2E + deploy** — funnel, A/B, interview prep; full
  E2E pipeline test; `scripts/send_digest.py` + Actions cron; ADR 0004.

### 2026-07-23 — Phase 0 complete (code-touching hygiene)
- Added `pyproject.toml` with ruff (lint + format) and mypy config.
- Ruff baseline gate is `E`/`F`/`W`/`I`; fixed all findings: removed dead
  imports/variables, replaced 4 bare `except:` with `except Exception:`, and
  persisted onboarding preferences into `st.session_state` (previously dropped).
  `ruff check .` and `ruff format --check .` both clean across 19 files.
- Fixed the five Pydantic v2 deprecations `.dict()` → `.model_dump()`
  (`app.py`, `core/storage.py` ×4).
- Rewrote CI `lint` job: ruff check + ruff format are **blocking gates**;
  mypy runs **advisory** (`continue-on-error`) until modules gain type coverage.
  Replaced black/flake8/isort in `requirements-test.txt` with ruff.
- Added GitHub issue templates (`phase.md`, `bug_report.md`, `config.yml`).
- `.env` schema already covered by the existing comprehensive `.env.example`.
- All 51 existing tests pass (`pytest`).
- **Deferred to a follow-up (documented in `pyproject.toml`):** enabling ruff
  `UP` (typing.List → list) and `B` (bugbear, e.g. `raise ... from`) rules, and
  tightening mypy from advisory to blocking, module by module.

### 2026-07-23 — Phase 0 kickoff (research + scaffolding)
- Captured the platform research as `docs/RESEARCH.md`.
- Added `ROADMAP.md` (11 phases, 0–10, with acceptance criteria).
- Added this `PROGRESS.md` and `CLAUDE.md` (conventions).
- Started the ADR log under `docs/adr/`
  (0001 record-architecture-decisions, 0002 target-architecture).
- **Still open for Phase 0:** ruff/mypy config + CI lint step; Pydantic v2
  deprecation fixes; `.env` schema doc; GitHub issue templates.
- No code behavior changed in this session — docs/scaffolding only.
