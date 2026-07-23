# 4. Deployment and scheduling

- Status: Accepted
- Date: 2026-07-23

## Context

CareerAgent needs (a) a place to run the Streamlit UI + `core/` services and
(b) a way to run periodic work (ingestion, digests) cheaply. PII-heavy tasks
should stay on a local LLM (Ollama), which needs local compute.

## Decision

- **UI + services:** deploy on **Hugging Face Spaces** (native Streamlit
  hosting, free) or self-host. Self-hosting is required when using Ollama for
  PII-safe local inference.
- **Database:** managed **Postgres** free tier (Supabase/Neon) via
  `DATABASE_URL`; SQLite for local dev (ADR 0003).
- **Scheduling:** **GitHub Actions cron** for periodic, network-only work — the
  daily digest (`.github/workflows/digest.yml` → `scripts/send_digest.py`). It
  dry-runs when no delivery secret is set, so it's safe by default.
- **Secrets:** provided as GitHub Actions / platform secrets
  (`CAREERAGENT_ENCRYPTION_KEY`, `DATABASE_URL`, delivery tokens); never
  committed.

## Consequences

- Zero-cost baseline: HF Spaces + free Postgres + Actions cron.
- Ollama-based PII tasks require self-hosting or a hosted GPU; the cloud LLM
  free tiers (Gemini/Groq) are the fallback for non-PII scale work.
- The digest workflow is inert until secrets are configured, so enabling the
  repo's Actions can't accidentally send anything.

## Not performed here

Actual deployment (provisioning a Space, a Postgres instance, or configuring
Actions secrets) was **not** carried out in this environment. The config and
scripts are provided and dry-run-tested; going live is an operator step.
