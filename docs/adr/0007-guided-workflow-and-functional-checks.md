# 7. Guided local workflow and functional validation

- Status: Accepted
- Date: 2026-10-16

## Context

Persisted API jobs and CVs were disconnected from session-only drafting. Users
had to parse a CV again, and a global draft/editor could retain another job's
content. Model connection gates also blocked deterministic browsing and resume
exports. Docker health checks could pass while the actual app script crashed.

## Decision

- Keep persistence and domain conversion in the existing facade. Explicitly
  restore an encrypted CV and bridge selected/pasted and API jobs into one
  pipeline; re-score when the active profile changes.
- Require an AI connection only for model calls. Local job browsing, tracking,
  resume tailoring, profile review, and exports remain available without it.
- Keep generated material and editor state in per-job session workspaces. A
  profile change invalidates those workspaces. Generation resets its editor
  values; switching jobs preserves that job's edits.
- Preserve source attribution per posting. Paginate SmartRecruiters with
  explicit request/job bounds and report partial results.
- Use a standard-library check command and run functional Docker validation on
  PRs: actual screens, encrypted data continuity, nonroot runtime, and health.
- Keep all application submission and outreach review under human control.

## Consequences and rollback

No runtime dependency, database migration, worker, or new service is required.
Session workspaces are temporary; saved profiles and jobs use existing storage.
Hosted authentication/isolation and remaining security issues are unchanged and
tracked separately. Revert the workflow commit to restore the prior UI/scripts;
retain existing data and its encryption key. CI costs increase by one bounded
Docker job on PRs, closing the earlier post-merge validation gap.
