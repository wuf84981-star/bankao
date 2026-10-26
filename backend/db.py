# ============================================================
# 数据库连接（S1 骨架版）
# 账密与配载图(docker-compose.yml)同源：bankao / dev_only_123 @127.0.0.1:5432
# 将来 backend 进容器后，主机名换成服务名 db，串从环境变量取，本文件不改结构。
# ============================================================
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://bankao:dev_only_123@127.0.0.1:5432/bankao",
)

engine = create_engine(DATABASE_URL)   # 连接池：后端通往数据库箱的干线
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """ORM 登记簿的父类：继承它的类=一张要建出来的表"""
    pass
