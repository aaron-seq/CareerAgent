# CareerAgent Roadmap

The original phases describe the project's history, not a completed checklist
of every proposed tool or live integration. Follow [current status](PROGRESS.md),
[open issues](https://github.com/aaron-seq/CareerAgent/issues) and the
[private cleanup and bug-review Project](https://github.com/users/aaron-seq/projects/8)
for active work. The [original plan and acceptance criteria](https://github.com/aaron-seq/CareerAgent/blob/627a8b34fcdce134a0a922665902b0855c147184/ROADMAP.md)
remain available at an immutable revision.

## Guiding principles

[CLAUDE.md](CLAUDE.md) owns the privacy, human-review, API-first and truthful
candidate-data rules. [Contributing](CONTRIBUTING.md) owns validation and delivery.

## Phases

| Historical phase | Implemented scope / canonical reference |
| --- | --- |
| 0 — Foundation | [Conventions and required checks](CONTRIBUTING.md). |
| 1 — Data layer | SQLModel, Alembic and encrypted payloads; [operations and recovery](docs/OPERATIONS.md). |
| 2–3 — Ingestion and extraction | ATS/aggregator sources, JSON-LD and polite fetching; [component contracts](ARCHITECTURE.md). |
| 4 — Matching | In-process embeddings, deduplication and explainable scoring; [architecture decisions](docs/adr/). |
| 5 — Resume tooling | Structured CVs, truthful tailoring, ATS checks, PDF preview and Overleaf-compatible export; [usage](docs/USAGE.md#build-a-cv-and-improve-its-readiness). |
| 6 — Application tracking | Pipeline states and follow-ups; [usage](docs/USAGE.md#your-first-application). |
| 7 — Outreach | Compliance-gated Gmail drafts; [operational limits](docs/OPERATIONS.md). |
| 8 — Autofill | Human-reviewed browser extension; [contract and verification limits](extension/README.md). |
| 9 — Enrichment and alerts | Dataset-backed signals and digest tooling; [dataset setup](core/enrichment/data/README.md). |
| 10 — Analytics and operations | Funnel/interview tooling and container checks; [architecture](ARCHITECTURE.md) and [operations](docs/OPERATIONS.md). |

## Implementation status (2026-07-23)

This anchor preserves the historical status URL. Current code uses
BeautifulSoup/stdlib JSON for JSON-LD, in-process vectors rather than pgvector,
and fpdf2 for PDF export rather than RenderCV. The base install uses hashing;
the optional sentence-transformers backend is preferred when available.
The original extruct, Jina/Crawl4AI,
reply-detection and LLM autofill proposals are not delivered capabilities.

Live-provider, browser and deployment acceptance must be assessed separately
from mocked tests. See [CV/API evidence](docs/CV_VALIDATION.md),
[browser evidence](docs/PRODUCT_UX_REVIEW_2026-10-19.md),
[security prerequisites](docs/SECURITY_AUDIT.md) and
[autofill gaps #13](https://github.com/aaron-seq/CareerAgent/issues/13).
[A/B variant tracking #35](https://github.com/aaron-seq/CareerAgent/issues/35)
still lacks a producing/consuming workflow. Historical phase checkmarks did
not establish production readiness.

## Definition of done (every phase)

Use the maintained [definition of done](CLAUDE.md#definition-of-done) and
[PR requirements](CONTRIBUTING.md#pull-requests). Record actual checks and
remaining acceptance gaps on the issue/PR; do not infer them from phase labels.
