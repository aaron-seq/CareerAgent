# 2. Target architecture and platform guardrails

- Status: Accepted
- Date: 2026-07-23

## Context

CareerAgent today is a Streamlit prototype with a `core/` package, local Ollama
LLMs, DuckDuckGo-based discovery, JSON-file storage, and Gmail draft creation.
The research in `docs/RESEARCH.md` evaluated the free/OSS tooling landscape for
job data, scraping, autofill, resume tooling, outreach, and infrastructure, and
surveyed the legal/ethical constraints (CFAA/hiQ, ToS, CAN-SPAM/GDPR/CASL).

We need a durable statement of the target architecture and the guardrails that
constrain it, so every phase builds toward the same shape rather than drifting.

## Decision

**Target stack (free-tier first, single-dev maintainable):**

- Stay in **Python**. Introduce a **FastAPI** service layer and move business
  logic out of `app.py` into `core/` services. Keep **Streamlit** as the UI
  initially.
- **Postgres** (Supabase or Neon free tier) + **pgvector**, via **SQLModel** +
  **Alembic**, replacing JSON-file storage. SQLite for local dev.
- **Ollama local LLM by default** (PII-safe); cloud free tiers (Gemini/Groq)
  only for non-PII burst work. **Pydantic AI** for structured extraction.
- **Embeddings:** sentence-transformers `all-MiniLM-L6-v2` → pgvector.
- **Job ingestion is API-first:** ATS public APIs (Greenhouse/Lever/Ashby) +
  Adzuna/The Muse/Remotive + JSON-LD (`extruct`), with Jina Reader/Crawl4AI as
  a scraping fallback only.
- **Autofill** ships as a **Manifest V3 browser extension, human-in-the-loop.**

**Guardrails (binding on all phases — see `CLAUDE.md`):**

1. Human-in-the-loop before every submit; no unattended mass-apply.
2. APIs and JSON-LD over scraping; honor `robots.txt`, rate-limit, cache;
   identify via `User-Agent`.
3. No logged-in scraping of social platforms (LinkedIn/Indeed/Glassdoor).
4. Never fabricate candidate data; LLM answers draw only from the real profile.
5. PII encrypted at rest and kept on the local LLM where possible.
6. Outreach is treated as regulated: sender identity + postal address +
   opt-out in every email, suppression-list check before send, per-campaign LIA.

## Consequences

- **Legal/ban risk is minimized** by construction: the highest-risk paths
  (logged-in scraping, unattended apply, unsolicited bulk email) are excluded or
  tightly constrained.
- **Coverage tradeoff:** API-first ingestion misses employers not on a modern
  ATS and sites that block scraping; accepted in exchange for zero-ToS-risk data.
- **Local-first LLM** keeps costs at zero and PII private, at the cost of
  requiring local compute (or a hosted GPU when multi-user).
- **Migration cost:** moving from JSON files to Postgres (Phase 1) is a
  prerequisite for dedup, tracking, and analytics, and must land early.
- Free-tier quotas and legal facts in `docs/RESEARCH.md` **must be re-verified**
  at build time; this ADR records direction, not immutable numbers.

## Notes

This ADR is not legal advice. The hiQ litigation ended with hiQ losing on
contract (ToS) grounds despite prevailing on the CFAA question — site ToS still
binds. Consult counsel before any scraping or bulk outreach at scale.
