# CLAUDE.md - Conventions and working agreement

Guidance for agents and contributors. CareerAgent is a local-first career
workspace with optional AI assistance and human-reviewed applications.
Read [current status](PROGRESS.md), [roadmap](ROADMAP.md),
[architecture](ARCHITECTURE.md) and [contributing](CONTRIBUTING.md) as needed.
[Research](docs/RESEARCH.md) is historical evidence, not a current specification.

## Coding and validation

- Stay in Python; support the Python 3.11 floor (CI covers 3.11-3.13).
  Follow existing services before adding frameworks or abstractions.
- Use Pydantic v2 `.model_dump()` / `.model_validate()` rather than deprecated
  `.dict()` / `.parse_obj()`. Use type hints and keep required mypy clean.
- Put business logic in `core/` services. The UI still has direct legacy
  calls; that is existing debt, not a pattern for new rules.
- Use Ruff for lint and formatting and conventional commits. Keep one
  cohesive feature branch per phase where practical.
- Keep dark-native `assets/style.css` consistent with `.streamlit/config.toml`;
  check contrast whenever either changes. Use OS-resident UI type and bundled
  PDF fonts; no webfont CDN.
- Every new module ships with meaningful tests. Mock application integrations,
  including Ollama and job boards. Dependency-advisory jobs intentionally
  contact advisory feeds without candidate data.
- Run `python -m scripts.check`; Docker is `python -m scripts.check docker`.
  [Contributing](CONTRIBUTING.md) owns developer setup/check instructions;
  [dependency locks](requirements/locks/README.md) owns graph generation,
  platform scope and scanner commands. Extension tests are separate from
  Python checks and require Node.js.
- Prefer free tools where they meet the need; verify current quotas before
  relying on a provider's free tier. Future stack ideas in the roadmap are
  not instructions to add dependencies during unrelated work.

## Secrets and personal data

- Never commit secrets or personal artifacts. Read configuration from the
  environment; `.env.example` defines supported settings.
- Preserve encryption of resume/contact/draft payloads and private key/token
  storage. Do not imply all metadata is encrypted; see the
  [security audit](docs/SECURITY_AUDIT.md).
- Keep PII-heavy inference local by default. Cloud use requires the user's
  explicit per-session choice with the data trade-off surfaced at that point
  ([ADR 0005](docs/adr/0005-cloud-llm-provider-for-pii-work.md)). Prefer non-PII
  work for cloud scale tasks.
- Preserve matching keys and data together; follow
  [operations and recovery](docs/OPERATIONS.md) for upgrades and migration.

## Ethics guardrails

1. Human review before every submit: autofill fills; the person reviews and
   clicks submit. No unattended mass application.
2. Prefer official APIs and JSON-LD. Scrape only as a fallback; honor
   `robots.txt`, rate limits, jitter, caching and an identifying User-Agent.
3. Never scrape logged-in LinkedIn, Indeed, Glassdoor or other social platforms.
4. Never fabricate experience or credentials. Use the person's real profile
   and flag unanswerable questions for human input.
5. Outreach must include sender identification, a physical postal address and
   one-click opt-out; check persistent suppression before every send, document
   a per-campaign LIA and honor opt-outs. The app currently creates Gmail
   drafts, not sent messages; retain its compliance gate and quotas.

## Definition of done

Code and relevant tests pass, canonical docs match behavior, and `PROGRESS.md`
records verified state and the next action. Add an ADR for a significant
decision. Do not claim live integration, deployment or production readiness
from mocked or local-only results.
