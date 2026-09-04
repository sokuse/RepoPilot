from collections.abc import Generator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from repopilot.core.config import settings
from repopilot.db.base import Base

# FastAPI 的同步接口可能跨线程执行，SQLite 开发模式需要关闭同线程限制。
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        # SQLite 默认不执行外键约束，显式开启后才能使用级联删除。
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    # 每个 HTTP 请求独享一个 Session，请求结束后由 with 自动关闭。
    with SessionLocal() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def create_database_tables() -> None:
    # 先导入模型，让表结构注册进 Base.metadata，再创建尚不存在的表。
    from repopilot.models import (  # noqa: F401
        conversation,
        knowledge_chunk,
        project,
        rag_run,
        repository_file,
        vector_index_state,
    )

    Base.metadata.create_all(bind=engine)
