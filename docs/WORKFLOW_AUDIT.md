# Workflow audit and improvements — 2026-10-16

This is the historical workflow baseline. The
[2026-10-19 follow-up](ENGINEERING_REVIEW_2026-10-19.md) records encrypted browser
recovery, real Chromium preference regressions, maintained runtimes, required
type checks, security-fixed frozen graphs and actual local inference.

CareerAgent helps a local user discover jobs, prepare truthful materials,
track applications, and review outreach. The review used the latest main,
existing issues, independent subagent review, synthetic Streamlit journeys,
mocked APIs, and functional Docker checks. It introduced no paid service or
runtime dependency.

## Confirmed issues and resulting behavior

| Priority | Confirmed problem | Result |
|---|---|---|
| High | Switching jobs retained another company's email, letter, or resume; fixed editor keys overwrote new generations. | Per-job workspaces preserve edits, reset editor state on generation, and invalidate generated material on CV change. |
| High | Fresh nonroot Compose startup failed on an automatically created host bind directory. | PR #44 uses a correctly initialized named volume; README documents existing bind upgrades. |
| Medium | Version text such as Node.js 20.11.1+ crashed cover-letter metric validation. | PR #44 uses strict numeric tokens and tests semantic versions plus grouped decimals. |
| Medium | Saved CVs could not be reopened; a disconnected model hid existing profile review and exports. | Explicit local restore, bounded metadata listing, and model gates only on AI actions. |
| Medium | API and manually selected jobs did not reach a coherent pipeline-to-drafting path. | Facade conversion/persistence and Prepare application actions connect the screens. |
| Medium | Streamlit 1.50 retained stale Pipeline controls during immediate navigation, breaking the next interaction in the Python 3.9 journey. | Supported button callbacks select the screen before page rendering; the unchanged regression test passes. |
| Medium | Duplicate-titled and withdrawn applications disappeared from detail selection. | Stable application IDs and withdrawn archive/detail visibility. |
| Medium | Source attribution was dropped in facade serialization (#19). | Per-posting source, attribution, and original link. |
| Medium | SmartRecruiters imported only its first page (#20). | Bounded pagination, duplicate/no-progress guards, partial-result notices, and continuation controls. |
| Medium | PRs skipped Docker; health alone missed app failures. | Shared local/CI commands and functional pre-merge container checks. |
| Medium | Digest channel failures were ignored, incomplete settings silently skipped delivery, and malformed URLs could leak configuration in tracebacks. | Validated settings/limits, safe diagnostics, nonzero failures, no automatic retries. |
| Low | ZIP exports exposed a server path instead of a browser download; preferences reset on navigation. | Download button and retained session preferences. |

## Automation and limits

Reopening an encrypted CV avoids another model call. Deterministic matching
refreshes on profile change; discovery scores new imports when a CV is active.
Application preparation reuses saved job data. None of these actions sends email
or submits an application automatically.

SmartRecruiters defaults to 25 postings per page, 250 unique jobs and 20 list
pages. Explicit adapter options allow at most 100 postings per page, 1,000 jobs
and 100 pages. Known totals, empty pages and repeated IDs stop requests. A
budget notice supplies the next offset; a list-request failure retains the
existing all-or-error behavior. A fetch is bounded, not a complete synchronization
of every arbitrarily large board.

The saved-profile selector lists 20 recent metadata records by default (maximum
100 through the facade), decrypting a profile only when explicitly selected.
This is a local single-user interface; it does not provide hosted user isolation.
Session draft workspaces persist through navigation, not browser-session loss.

## Verification

Final Python 3.11 local checks: **452 Python tests and 18 extension tests passed**; Ruff
lint/format passed. Core line coverage is **92.78% (3,044/3,281)**, above the
previous 92.48%. The functional Docker build/smoke passed on the final source.
Mypy remains advisory: 29 existing errors with Python 3.11 target, down from 32;
it is not a passing type gate. Eight known deprecation/reload warnings remain.

The complete Python 3.9.25 / Streamlit 1.50 run also passes 452 tests, at 92.72%
core coverage. Its 11 warnings include three Google SDK notices that Python 3.9
is past end of life. Python 3.11 is recommended; a supported-runtime transition
is tracked in [#46](https://github.com/aaron-seq/CareerAgent/issues/46). No warnings
were suppressed and existing version compatibility was retained.

The regression suite exercises job switches, editor regeneration, saved-CV
restore, profile changes, disconnected browsing/tailoring, pipeline handoffs,
duplicate/withdrawn applications, source retention, pagination bounds, ZIP
downloads, CLI failures, and token-safe digest diagnostics. External AI, Gmail,
job-board and delivery APIs are mocked in tests.

The Docker smoke uses a unique fresh volume, runs actual Onboarding/Pipeline
screens, writes encrypted CV data and a private generated key, decrypts from a
replacement container, checks the nonroot user, and starts the normal command
with a health request. It creates no published port and cleans only its own
container/volume.

Official GitHub release refs were verified for pinned Actions; source URLs and
review evidence were recorded during the engineering review. The official
SmartRecruiters API confirmed distinct offset pages and totalFound with minimal
public requests. Its documentation hostname was blocked in this environment.

Browser screenshot/accessibility automation, live model inference, OAuth,
actual delivery, and hosted Postgres were not validated. Existing PyPDF2 and
intentional SQLModel reload warnings remain documented in the security audit.
No end-to-end performance improvement is claimed; bounds and avoided repeat
model calls are design properties, not load-test results.

## Remaining work and rollback

See [the security audit](SECURITY_AUDIT.md) and issues #38, #41–#43 for historical
PII, outbound URL boundaries, metadata encryption, and semantic grounding.
The matching-quality, dependency and advisory typing backlogs remain open.
The latest historical scheduled digest failure has not been diagnosed from
remote logs; safe local failure paths are tested, not a repaired live delivery.

Revert the workflow commits to roll back UI/automation changes; there is no new
schema migration or destructive data conversion. Keep database/artifact/key
backups together, and retain any existing Compose bind directory when upgrading.
ADR 0007 records the workflow and validation decisions.
