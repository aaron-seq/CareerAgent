# 11. Recover deliberate local choices without serializing session authority

- Status: Accepted
- Date: 2026-10-17

## Context

Browser refresh lost selected jobs, contacts, preferences and active CV despite
saved jobs/CVs remaining in the database (#48). Serializing the entire Streamlit
session would retain clients, credentials, generated drafts or authority to act.
Fingerprint-only job references could replace pasted facts with a similar API
posting. Reading preference widgets only inside Onboarding also lost edits when
navigation coalesced with their change event.

## Decision

- Store a bounded, versioned, encrypted `workspace.json` under existing local
  storage, with atomic replacement and private permissions. Allow only a CV row
  ID, exact selected job IDs, contacts, narrow preferences and last page.
- Source jobs/CVs stay in the database. Preserve exact row identity at selection
  and restoration; legacy in-session fallback requires equal visible facts.
- Restore once per fresh session with no model, network or implicit scoring.
  Warn to re-score global discovery matches after CV restoration because those
  records have no profile provenance. Do not restore clients, credentials,
  unsent drafts, compliance approvals or arbitrary session keys.
- Persist only changed choices. Preference callbacks synchronize stable widget
  keys before navigation can interrupt page rendering.
- Unreadable/wrong-key state blocks replacement and shows recovery guidance.
  An explicit reset retains the old ciphertext in a private backup before
  starting a new snapshot. Saved source jobs/CVs remain untouched.

## Consequences and rollback

No schema migration, model download or runtime dependency. Bounds are 200 job
references, 200 contact companies/500 total contacts, 50 roles/locations, and
2 MiB ciphertext. Explicit readable ZIP exports include workspace data.
This supports one trusted local user; concurrent tabs use last successful save,
not conflict-aware synchronization. Filesystem atomic replacement is not a
power-loss durability guarantee. Revert recovery code to return to session-only
choices; retain encrypted snapshot/backups and their key for later recovery.
