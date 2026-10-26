from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata

# 伴考接线：建表图纸(metadata)与连接串都取自 backend 侧，真源唯一——
# 迁移工具和后端读的是同一份 db.py，永不出现"两边账对不上"
from backend.db import DATABASE_URL  # noqa: E402
from backend.models import Base  # noqa: E402  导入即把 users/conversations/messages 登记进 metadata

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# ── S9·W5 外来表黑名单（家法：手写索引必登 __table_args__ 的镜像雷）──
# 这四张是 LangGraph PostgresSaver.setup() 自管自建的检查点表——排障工具，
# 不在伴考的建表图纸(metadata)里。不拉黑的话，下次 autogenerate 会把它们
# 判成孤儿表生成 DROP，一条正常迁移就把别人的家拆了（历史上误拆别家表的同款坑）。
_LG_TABLES = {"checkpoints", "checkpoint_blobs", "checkpoint_writes",
              "checkpoint_migrations"}


def _include_object(object, name, type_, reflected, compare_to) -> bool:
    """alembic 比对面筛子：四张检查点表不进任何比对（增删改全当看不见）。
    对象身份认 type_ 参数（"table"/"column"/"index"…）——raw Table 对象没有
    .kind 属性，那是比对后 diff 对象的字段（探针真炸出来的坑，2026-10-11）。"""
    return not (type_ == "table" and name in _LG_TABLES)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata,
            include_object=_include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
