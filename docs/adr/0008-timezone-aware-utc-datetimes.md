# 8. Timezone-aware UTC datetimes

- Status: Accepted (supersedes the [2026-08-27 naive-UTC convention](https://github.com/aaron-seq/CareerAgent/blob/2db88ef8ab15387c2eb9062158250a338cc70e18/PROGRESS.md))
- Date: 2026-10-16
- Issue: [#37](https://github.com/aaron-seq/CareerAgent/issues/37)

## Context

Since 2026-08-27 the codebase stored **naive datetimes holding UTC**:
`core/normalize.utc_now()` stripped the tzinfo, and `to_naive_utc()` coerced
anything arriving aware. That was chosen because SQLite `DATETIME` and the
Postgres `timestamp without time zone` columns cannot hold an offset, so aware
values round-tripped to naive and then raised `TypeError` on comparison.

sqlmodel 0.0.45 changed the column type it infers for `datetime` fields to its
own `UTCDateTime`, which **raises on naive values** on write and returns aware
UTC on read. A fresh install failed 78 of 452 tests, so `requirements.txt` was
capped at `sqlmodel<0.0.45` as a stopgap. The cap freezes us on an old release
and the naive convention fights the library's direction.

## Decision

1. **Aware UTC everywhere.** `utc_now()` returns `datetime.now(timezone.utc)`.
   `ensure_utc(dt)` replaces `to_naive_utc`: naive input is taken to hold UTC
   (`tzinfo` attached, no shift); aware input is converted to UTC.
2. **Own the column type.** Every `datetime` column in `core/db/tables.py`
   declares `sa_type=UTCDateTime`, a small project `TypeDecorator` over
   `DateTime(timezone=True)` whose bind and result processors both call
   `ensure_utc`. sqlmodel honours an explicit `sa_type` ahead of inference on
   every release from 0.0.14 to 0.0.48, so behaviour is **identical on old and
   new sqlmodel**: rows always read back aware UTC, including SQLite rows and
   rows written before this change.
3. **Lenient on naive writes.** Unlike sqlmodel's type, ours does not raise on
   naive input; it applies the same "naive means UTC" rule. The whole codebase
   used that rule until now, so legacy callers and pre-migration rows keep
   working instead of failing at flush time.
4. **Coerce at comparison boundaries that accept outside input.** Public
   arguments that may be naive (`as_of`, `now`) and in-memory row attributes
   not yet round-tripped go through `ensure_utc` before comparison or
   subtraction: `TrackingService.due_followups`/`snooze_followup`, the
   facade's application cards, `SendPolicy`, and the ghost-job age. Ingestion
   (`parse_date`, the persistence assignments in `IngestionService` and the
   JSON-LD save path) normalises board dates to aware UTC at the source.
5. **Migration `3f1c2a9d7e45`** alters the twelve datetime columns to
   `DateTime(timezone=True)`. On Postgres it converts with
   `USING col AT TIME ZONE 'UTC'` so existing naive-UTC values keep their
   instant regardless of the server's session time zone; on SQLite the batch
   rebuild changes only the declared type and leaves stored text untouched.
6. Lift the cap to `sqlmodel>=0.0.14,<1.0.0`; the full suite runs green on
   0.0.14, 0.0.44 and 0.0.48.

## Alternatives considered

- **Keep naive UTC and annotate fields as sqlmodel's `NaiveDatetime`.** Smallest
  diff, but only exists on >=0.0.45, so old installs would break instead; and it
  keeps `timestamp without time zone` on Postgres, where the driver interprets
  aware values in the session time zone.
- **Rely on sqlmodel's inferred `UTCDateTime` and sprinkle `ensure_utc` at every
  comparison.** Works on new sqlmodel only if nothing ever writes a naive value;
  on old sqlmodel reads stay naive, so every comparison site must remember to
  coerce. One column type fixes both ends in one place.
- **Raise on naive writes (sqlmodel's behaviour).** Stricter, but breaks any
  remaining naive producer at runtime rather than at review time. Revisit once
  the codebase has been aware-only for a while.

## Consequences

- `isoformat()` output for persisted datetimes now carries `+00:00` (e.g. the
  saved-CV list in the UI). Sorting by those strings is unaffected because all
  values share the suffix.
- Postgres deployments must run `alembic upgrade head`; the conversion
  rewrites the twelve columns (table rewrite on large tables).
- Domain models in `core/models.py` (`EmailDraft.created_at`,
  `WhatsAppDraft.created_at`) still default to naive local `datetime.now`; they
  are display-only for legacy JSON exports and never persisted to the DB.
- **Rollback:** `alembic downgrade -1` (Postgres converts back with
  `AT TIME ZONE 'UTC'`), revert the commits, and restore the `<0.0.45` cap.
