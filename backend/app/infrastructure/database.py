"""SQLAlchemy 引擎与会话工厂。

- SQLite 连接开启 WAL、busy_timeout 与外键约束。
- 依据 SQLAlchemy 官方 pysqlite 配方把所有事务改为 BEGIN IMMEDIATE：
  写事务在开始时即取得 reserved 锁，幂等「检查+插入」因此原子化，
  并发写同一实体时由乐观版本列裁决（A09）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.infrastructure.config import get_settings

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Base(DeclarativeBase):
    pass


def resolve_database_url(url: str) -> str:
    """把相对 SQLite 路径锚定到仓库根，避免随进程 CWD 漂移。"""
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url
    raw_path = url[len(prefix):]
    if not raw_path or raw_path.startswith(":memory:") or Path(raw_path).is_absolute():
        return url
    absolute = (_PROJECT_ROOT / raw_path).resolve()
    absolute.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{absolute.as_posix()}"


def configure_engine(engine: Engine) -> Engine:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @event.listens_for(engine, "connect")
    def _disable_pysqlite_begin(dbapi_connection, connection_record):  # noqa: ANN001
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_immediate(dbapi_connection):  # noqa: ANN001
        dbapi_connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    engine = create_engine(
        resolve_database_url(settings.database_url),
        connect_args={"check_same_thread": False},
    )
    return configure_engine(engine)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
