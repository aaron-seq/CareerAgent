# Project status and continuation

Last verified: 2026-10-28T21:05:37+05:30 (Asia/Kolkata). Cleanup starts at
[`2db88ef`](https://github.com/aaron-seq/CareerAgent/commit/2db88ef8ab15387c2eb9062158250a338cc70e18).
This checkpoint replaces the repeated session log; its complete history remains
in the [immutable prior log](https://github.com/aaron-seq/CareerAgent/blob/2db88ef8ab15387c2eb9062158250a338cc70e18/PROGRESS.md).

## Active delivery

- [Issue #85](https://github.com/aaron-seq/CareerAgent/issues/85): reduce duplicate
  documentation and maintenance files in the runtime image. Branch:
  `refactor/85-repository-cleanup`; [draft PR #86](https://github.com/aaron-seq/CareerAgent/pull/86) is published, unmerged.
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
  migrations and application source retained. Older README
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

At cleanup commit `4f0bf0d`, [published Linux CI](https://github.com/aaron-seq/CareerAgent/actions/runs/40683501579)
passed lint/type, all 922 Python tests on each of 3.11-3.13, and 63 extension
tests. The unchanged dependency locks failed the live advisory gates; Docker was
skipped because it depends on them. This triggered the bounded [#87 refresh](https://github.com/aaron-seq/CareerAgent/issues/87):
Streamlit 1.66.1, Pillow 13.0.0, pypdf 6.21.3 and certifi 2026.10.19. The unused
Ollama Python SDK was removed from the manifest and six runtime/test locks;
all unrelated pins/hashes remain identical. Scanner-lock certifi was refreshed.

Personally run on the refresh: 10 isolated lock tests passed
(`python -m pytest --noconftest tests/test_dependency_locks.py -q`; these tests
use no DB fixtures). Strict pip-audit 2.10.1 checks of each hashed test graph
returned zero advisory rows (96/95/95 distributions). The initial scan returned
45 feed rows across three packages; duplicates/aliases are not distinct verified
application vulnerabilities. Current-head Linux matrix and Docker results are
recorded in the [PR checks and validation record](https://github.com/aaron-seq/CareerAgent/pull/86).
[CI at `f03fb24`](https://github.com/aaron-seq/CareerAgent/actions/runs/40713225520)
is verified green: 922 Python tests on each supported minor, 63 extension tests,
lint/type and three advisory gates pass. The real Docker smoke passed package
exclusions, runtime assets, screens, encrypted replacement-container persistence
and health. This checkpoint-only follow-up changes no application code or graph;
read the PR for its exact current-head checks. No scan exclusions or CI gates changed.

Docker's local Linux daemon was unavailable; starting installed Docker Desktop
did not establish a connection. Full Windows Python execution remained blocked
by the OS policy; a personally repeated full runner timed out and its pytest
child was stopped. No live provider, Gmail/OAuth, employer-form, Postgres,
accessibility, scale/deployment recovery or history-wide secret scan was run.

Selected threat scope: packaging must omit maintenance files and retain runtime
assets/licenses; docs must preserve key/data recovery and personal-data warnings.
The final-review agent executed the actual package assertion block with synthetic
files: clean fixture passed, eight contaminations and seven missing assets failed
as intended. That checks the oracle, not a built image. Docs review found no missing
local links or lost recovery/consent instructions. Agents are delegated system
perspectives, not independent human reviewers. The orchestrator checked 71 local
links/fragments and repeated the clean/contaminated package assertion scenarios.

GitHub read-only discovery: private vulnerability reporting is disabled; code
scanning returned no analysis; Dependabot-alert access returned disabled/403.
These are access/configuration observations, not clean scanner results. Existing
security settings were not changed. Do not put new confidential findings in public
issues. See the existing [security audit](docs/SECURITY_AUDIT.md) for known scope.

## Retained work and evidence

- SDK removal and four version changes are retested in #87; the unmerged draft
  remains awaiting review. Existing API/CLI behavior stays supported.
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
   own authorization. Roll back docs/packaging if needed while retaining the
   security refresh or a separately reviewed safe graph; no data migration.
