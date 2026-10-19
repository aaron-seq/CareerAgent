# ADR 0013: Review saved application answers before autofill

Date: 2026-10-19

Status: Accepted

## Context

CareerAgent helps one local user prepare truthful applications with a human
review before submission. Candidate answers already had encrypted persistence
and an extension contract, but the UI exported identity only. Manual contacts
were incorrectly labeled verified, guessed employer domains came from ATS URLs
or company names, and optional AI looked like a broken prerequisite.

Independent Chromium testing also demonstrated that conditional CV entry
controls lost unsaved edits. Streamlit AppTest alone did not reproduce that
widget cleanup behavior. The existing framework and storage support a bounded
repair without a new frontend, service, dependency or database migration.

## Decision

- Use native build/import tabs, saved-CV selection above them, one sidebar
  navigation and collapsed optional AI settings. Keep route identifiers stable.
- Preserve unsaved CV-builder facts in a narrow session-memory dictionary.
  Deliberately saving/activating another CV starts its editor from that profile.
  Refresh recovery continues to include only previously committed choices.
- Edit optional application answers against the exact saved CV row. Keep
  pending edits separately in session memory; validate and encrypt only on
  explicit Save. A new CV snapshot starts with unknown application answers.
- Unknown eligibility and relocation remain distinct from explicit False;
  zero pay/notice remains a supplied value. Country is explicit and never
  inferred. Preserve saved fields that the editor does not expose.
- Downloads read the persisted answers, show the exact values and signal
  pending edits. Voluntary demographics require the saved sharing choice.
  Revoking that choice excludes them from subsequent exports.
- Export target pay when supplied, otherwise the saved minimum. Include
  currency/period and preserve supported decimal precision. Reject textual
  amounts that the existing float schema would alter. Do not convert pay.
- Optional embedded PDF failure leaves identity/answers-only JSON available.
  Use the active CV, with the existing 2 MB extension limit. Readable exports
  are deliberate; no app endpoint or new extension permissions are needed.
- Validate application links before rendering them. Opening a posting or
  downloading materials does not mark it applied. Existing tracking controls
  record the user's status separately.
- Autofill abstains on conflicting or unsupported salary units/currencies and
  numeric-only fields. Skip hidden non-file controls; retain intentionally
  hidden resume upload inputs. Never submit a form.
- Validate manual contacts locally without DNS; show provenance rather than
  independent verification. Require an explicit employer email domain for
  unverified patterns. Existing delivery/compliance gates still apply.

## Alternatives and consequences

A new frontend or multi-step wizard adds state and dependencies without fixing
these specific trust and lifecycle bugs. Mutually mounted radio entry paths
were tried and rejected after actual browser data loss. Native tabs keep both
entry widgets mounted; session callbacks cover sidebar navigation.

Unsaved drafts live only in the browser's Streamlit session. They are not a
backup, and refreshing may discard them. Application drafts are scoped by CV
row; exports intentionally exclude them until Save. This adds no cross-tab
synchronization or multi-user isolation. Eligibility supports one saved country;
unfamiliar wording/countries remain manual. Existing hidden reference preferences
do not change job matching. Local CV readiness remains a content checklist,
not a commercial ATS score or prediction.

## Validation and rollback

Meaningful core/extension contracts and Streamlit tests cover unknown/False/zero,
invalid input, failed persistence, row switches, sensitive sharing and fallback
downloads. Independent real Chromium covers widget lifecycle, actual DOM/file
autofill, mobile layout and representative keyboard navigation. See the
[product review](../PRODUCT_UX_REVIEW_2026-10-19.md) for evidence and limits.

Revert the coherent UI/core/extension change together while keeping the original
database, artifacts and encryption key. There is no migration to reverse.
The new neutral `Any` search-seniority preference extends the recovery schema;
older code may reject a workspace using it, but must preserve that ciphertext
for recovery after upgrading again. Do not delete saved data to work around it.
