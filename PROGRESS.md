# Progress Log

Living status log. Update the top block at the end of every working session.
Full plan in `ROADMAP.md`; conventions in `CLAUDE.md`; research in `docs/RESEARCH.md`.

## Current status
- **Current phase:** Phase 0 — Foundation & hygiene (in progress)
- **Last updated:** 2026-07-23
- **Next action:** Finish Phase 0 — add ruff/mypy config, wire lint into CI,
  fix the five `.dict()` → `.model_dump()` deprecations
  (`app.py:263`, `core/storage.py:41,52,63,74`), and add issue templates.
- **Blockers:** None.

## Log

### 2026-07-23 — Phase 0 kickoff (research + scaffolding)
- Captured the platform research as `docs/RESEARCH.md`.
- Added `ROADMAP.md` (11 phases, 0–10, with acceptance criteria).
- Added this `PROGRESS.md` and `CLAUDE.md` (conventions).
- Started the ADR log under `docs/adr/`
  (0001 record-architecture-decisions, 0002 target-architecture).
- **Still open for Phase 0:** ruff/mypy config + CI lint step; Pydantic v2
  deprecation fixes; `.env` schema doc; GitHub issue templates.
- No code behavior changed in this session — docs/scaffolding only.
