from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from ..config import secret_key
from ..database.database import get_db
from ..models.user import User

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# 用户名不存在时仍要跑一次完整的哈希校验，耗时与真实用户对齐，避免登录接口
# 通过响应耗时差异被用来枚举已注册用户名（真实哈希校验走 bcrypt，耗时远高于
# 一次字符串比较或提前返回）。这个哈希对应的明文从不会被使用，不是真实凭据。
_UNKNOWN_USER_PASSWORD_HASH = pwd_context.hash("funuser-timing-attack-mitigation")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码是否与已存储的哈希匹配。"""
    return pwd_context.verify(plain_password, hashed_password)


def verify_password_or_dummy(plain_password: str, hashed_password: str | None) -> bool:
    """验证密码；`hashed_password` 为空（用户不存在）时仍执行一次等耗时的哈希校验。

    用于登录接口：无论用户名是否存在都触发同等开销的 bcrypt 运算，
    防止凭据校验的响应耗时差异被用来枚举已注册用户名。
    """
    return pwd_context.verify(
        plain_password, hashed_password or _UNKNOWN_USER_PASSWORD_HASH
    )


def get_password_hash(password: str) -> str:
    """返回适合持久化的密码哈希。"""
    return pwd_context.hash(password)


def create_access_token(
    data: dict[str, Any], expires_delta: timedelta | None = None
) -> str:
    """为给定载荷签发带过期时间的 JWT。"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, secret_key(), algorithm=ALGORITHM)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """解析访问令牌并返回当前用户，凭据无效时返回 401。"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, secret_key(), algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user
