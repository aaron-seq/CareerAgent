# 9. Candidate answers beside the CV, one autofill import contract

- Status: Accepted
- Date: 2026-10-16

## Context

Autofill stalled on the questions a CV cannot answer: work authorization,
sponsorship, salary, notice period, and EEO questions. An unmerged branch
(`claude/ui-integration-followup`, commits 2407332/74ad10c) added a structured
candidate profile and an apply flow, but against an older main. It embedded the
whole CV inside a second encrypted payload and introduced a second extension
export format beside `facade.extension_profile`.

## Decision

- Store a `CandidateProfile` (answers only, no CV copy) in a nullable encrypted
  `cv_profile.candidate_payload` column (migration `3c90c531157f`). The CV row
  remains the single source of truth for history; answers belong to that row.
- Every answer is tri-state. `None` means unknown and is never exported, so the
  extension leaves the question blank and outlines it for the human.
- Demographic answers are exported only when the candidate opted in; the export
  then carries `share_demographics: true`, and the extension re-checks it.
- Extend `facade.extension_profile` with optional `answers` and `resume` blocks
  instead of adding a second format. The popup whitelists every key and type.
  One checked-in fixture (`extension/test/fixtures/candidate_profile.json`) is
  asserted by both the Python and Node test suites.
- `apply_target` reports autofill support only for the content-script hosts in
  `extension/manifest.json`; a test keeps the two lists equal.
- The extension stays user-triggered and never submits. Auto-fill-on-page-load
  and broader host permissions from the old branch were not adopted.

## Consequences and rollback

One additive, nullable column; existing CVs read as "no answers yet". Saving a
newly parsed CV creates a new row, so the UI must copy answers forward
explicitly when it replaces a CV. Embedded resumes are capped at 2 MB to stay
within `chrome.storage.local`. Roll back with `alembic downgrade cbb284f817e8`
(drops only the answers column) and revert the feature commits; the seven-key
export without a candidate profile is unchanged, so older extension builds keep
working.


Review hardening: eligibility exports carry `work_authorization_country` as
context, never inferred from location. Browser answers require an explicitly
matching country and a supported positive question grammar; unknown country,
negation and compound wording abstain for human review. The country metadata
survives popup import/edit but does not count as an answered question. Selects
are filled only on an explicit non-answer placeholder or no selection, so a
candidate's first-option answer is preserved.
