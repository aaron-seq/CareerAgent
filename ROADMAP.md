# CareerAgent Roadmap

Phased plan to grow CareerAgent from an outreach-drafting prototype into a
full, compliant, API-first job-search-and-application platform. Derived from
`docs/RESEARCH.md`. Each phase is a self-contained, shippable, tested unit of
work. Progress is tracked in `PROGRESS.md`; conventions live in `CLAUDE.md`.

## Guiding principles
- **API-first, scraping as fallback.** Prefer official ATS/aggregator APIs and
  JSON-LD extraction over headless scraping. Never scrape logged-in social
  platforms.
- **Human-in-the-loop before any submit.** Autofill assists; the human reviews
  and clicks submit. No unattended mass-apply.
- **PII stays local and encrypted.** Resume/contact data uses local LLMs by
  default; cloud calls are opt-in and non-PII.
- **Compliance is built in, not bolted on.** Suppression list, opt-out, postal
  address, and per-campaign LIA live in the data model.
- **Free-tier first.** Choose tools with durable free tiers; re-verify quotas at
  build time.

## Phases

Legend: ☐ not started · ◐ in progress · ☑ done

- ☑ **Phase 0 — Foundation & hygiene.** CLAUDE.md, ROADMAP.md, PROGRESS.md, ADR
  folder, issue templates; ruff+mypy+pytest+CI; fix Pydantic v2 deprecations
  (`.dict()` → `.model_dump()`); `.env` schema.
  *AC:* CI green, lint clean, docs present. **Done** — `ruff check`/`ruff format`
  clean, 51 tests passing, ruff is a blocking CI gate (mypy advisory).

- ☐ **Phase 1 — Data layer.** Postgres (Supabase/Neon) + SQLModel + Alembic;
  migrate `CVProfile`, `JobPosting`, `Contact`, `EmailDraft`, `Application` from
  JSON to DB; PII encryption for resume fields.
  *AC:* CRUD + migration tests pass; JSON import path works.

- ☐ **Phase 2 — Real job ingestion (APIs).** Ingestion service:
  Greenhouse/Lever/Ashby public APIs + Adzuna + The Muse + Remotive; normalize
  into canonical `JobPosting`; store with source + fetched-at.
  *AC:* pulls ≥N real jobs from ≥3 sources into DB with mocked-HTTP tests.

- ☐ **Phase 3 — ATS detection + JSON-LD + polite fetcher.** Careers URL → ATS
  detection (regex signatures); `extruct` JSON-LD parser; robots.txt +
  rate-limit + cache; Jina Reader/Crawl4AI fallback.
  *AC:* careers URL returns structured jobs; robots.txt honored; fixture tests.

- ☐ **Phase 4 — Dedup + embeddings + scoring.** Fuzzy dedup
  (title+company+location, canonical URL); sentence-transformers `all-MiniLM-L6-v2`
  → pgvector; resume↔JD cosine + keyword-gap (KeyBERT/RapidFuzz), explainable.
  *AC:* duplicates collapse; each job gets an explainable match score.

- ☐ **Phase 5 — Resume tooling.** LLM parse into JSON Resume schema;
  ATS-friendliness linter; RenderCV (YAML→PDF); truthful tailored variants.
  *AC:* upload → JSON Resume → ATS-clean PDF; tailoring cites only real data.

- ☐ **Phase 6 — Application tracking pipeline.** Kanban states
  (saved→applied→screening→interview→offer/rejected); follow-up reminders;
  duplicate-application prevention; company blacklist.
  *AC:* full lifecycle tracked; reminders fire; no double-apply.

- ☐ **Phase 7 — Outreach engine hardening (compliance).** Reuse personalization
  + validators + Gmail drafts; add email verification (dnspython/email-validator),
  suppression list, per-campaign LIA, postal address + opt-out in every template,
  send caps + jitter, reply detection.
  *AC:* no send without verification + suppression check; enforced by tests.

- ☐ **Phase 8 — Human-in-the-loop autofill extension.** Manifest V3 extension:
  profile in `chrome.storage`, layered field detection
  (autocomplete→ARIA→label→fuzzy→LLM fallback), per-site activation; fills but
  never auto-submits; optimized for Greenhouse/Lever/Ashby.
  *AC:* fills a real Greenhouse form correctly; never auto-submits.

- ☐ **Phase 9 — Enrichment, filters, alerting.** Salary (Adzuna), company
  enrichment (layoffs.fyi, Glassdoor), visa sponsorship filter (USCIS H-1B /
  DOL LCA / UK sponsor register), ghost-job detection, new-grad/intern filter;
  alerting via Telegram/Discord/email digest/RSS (GitHub Actions cron).
  *AC:* jobs annotated with salary/visa/company signals; daily digest delivered.

- ☐ **Phase 10 — Analytics + polish + deploy.** Application→response funnel; A/B
  resume-variant tracking; interview-prep generation from JD; deploy (HF Spaces /
  self-host + scheduled Actions); docs + onboarding.
  *AC:* dashboard renders funnel; deployment reproducible; README updated.

## Definition of done (every phase)
Code + tests green + docs updated + `PROGRESS.md` updated + an ADR in
`docs/adr/` if a significant decision was made.
