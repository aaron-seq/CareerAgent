# Project status and continuation

Last verified: 2026-10-28, Asia/Kolkata. Current cleanup starts at
[`2db88ef`](https://github.com/aaron-seq/CareerAgent/commit/2db88ef8ab15387c2eb9062158250a338cc70e18).
This checkpoint replaces the repeated session log; its complete history remains
in the [immutable prior log](https://github.com/aaron-seq/CareerAgent/blob/2db88ef8ab15387c2eb9062158250a338cc70e18/PROGRESS.md).

## Active delivery

- [Issue #85](https://github.com/aaron-seq/CareerAgent/issues/85): reduce duplicate
  documentation and maintenance files in the runtime image. Branch:
  `refactor/85-repository-cleanup`; draft PR publication and final CI pending.
- [Private maintenance Project](https://github.com/users/aaron-seq/projects/7),
  [milestone 1](https://github.com/aaron-seq/CareerAgent/milestone/1).
  Status is manual: Todo = captured/ready, In Progress = implementation or
  review/retest, Done = accepted and verified. Priority P2; no dates/assignees.
- README owns quickstart; [usage](docs/USAGE.md) owns detailed user workflows;
  [operations](docs/OPERATIONS.md) owns deployment, backups and upgrades;
  [contributing](CONTRIBUTING.md) owns developer checks; [architecture](ARCHITECTURE.md)
  owns the component map; [locks](requirements/locks/README.md) owns dependencies.
- Repeated module trees, setup, generic templates and superseded research/phase
  narration removed. Distinct ADRs, published reviews/validation, font notices,
  migrations, lockfiles and all application behavior retained. Older README
  workflow anchors lead to the replacement guides.
- `.dockerignore` excludes docs/tests/extension/CI and test/audit dependency
  files. Existing Docker smoke now rejects those files in the image and checks
  required fonts, notices, theme, migration config and runtime lock.
- Existing checkout and its untracked audit, credentials, database, personal
  files, environments and other worktrees were preserved. No local output was
  purged. No merge, release, deployment or history rewrite occurred.

## Validation and limits

Baseline at `2db88ef`, agent-run in a secret-free tracked archive on Windows
Python 3.11.9: fresh source-manifest install succeeded; Ruff 0.15.8 lint/format,
mypy 2.4.0 (124 files) and Node 22.18.0 tests (63) passed. Python tests could not
collect: Windows Application Control rejected SQLAlchemy 2.1.6's native module.
The OS policy was not changed. This Windows graph is not a Linux hash-lock result.

Final local checks and Linux CI are pending. Docker's local Linux daemon was
unavailable; starting installed Docker Desktop did not establish a connection.
The image build/smoke and Linux locked Python 3.11-3.13 matrix must pass before
acceptance. No live provider, Gmail/OAuth, employer-form, Postgres, accessibility,
load/recovery deployment or history-wide secret scan was performed in this cleanup.

Selected threat scope: packaging must omit maintenance files and retain runtime
assets/licenses; docs must preserve key/data recovery and personal-data warnings.
The final-review agent executed the actual package assertion block with synthetic
files: clean fixture passed, eight contaminations and seven missing assets failed
as intended. That checks the oracle, not a built image. Docs review found no missing
local links or lost recovery/consent instructions. Agents are delegated system
perspectives, not independent human reviewers; orchestrator verification is pending.

GitHub read-only discovery: private vulnerability reporting is disabled; code
scanning returned no analysis; Dependabot-alert access returned disabled/403.
These are access/configuration observations, not clean scanner results. Existing
security settings were not changed. Do not put new confidential findings in public
issues. See the existing [security audit](docs/SECURITY_AUDIT.md) for known scope.

## Retained work and evidence

- Keep the unused `ollama` SDK candidate until six runtime/test locks and clean
  environments can be revalidated together. No dependency upgrades in this change.
- Dormant variant helpers remain tracked by [#35](https://github.com/aaron-seq/CareerAgent/issues/35);
  public compatibility and database contracts need evidence before removal.
- [#38](https://github.com/aaron-seq/CareerAgent/issues/38),
  [#41](https://github.com/aaron-seq/CareerAgent/issues/41) and
  [#42](https://github.com/aaron-seq/CareerAgent/issues/42) remain owner/security
  prerequisites. This cleanup does not resolve historical exposure or hosted use.
- Product/workflow findings [#65-#75](https://github.com/aaron-seq/CareerAgent/issues?q=is%3Aissue+is%3Aopen),
  [first-use UX #77](https://github.com/aaron-seq/CareerAgent/issues/77) and
  [UI migration #78](https://github.com/aaron-seq/CareerAgent/issues/78) remain separate.
- PR #76 changes overlapping README text and adds a release guide plus extension
  and ADR fixes; do not discard those behavioral fixes when reconciling docs.
  Dependency PRs #79-#84 need their own reviewed lock refresh.
- Published [engineering](docs/ENGINEERING_REVIEW_2026-10-19.md),
  [product](docs/PRODUCT_UX_REVIEW_2026-10-19.md), [CV](docs/CV_VALIDATION.md)
  and [workflow](docs/WORKFLOW_AUDIT.md) results validate only their stated revisions.
  [Roadmap](ROADMAP.md) phases describe implementations, not production acceptance.

## Resume here

1. Verify branch/HEAD, `git status`, issue/PR, Project and milestone state.
2. Inspect the cleanup PR diff and current-head CI; resolve introduced failures.
3. In a fresh supported environment install the matching graph and run
   `python -m scripts.check`, then `python -m scripts.check docker`.
4. Reconcile PR #76's docs with the canonical guides; preserve its extension/ADR
   changes. Keep unresolved validation and product/security work linked above.
5. Keep the issue/milestone open until acceptance; merging/deployment need their
   own authorization. Revert cleanup commits to roll back; no data migration.
