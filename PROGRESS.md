# Progress Log

Living status log. Update the top block at the end of every working session.
Full plan in `ROADMAP.md`; conventions in `CLAUDE.md`; research in `docs/RESEARCH.md`.

## Current status
- **Current phase:** Phase 0 — Foundation & hygiene (**complete**)
- **Last updated:** 2026-07-23
- **Next action:** Begin Phase 1 — Data layer (Postgres + SQLModel + Alembic;
  migrate models off JSON; PII encryption for resume fields).
- **Blockers:** None.

## Log

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
