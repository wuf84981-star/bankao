"""s9_中文分词全文检索腿

Revision ID: c7d3f9a1e204
Revises: b6a0874cf86c
Create Date: 2026-10-09

加腿，不换腿——search.py 的 RRF 融合骨架不動，本迁移只给 chunks 补一条
能真正命中中文的关键词通道。

背账：pg_trgm 那条腿对中文按 UTF-8 字节剁三元组，「基期量怎么算」对正题
块 similarity 实测被稀释到 0.0275（search.py 注释原账），阈值降到 0.01 才
勉强放行——关键词腿事实上半废。补的办法不是换库（Milvus 砍掉了），是给 PG
装一只能切中文词的索引。

为什么不用 zhparser：它是 C 扩展，pgvector 官方镜像不带，要用得自己编译
镜像——对这套部署是不必要的构建负担。改走「分词在 Python 侧做」：jieba
切词 → 空格连接 → to_tsvector('simple', …)。'simple' 只按空白切词项、
不二次切分，等于把词边界权交给我们，索引照吃。

为什么不用生成列或触发器（三条路逐一验尸）：
① 生成列（GENERATED AS ... STORED）：PG 明令禁止 UPDATE 生成列
   （cannot update a generated column）。而存量回填恰恰是本刀的核心动作
   ——老资料库不重新上传也得立刻能被检索到。故否决。
② PG 侧触发器调 Python：jieba 跑在 backend 箱、库在 db 箱，两箱之间不共享
   解释器；要在 PG 里跑 Python 得装 plpython3（C 扩展插件），官方镜像不带。
   为一列索引去编译镜像不值得。故否决。
③ 最终形态：两列皆普通列，分词在写入端做——与向量点火（ignite.py）同一套路，
   代码侧负责分词，DB 只存结果。本迁移负责存量回填，新块入库由解析侧负责。

回填分两段：先把 content_tokenized 用Python 逐块算好、再按 id 成批 UPDATE
（分批 500条防长事务）。不在 SQL 里 to_tsvector('simple', content)——那会把
整句中文当一个词项，等于白建索引（pg_trgm 同款病）。
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = 'c7d3f9a1e204'
down_revision: Union[str, Sequence[str], None] = 'b6a0874cf86c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 分批回填的批大小：一次 UPDATE 500 行。
# 太大：长事务把行锁按在表上，并发入库被堵；太小：往返次数多。
BATCH = 500


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()

    # 扩展先行铁律（51d6 反序血案同款教训，2026-10-11 真机补钉）：
    # btree_gin 给整列补 GIN 操作族（int4_gin_ops）——复合 GIN (user_id, content_tsv)
    # 里的 user_id 没它就没默认算子，真机首跑正是在这里炸的：
    # "data type integer has no default operator class for access method gin"。
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")

    # ── 两列：分词串本体 + tsvector 投影 ──
    op.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS content_tokenized text")
    op.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS content_tsv tsvector")

    # ── 存量回填：jieba 在本进程跑（分词权在代码侧），逐块算好写回 ──
    # 为什么能在迁移里 import 应用代码：迁移与代码同仓同 venv，backend 包可寻址。
    # 若将来迁移要脱离代码仓库独立重放，这里需改成读环境变量指定的分词服务——
    # 当下不值得复杂化。
    from backend.zh_tokenizer import ts_input

    # 分批游标推进：不用 OFFSET（回填过程中条件会变，OFFSET 会跳行），
    # 一批一批按 id 推进，每批重新取「下一批还没填的最小 id 之后那些」。
    done = 0
    last_id = 0
    while True:
        rows = bind.execute(text(
            "SELECT id, content FROM chunks "
            "WHERE content_tsv IS NULL AND id > :last ORDER BY id LIMIT :n"
        ), {"last": last_id, "n": BATCH}).fetchall()
        if not rows:
            break
        payload = []
        for cid, content in rows:
            tokenized = ts_input(content or "")
            # 分词后为空（全虚词/全停用词）的块留 NULL——GIN 索引不收 NULL，
            # 空词集进索引只占位置不产生命中。这类块靠向量腿与 trgm 腿兜。
            if tokenized:
                payload.append((cid, tokenized))
        if payload:
            # to_tsvector 在 UPDATE 侧算，DB 里只存最终词项集，索引由 GIN 维护。
            # executemany 逐行发：个人库几万块，一次往返换来的可读性与
            # 可诊断性（出错能定位到具体行）值这个成本——批量 SQL 省的那点
            # 时间在离线回填里毫无意义。
            bind.execute(text("""
                UPDATE chunks
                SET content_tokenized = :tok,
                    content_tsv = to_tsvector('simple', :tok)
                WHERE id = :id
            """), [{"id": cid, "tok": tok} for cid, tok in payload])
        last_id = max(r[0] for r in rows)
        done += len(rows)

    total = bind.execute(text("SELECT count(*) FROM chunks")).scalar()

    # ── 索引 ──
    # 两条 GIN（models.py 的 __table_args__ 已登记户口，autogenerate 只维护不猎杀）：
    # 单列供「不限用户的纯全文」与 EXPLAIN 用；复合供检索恒走的
    # user_id 等值 + tsv 匹配路径——单列 GIN 会把 user_id 过滤退化成
    # 过滤后扫描，复合索引让planner 先按用户切开再在该用户块内匹配。
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunks_content_tsv ON chunks USING GIN (content_tsv)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_user_tsv ON chunks "
        "USING GIN (user_id int4_ops, content_tsv)")

    # 统计信息：小表时 planner 常错选两腿顺序，ANALYZE 成本毫秒级。
    op.execute("ANALYZE chunks")
    print(f"[s9] 中文分词腿回填完成：{done}/{total} 块已建tsvector")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_chunks_user_tsv")
    op.execute("DROP INDEX IF EXISTS ix_chunks_content_tsv")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS content_tsv")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS content_tokenized")