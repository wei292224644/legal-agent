"""suggestion 表字段调整：kind→status,加 source/confirmed_at/error,request_id 可空

Revision ID: a5f7181a7fc3
Revises: 6e6f3cb65b5e
Create Date: 2026-05-30 22:54:11.809425

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a5f7181a7fc3'
down_revision: Union[str, Sequence[str], None] = '6e6f3cb65b5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) kind → status（重命名列，保留原有数据：pending/ready）
    op.alter_column('suggestions', 'kind', new_column_name='status',
                    existing_type=sa.String(), existing_nullable=False)

    # 2) request_id 可空（direct 洞察无 request_id）
    op.alter_column('suggestions', 'request_id',
                    existing_type=sa.String(), nullable=True)

    # 3) 新字段
    op.add_column('suggestions',
                  sa.Column('source', sa.String(), nullable=False,
                            server_default='gated'))
    op.add_column('suggestions',
                  sa.Column('confirmed_at', sa.DateTime(timezone=True),
                            nullable=True))
    op.add_column('suggestions',
                  sa.Column('error', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('suggestions', 'error')
    op.drop_column('suggestions', 'confirmed_at')
    op.drop_column('suggestions', 'source')
    op.alter_column('suggestions', 'request_id',
                    existing_type=sa.String(), nullable=False)
    op.alter_column('suggestions', 'status', new_column_name='kind',
                    existing_type=sa.String(), existing_nullable=False)
