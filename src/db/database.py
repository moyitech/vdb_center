from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from typing import AsyncGenerator
from sqlalchemy_utils import database_exists, create_database
from sqlalchemy import text, select, update, delete, insert
from src.conf.env import settings
from src.db.models import Base

pg_url = settings.BIZ_DB_CONNECTION
async_pg_url = settings.VEC_DB_CONNECTION



# 如果数据名不存在，就创建一个
if not database_exists(pg_url):
    create_database(pg_url)

async_engine = create_async_engine(
    async_pg_url,
    connect_args={"server_settings": {"timezone": "Asia/Shanghai"}},
    pool_size=20,  # 连接池大小
    max_overflow=10,  # 最大溢出连接数
    pool_pre_ping=True,  # 连接前测试连接
    # pool_recycle=28800,  # 8小时回收连接
    echo=False  # 设为True可以看到SQL语句
)

# todo all 在这里 migrate
# Note: create_all is sync, so we use sync engine for this operation
from sqlalchemy import create_engine

sync_engine = create_engine(
    pg_url,
    connect_args={"options": "-c timezone=Asia/Shanghai"}
)

from sqlalchemy import text

with sync_engine.begin() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
Base.metadata.create_all(bind=sync_engine)  # type: ignore


DBSession = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with DBSession() as session:
        yield session


async def get_tx_session() -> AsyncGenerator[AsyncSession, None]:
    async with DBSession() as session:
        async with session.begin():
            yield session


if __name__ == "__main__":
    import asyncio
