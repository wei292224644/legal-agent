"""add lawyer_embedding to sessions

Revision ID: 98ce04ea5890
Revises: a5f7181a7fc3
Create Date: 2026-05-31 17:25:26.665570

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '98ce04ea5890'
down_revision: Union[str, Sequence[str], None] = 'a5f7181a7fc3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("lawyer_embedding", sa.dialects.postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "lawyer_embedding")
