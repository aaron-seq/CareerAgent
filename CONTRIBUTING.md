# Contributing to CareerAgent

## Development setup

Follow the [quickstart](README.md#getting-started) in a virtual environment.
Use Python 3.11-3.13 and Node.js for extension tests. Install the matching test
lock on Linux x86_64; other platforms resolve `requirements-test.txt` and
validate their own graph. [Dependency instructions](requirements/locks/README.md)
cover lock refresh and advisory scans. Ordinary tests need no model or API key.
Copy `.env.example` to `.env` only when configuring optional integrations.

## Changes and checks

Link an existing issue or open one describing the problem and acceptance
criteria. Use a dedicated `feature/`, `fix/`, `docs/`, `refactor/` or `test/`
branch; keep unrelated work separate. Follow [repository conventions](CLAUDE.md)
and the [component contracts](ARCHITECTURE.md).

```bash
python -m scripts.check             # lint, format, mypy, Python coverage, Node
python -m scripts.check lint test   # selected checks while developing
python -m scripts.check docker      # build, actual screens, persistence, health
```

The full default command is required before submitting a change. CI exercises
Linux Python 3.11-3.13 and Docker; a local result covers its actual environment.
For a trusted TLS proxy, Docker accepts
`--docker-ca-bundle /path/to/trusted.pem`; keep certificate verification on.

Add meaningful pytest regression tests in `tests/test_*.py` for changed
behavior. Mock external APIs, including Ollama, job boards and Gmail. The
extension has separate tests in `extension/test/`, run with `node --test`
from `extension/`. Do not weaken assertions or skip checks to get a green run.

Exercise affected screens with synthetic data. For parsing/export changes,
check real PDF hyperlinks, selectable text and grounded claims. For workflow
changes, check navigation, refresh, per-CV/job state and failed writes. For
provider changes, state whether the boundary was mocked or actually exercised.
Do not send messages or submit employer applications as routine verification.

## Code and privacy

Ruff formats Python to 88 columns; mypy checks all repository Python files.
Keep functions focused, document public contracts and use Pydantic v2 models.
Put business rules in `core/` services rather than new UI paths. Log actionable
failures without model responses, CV content or credentials. Preserve theme,
offline-font, encryption and human-review rules in [CLAUDE.md](CLAUDE.md).

Do not commit local data, credentials, keys or raw sensitive logs. Review
explicitly selected paths with `git diff --cached` before committing; avoid
staging an entire workspace blindly. Preserve licenses, migrations and useful
validation evidence.

## Pull requests

Use conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`,
`chore:`). Explain the concrete problem and resulting behavior in the PR;
include the issue, actual checks and environment, unrun checks, compatibility
and rollback where material. Add screenshots for visible changes. Distinguish
self/agent review from independent human review.

Update the relevant canonical guide and [current checkpoint](PROGRESS.md).
Add an [ADR](docs/adr/) only for a consequential architectural decision.
Keep acceptance and external-integration gaps explicit. Be respectful and
constructive in issues and reviews.
