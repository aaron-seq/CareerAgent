# CLAUDE.md — Conventions & Working Agreement

Guidance for Claude Code (and humans) working in this repository. Read this
first. The full plan is in `ROADMAP.md`, current status in `PROGRESS.md`, and
the platform research in `docs/RESEARCH.md`.

## What this project is
CareerAgent is a **local-first, privacy-first AI career assistant** — an
API-first, compliant job-search-and-application platform: job ingestion and
explainable matching, truthful resume tailoring and cover letters, application
tracking, compliant outreach, and human-in-the-loop autofill. LLM inference
runs against local Ollama by default; a free-tier cloud provider (Groq) is
available as an opt-in alternative (ADR 0005).

## Architecture snapshot (current)
- **UI:** Streamlit single-file `app.py` (6 screens: Onboarding, Job Discovery,
  Pipeline, Contact Finder, Draft Studio, Export & Logs). No business logic
  lives in `app.py` itself. In practice it calls `core/` two ways: the
  DB-backed platform services (ingestion, matching, resume, tracking,
  outreach, analytics) go through `core/facade.py`; the original CV/contact/
  personalization/Gmail/storage modules are instantiated directly by
  `app.py` (`CVParser`, `JobFinder`, `ContactFinder`, `PersonalizationEngine`,
  `DraftValidator`, `GmailDraftClient`, `LocalStorage`) — a repo-audit finding
  (2026-08) worth routing through the facade too, not yet done.
- **Logic:** `core/` package — see `ARCHITECTURE.md` for the full module map
  (ingestion, matching, resume, tracking, outreach, enrichment, analytics,
  db, plus the original CV/contact/personalization/LLM modules).
- **LLM:** Ollama local inference by default (`llama3.1:8b`, `llama3.2:3b`,
  `qwen2.5:7b`, `mistral:7b`); Groq (free-tier cloud, opt-in) as an
  alternative when Ollama isn't installed — see ADR 0005 for the PII tradeoff.
- **Storage:** SQLModel on SQLite for dev (Postgres in prod, ADR 0003); legacy
  JSON under `careeragent_data/` for drafts/exports.
- **Tests:** `tests/` (pytest, 204+); CI in `.github/workflows/ci.yml`.

## Tech stack & direction
- **Language:** Python (target 3.11+). Stay in Python.
- **Target additions (see ROADMAP):** FastAPI service layer, Postgres
  (Supabase/Neon free tier) + `pgvector`, SQLModel + Alembic, Pydantic AI for
  structured extraction, sentence-transformers `all-MiniLM-L6-v2` embeddings.
- **Prefer free tiers.** Choose tools with durable free tiers; re-verify quotas
  against official docs at build time (they change often).

## Coding conventions
- Pydantic v2 idioms — use `.model_dump()` / `.model_validate()`, **not** the
  deprecated `.dict()` / `.parse_obj()`.
- Type hints everywhere; keep `mypy` clean.
- Lint/format with `ruff`; keep it green.
- Business logic lives in `core/` services — **no business logic in the UI
  layer** (`app.py`). Streamlit calls into `core/`.
- Conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`,
  `refactor:`). One feature branch per phase where practical.
- **`assets/style.css` is dark-native and must stay in step with the theme
  in `.streamlit/config.toml`.** These drifted once — the CSS was authored
  for a light theme while config set a dark one, rendering every heading
  near-black on near-black. Change one, check the other.
- No webfont CDN in the UI. Local-first is the product's premise; type is
  built from OS-resident faces so nothing phones home and offline works.

## Testing
- Every new module ships with pytest tests.
- **Mock all external APIs** (`respx`/`vcr.py`/`pytest-mock`) — no live network
  calls in CI. Ollama and job-board APIs must be mocked in tests.
- Run: `pytest`. Lint: `ruff check .`. Types: `mypy .`.

## Secrets & PII
- Never commit secrets. Read config from env (`.env`, already gitignored;
  schema in `.env.example`).
- **Encrypt PII at rest** (resume/contact data) once the DB lands — `pgcrypto`
  or app-level Fernet (`cryptography`).
- Keep PII-heavy work (resume parsing/tailoring) on the **local** LLM by
  default; reserve cloud free tiers for non-PII scale tasks (job extraction,
  dedup). Narrowed by ADR 0005: the user can opt into a cloud provider (Groq)
  for PII-heavy work too, per-session, with the tradeoff surfaced at the
  point of choice — see that ADR before treating "local for PII" as absolute.

## Ethics guardrails (non-negotiable)
1. **Human-in-the-loop before every submit** — autofill fills, the human
   reviews and clicks submit. No unattended mass-apply.
2. **APIs over scraping.** Prefer official ATS/aggregator APIs and JSON-LD
   extraction. Scrape only as a fallback; honor `robots.txt`, rate-limit +
   jitter, cache, and send an identifying `User-Agent`.
3. **Never scrape logged-in social platforms** (LinkedIn/Indeed/Glassdoor) —
   ToS breach + account-ban risk.
4. **Never fabricate** candidate experience/credentials. LLM answers draw only
   from the user's real profile; flag anything unanswerable for human input.
5. **Outreach is regulated.** Include sender identification + physical postal
   address + one-click opt-out in every email; check a persistent suppression
   list before every send; document a per-campaign LIA (GDPR); honor opt-outs.

## Definition of done (every phase)
Code + tests green + docs updated + `PROGRESS.md` updated + an ADR in
`docs/adr/` if a significant decision was made.

## How to run
```bash
ollama serve                 # start local LLM runtime (separate terminal)
pip install -r requirements.txt
streamlit run app.py         # launch the UI
pytest                       # run tests
ruff check .                 # lint
```

## Environment quirks (verified 2026-07-26)
- No repo-local venv. Global interpreter here is Python 3.13.7 — ruff,
  mypy, pytest, and streamlit all ran clean against it directly, but CI
  matrix-tests only 3.9-3.11; don't rely on 3.13-only syntax.
- `pytest` needs `requirements-test.txt` installed, not just
  `requirements.txt` (`sqlmodel` etc. live there). Skipping it fails
  collection at `tests/conftest.py` with `ModuleNotFoundError: sqlmodel`.
  Run `pip install -r requirements.txt -r requirements-test.txt` first.
- `extension/` is a separate Node/Chrome-extension subproject (own
  `package.json`; tests via `node --test`, run from inside `extension/`).
  It's outside the Python package and untouched by root `pytest`/`ruff`/
  `mypy`.
- `mypy .` cannot complete on this machine's global environment as of
  2026-08: `requirements-test.txt` pins `mypy==1.7.1` (Nov 2023), but
  `numpy`'s installed stub file uses PEP 695 `type` statement syntax that
  version can't parse, so the run aborts before checking any project code.
  Low severity in practice — `pyproject.toml` already marks mypy advisory,
  and CI installs an unpinned newer `mypy` with `continue-on-error: true` —
  but the exact `pip install -r requirements-test.txt` + `mypy .` path this
  doc describes for local dev doesn't work as written. Fix is bumping the
  `mypy` pin; not done here since it's a version-pin decision, not a bug.
