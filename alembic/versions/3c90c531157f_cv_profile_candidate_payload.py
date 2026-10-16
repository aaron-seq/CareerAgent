"""cv_profile.candidate_payload (encrypted application answers)

Revision ID: 3c90c531157f
Revises: cbb284f817e8
Create Date: 2026-10-16 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

import core.db.crypto  # custom column types (EncryptedString)
from alembic import op

revision: str = "3c90c531157f"
down_revision: Union[str, None] = "cbb284f817e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable with no default: existing CVs simply have no answers yet, which
    # the repository reads as "everything unknown".
    with op.batch_alter_table("cv_profile", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "candidate_payload", core.db.crypto.EncryptedString(), nullable=True
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("cv_profile", schema=None) as batch_op:
        batch_op.drop_column("candidate_payload")
