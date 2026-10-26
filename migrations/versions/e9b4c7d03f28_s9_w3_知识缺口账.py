"""s9_w3_知识缺口账

Revision ID: e9b4c7d03f28
Revises: c7d3f9a1e204
Create Date: 2026-10-11

第 23 张表 knowledge_gaps：用户问了、讲义答不上（或只擦边）的问题账。
施工图 W3——闸线（REL_THRESHOLD=0.30，能不能喂教练）与登记线
（GAP_WEAK=0.60，要不要进待补账）两线两职，同币种向量余弦；
top_score 为 NULL 即 zero（向量零分/零命中），有分低于线即 weak。

手写 op.execute（施工图画押）：干净库可整链重放，IF NOT EXISTS 全副；
索引与 models.py __table_args__ 同步登记（S4 血案家法——手写索引
不落户，autogenerate 就把当孤儿猎杀）。
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'e9b4c7d03f28'
down_revision: Union[str, Sequence[str], None] = 'c7d3f9a1e204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_gaps (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            top_score DOUBLE PRECISION,
            channel VARCHAR(16) NOT NULL DEFAULT 'web',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_gaps_user_created "
               "ON knowledge_gaps (user_id, created_at)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_knowledge_gaps_user_created")
    op.execute("DROP TABLE IF EXISTS knowledge_gaps")
