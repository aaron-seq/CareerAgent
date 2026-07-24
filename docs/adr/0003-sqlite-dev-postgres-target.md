# 3. SQLite for dev/CI, Postgres as the deployment target; vectors in JSON

- Status: Accepted
- Date: 2026-07-23

## Context

ADR 0002 set Postgres + pgvector as the target data layer. In practice the
development/CI environment cannot run pgvector (the extension isn't installable
here), and requiring a live Postgres for every test run adds friction and
flakiness. We still want the schema, migrations, and repository code to be the
real thing, exercised on every test run.

## Decision

- Use **SQLAlchemy/SQLModel** with a URL selected by `DATABASE_URL`.
- Default to **SQLite** (a local file for dev, in-memory per test). Keep the
  schema Postgres-compatible (no SQLite-only features; JSON via the portable
  `sqlalchemy.JSON` type).
- **Postgres is the deployment target** (`postgresql+psycopg://…`); Alembic
  migrations run against it unchanged (`render_as_batch=True` keeps SQLite
  ALTERs working too).
- Store **embeddings as JSON** and do similarity search **in-process with
  NumPy** behind a `VectorStore` interface. `pgvector` is the documented
  production swap: replace the JSON column with a `vector` column and push the
  cosine search into SQL, keeping the same interface.
- Encrypt PII columns at rest with Fernet via an `EncryptedString`
  `TypeDecorator`; use a keyed HMAC (`deterministic_hash`) for values that must
  be looked up (suppression list, dedup).

## Consequences

- Zero-setup, fast, deterministic tests; the same ORM/migration code path runs
  in dev and prod.
- In-process vector search is fine at single-user / thousands-of-rows scale but
  will not scale like pgvector; the `VectorStore` seam makes the swap local.
- Encrypted columns cannot be filtered on in SQL (non-deterministic ciphertext);
  that is by design — lookups use the HMAC or a non-PII key.
- A small compatibility tax: we avoid backend-specific SQL and must keep the
  JSON/`vector` seam honest.
