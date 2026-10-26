# ============================================================
# 伴考后端 · 装箱图（Dockerfile）
# 三件事：垫什么底座 / 货怎么装 / 开机跑什么
# 本机 .venv 是 Python 3.12.13，箱内也用 3.12——版本对齐，
# 杜绝"本机跑得通、箱里跑不通"的两张皮。
# ============================================================
FROM python:3.12-slim

WORKDIR /app

# ── 先装依赖层（Cargo 优先原则）──
# 只 COPY 账本（pyproject/uv.lock）：只要依赖没改，下面这层缓存永远命中；
# 改代码不用重装依赖——重构一箱货比重新进货便宜得多。
# postgresql-client：D50 甲备份作业要 pg_dump/pg_restore——调度器住本箱,
# 拍全家福的工具就得在本箱（进依赖层不进代码层：这行不动缓存不失效）。
COPY pyproject.toml uv.lock ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv \
    && uv sync --frozen --no-install-project   # 按锁文件原样装，一个字节都不漂移

# ── 再装代码层 ──
COPY backend ./backend
# 账本架子也进箱（2026-09-12 云服务器点火案）：本机惯例是迁移在宿主机跑，
# 服务器宿主没有 Python 环境——alembic 进箱，容器内 exec 即可建表，本机服务器同姿势
COPY alembic.ini ./
COPY migrations ./migrations

EXPOSE 8000

# 默认命令：生产形态（无 --reload）；开发期由 compose 的 command 覆盖加重载
CMD ["uv", "run", "--no-sync", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
