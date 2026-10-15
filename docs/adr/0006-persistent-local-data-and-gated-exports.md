# 6. Persistent local keys, encrypted artifacts, and gated Gmail exports

- Status: Accepted
- Date: 2026-10-15

## Context

The local-first application used process-lifetime encryption keys for persistent
data and deterministic suppression hashes. Its parallel JSON writers bypassed
database encryption. Gmail compliance existed as a detached preview, while UI
reruns reset approval and the action discarded the compliant body. Quotas were
in-memory counters recreated on each facade call.

## Decision

- Reuse the existing Fernet implementation. An explicit environment key takes
  precedence; otherwise atomically publish a private persistent local key file.
  Encryption and deterministic hashing use the same retained key.
- Store new JSON artifacts in an authenticated, versioned encrypted envelope.
  Support old plaintext reads and explicit repeatable migration. Keep
  user-requested readable exports, with a clear disclosure.
- Put app-triggered Gmail creation behind the existing facade. Recheck the current
  recipient/content and suppression at the action boundary, use the approved
  body, and persist successful export metadata.
- Rebuild the daily quota from persisted Gmail exports. Serialize the final
  check/export/record with SQLite's write transaction or a transaction-scoped
  Postgres advisory lock. Do OAuth before taking that lock. Previewing does not
  consume the quota. The default limits are 25 exports/day and a 30-second gap.
- Keep resume tailoring to reordering unchanged candidate facts. Treat free-prose
  cover-letter checks as conservative heuristics requiring human review.

## Consequences and alternatives

This preserves the existing stack and avoids a new service, queue, settings
framework, or cryptographic format. Persistent keys prevent restart-related data
loss, but must be backed up and retained. Atomic key publication avoids two
processes selecting different local keys during first-run initialization.

The SQLite write lock can briefly delay other writes while Gmail responds; the
transport uses its bounded HTTP timeout. Postgres locking still needs integration
testing. External Gmail creation and the local DB commit are not an exactly-once
distributed transaction; a commit failure after remote success needs reconciliation.
Gmail messages sent manually remain outside these limits, and the app never sends
mail itself.

Existing plaintext artifacts/exports/backups and unencrypted DB metadata are not
magically secured by this change. Legacy migration is explicit, and source rollback
must retain matching keys and compatible data/backups. See `docs/SECURITY_AUDIT.md`.
