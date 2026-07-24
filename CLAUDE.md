# CLAUDE.md — Conventions & Working Agreement

Guidance for Claude Code (and humans) working in this repository. Read this
first. The full plan is in `ROADMAP.md`, current status in `PROGRESS.md`, and
the platform research in `docs/RESEARCH.md`.

## What this project is
CareerAgent is a **local, privacy-first AI career assistant**. Today it drafts
personalized job-outreach emails from your CV using local Ollama LLMs. The
roadmap grows it into an API-first, compliant job-search-and-application
platform (job ingestion, matching, resume tooling, tracking, human-in-the-loop
autofill).

## Architecture snapshot (current)
- **UI:** Streamlit single-file `app.py` (5 screens: Onboarding, Discovery,
  Contacts, Draft Studio, Export).
- **Logic:** `core/` package — `llm.py` (Ollama client), `models.py` (Pydantic
  v2), `validators.py`, `cv_parser.py`, `job_finder.py`, `contact_finder.py`,
  `personalization.py`, `gmail_drafts.py`, `whatsapp.py`, `prompts.py`,
  `storage.py`.
- **LLM:** Ollama local inference (`llama3.1:8b`, `llama3.2:3b`, `qwen2.5:7b`,
  `mistral:7b`).
- **Storage:** local JSON under `careeragent_data/` (to be replaced by Postgres
  in Phase 1).
- **Tests:** `tests/` (pytest); CI in `.github/workflows/ci.yml`.

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
- Keep PII-heavy work (resume parsing/tailoring) on the **local** LLM; reserve
  cloud free tiers for non-PII scale tasks (job extraction, dedup).

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
