from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ..config import database_url

SQLALCHEMY_DATABASE_URL = database_url()

engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """funuser 的 SQLAlchemy 声明式模型基类。"""


def get_db() -> Generator[Session, None, None]:
    """为一次请求提供数据库会话，并在请求结束时关闭它。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
