# 12. Freeze reviewed dependencies and require maintained Python runtimes

- Status: Accepted
- Date: 2026-10-17

## Context

Range-only installs allowed upstream SQLModel changes to break existing code.
A strict current PyPI advisory scan found affected Pillow 11.3.0 and pytest
7.4.3. Fixed releases require newer Python, while 3.9 and 3.10 are past end of
life. An advisory type check allowed real return/JSON-shape defects to persist.

## Decision

- Require Python 3.11+, validate 3.11/3.12/3.13, and retain the 3.11 Docker base.
  Upgrade Pillow to 12.3.0, pytest to 9.0.3 and the compatible asyncio plugin.
  Keep other compatible versions as resolver preferences.
- Generate exact SHA-256 runtime/test graphs per supported CPython minor for
  Linux x86_64. Runtime/test versions agree; CI/Docker/digest require hashes and
  binary wheels. Other platforms resolve manifests and validate their own graph.
- Isolate/hash-lock the PyPA audit tool. Audit resolved test graphs against the
  actual PyPI feed, preserve reports and fail on findings or collection errors.
  Do not use ignored advisory IDs or equate no findings with product safety.
- Run weekly/manual unconstrained upstream compatibility tests separately from
  frozen PR checks. Dependabot monitors manifests and Actions; lock updates
  remain reviewed, not assumed automatic.
- Require full-repository mypy through the shared check command and CI after
  repairing diagnostics with actual payload/text validation and precise types.

## Consequences and rollback

This retires interpreter compatibility, not database/key formats. Back up DB,
artifacts and matching key, install into a fresh maintained environment, retain
data paths and migrate normally. No migration is introduced by this decision.
Seven generated lock files increase review size, but standard pip consumes them
without a new runtime package. Python/OS/container base reproducibility and
security remain outside these package locks. Feed outages visibly fail the audit.

Rollback source/workflow/locks together only after assessing the old vulnerable
graph; prefer a reviewed patched graph. Never restore an affected package merely
to make an obsolete interpreter work, discard saved data or change its key.
