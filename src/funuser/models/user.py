from sqlalchemy import Column, DateTime, Integer, SmallInteger, String
from sqlalchemy.sql import func

from ..database.database import Base


class User(Base):
    """持久化的用户账户。"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    phone = Column(String(20))
    status = Column(SmallInteger, default=1)  # 0 表示禁用，1 表示正常
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
