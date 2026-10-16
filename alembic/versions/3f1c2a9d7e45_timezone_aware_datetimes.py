"""datetime columns become timezone-aware (timestamptz on Postgres)

Revision ID: 3f1c2a9d7e45
Revises: cbb284f817e8
Create Date: 2026-10-16 00:00:00

ADR 0008. Existing values were always written as naive UTC, so the Postgres
conversion reinterprets them explicitly ``AT TIME ZONE 'UTC'`` rather than in
the server session's time zone. On SQLite ``DATETIME`` has no offset either
way; the batch rebuild only records the new declared type, and stored values
are untouched (``core.db.tables.UTCDateTime`` attaches UTC on read).
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "3f1c2a9d7e45"
down_revision: Union[str, None] = "cbb284f817e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, nullable)
_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("company", "created_at", False),
    ("job_posting", "date_posted", True),
    ("job_posting", "fetched_at", False),
    ("cv_profile", "created_at", False),
    ("contact", "created_at", False),
    ("email_draft", "sent_at", True),
    ("email_draft", "created_at", False),
    ("application", "applied_at", True),
    ("application", "next_follow_up_at", True),
    ("application", "created_at", False),
    ("application", "updated_at", False),
    ("suppression", "created_at", False),
)


def _alter(to_aware: bool) -> None:
    old = sa.DateTime(timezone=not to_aware)
    new = sa.DateTime(timezone=to_aware)
    tables: dict[str, list[tuple[str, bool]]] = {}
    for table, column, nullable in _COLUMNS:
        tables.setdefault(table, []).append((column, nullable))
    for table, columns in tables.items():
        with op.batch_alter_table(table, schema=None) as batch_op:
            for column, nullable in columns:
                batch_op.alter_column(
                    column,
                    existing_type=old,
                    type_=new,
                    existing_nullable=nullable,
                    # Ignored outside Postgres. naive -> aware: read the stored
                    # wall-clock as UTC; aware -> naive: render the instant in UTC.
                    postgresql_using=f"{column} AT TIME ZONE 'UTC'",
                )


def upgrade() -> None:
    _alter(to_aware=True)


def downgrade() -> None:
    _alter(to_aware=False)
