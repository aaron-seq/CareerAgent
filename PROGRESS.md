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
