# Progress Log

Living status log. Update the top block at the end of every working session.
Full plan in `ROADMAP.md`; conventions in `CLAUDE.md`; research in `docs/RESEARCH.md`.

## Current status
- **Current phase:** Phases 0–10 **complete**.
- **Last updated:** 2026-07-23
- **Next action:** Manual QA of the not-live-verified paths (live API pulls,
  real LLM output, extension in a browser, real email send, deployment), then
  wire the new `core/` services into `app.py` screens incrementally.
- **Blockers:** None. Build env can't reach external services (job APIs / model
  hub / Ollama) or install pgvector; see per-phase notes below and ADRs 0003/0004.

## Verification level per phase
- **Genuinely run + tested here:** P1 data layer, P4 dedup/scoring, P5 resume
  tooling, P6 tracking, P7 outreach gate logic, P9 enrichment/digest, P10
  analytics, and the full internal E2E (`tests/test_e2e_pipeline.py`).
- **Built + unit-tested, external boundary mocked:** P2 ingestion adapters
  (respx), P3 JSON-LD/polite fetcher (respx), P7 email verification (stub
  resolver), P9 Telegram/Discord emitters (respx).
- **Built + unit-tested, NOT live-verified:** P8 extension in a real browser,
  real email delivery, and deployment (dry-run only).

Totals: **143 Python tests + 11 JS tests green; `ruff` + `ruff format` clean.**

## Log

### 2026-07-25 — Structured candidate profile (Wellfound-style capture)
Researched how candidate-profile platforms capture applicants and applied the
core lesson: **you build a structured profile, not upload a document**, with
work authorization, compensation, and preferences as first-class fields.
- **`core/candidate.py`** — `CandidateProfile` wraps the parsed CV and adds
  work authorization, compensation, availability, job preferences, and
  optional EEO. Every field is tri-state/optional.
- **Completeness meter** — weighted checklist where each gap explains what it
  costs ("work authorization: the most common blocking question"). Weights
  reflect how often a field blocks a submission, so work auth outranks a
  portfolio link. Drives a "next best action" nudge in the UI.
- **Autofill can now answer questions, not just fill text.** `build_answers()`
  derives work-authorized / requires-sponsorship / salary / notice period /
  relocation; the extension gained `<select>`, radio-group, and `<textarea>`
  handling to actually answer them.
- **Onboarding redesigned** into tabs (Basics / Work eligibility / Preferences
  / Compensation / Optional EEO) with the completeness meter alongside.
- **Two safety properties, both tested:** an unanswered question is *absent*
  from the payload rather than a guessed "No", and demographics are only ever
  shared with explicit opt-in.
- Storage: new encrypted `candidate_payload` column (migration `a27f58a5e51c`,
  up/down verified); legacy CV-only rows upgrade transparently.
- 14 Python + 10 JS new tests. Totals: **221 Python + 27 JS green; ruff clean.**


### 2026-07-25 — Apply flow: job link -> autofilled application form
Closed the gap between the tracked jobs and the browser extension. Previously
the extension needed its profile typed in by hand and knew nothing about the
pipeline.
- **`core/apply.py`** — `resolve_apply_url()` classifies a posting URL
  (supported ATS / recognized-but-unsupported / unknown) so the UI sets honest
  expectations; `build_autofill_profile()` derives the extension profile from
  the **parsed CV** and embeds the ATS-clean resume PDF for the file input.
  Fields the CV lacks stay empty — nothing invented onto a real application.
- **App** — Onboarding gains **Export autofill profile**; every Pipeline job
  card gains **Apply** (opens the real form) and **I applied** (creates and
  advances the tracked application, starting the follow-up reminder).
- **Extension** — imports that JSON instead of manual entry; auto-fills on load
  when it detects a real application form (>= 2 mappable fields, so it won't
  fire on a search box); attaches the resume via `DataTransfer`; shows a banner
  saying what was filled. Manifest broadened to the EU Greenhouse/Lever hosts
  and `all_frames` for embedded forms.
- **Still never submits.** The banner and popup both say so, and
  `meta.never_submits` is carried in the profile itself.
- 16 Python + 6 JS new tests. Totals: **207 Python + 17 JS green; ruff clean.**

Not verified here: a real browser filling a live ATS form (no browser/DOM in
this environment). That remains the one manual QA step.


### 2026-07-25 — Keyless live job sources + a live verifier
Added four job boards that need **no API key and no account**, so the app
returns real listings out of the box:

| Source | Endpoint | Notes |
|---|---|---|
| Arbeitnow | `www.arbeitnow.com/api/job-board-api` | EU + remote; `visa_sponsorship` flag |
| Himalayas | `himalayas.app/jobs/api` | Remote-only; provider caps limit at 20 |
| Jobicy | `jobicy.com/api/v2/remote-jobs` | Remote-only; annual salary fields |
| RemoteOK | `remoteok.com/api` | **Attribution legally required** |

- Keyword filtering is mapped per provider in the facade (`what` / `category` /
  `industry`), and silently dropped for boards that have no keyword filter
  rather than sent as a junk parameter.
- RemoteOK's first array element is a legal notice, not a job — skipped.
- `scripts/verify_sources.py` probes every source live, runs the real payload
  through our parser, and reports which work (plus salary/date coverage).
  Exits non-zero so it can gate CI on a connected runner.

**Response shapes come from each provider's documentation, not a live call** —
this environment's egress is blocked (only PyPI and api.github.com resolve;
every job API returns 403). `verify_sources.py` is how that gets confirmed on a
connected machine. Parsing is defensive: unexpected/missing fields degrade to
`None` instead of raising.

11 new tests. Totals: **191 Python + 11 JS green; ruff clean.**

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
