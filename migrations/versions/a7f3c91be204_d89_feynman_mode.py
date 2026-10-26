"""d89 feynman_mode

Revision ID: a7f3c91be204
Revises: d4081d7a6809
Create Date: 2026-10-18 15:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7f3c91be204'
down_revision: Union[str, Sequence[str], None] = 'd4081d7a6809'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # D89 费曼意愿闸：nullable Boolean，NULL=从没动过=开（默认档活在代码，
    # 不冻进 DDL——D81 家法同款），False=用户关档。
    op.add_column('agent_settings', sa.Column('feynman_mode', sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('agent_settings', 'feynman_mode')
