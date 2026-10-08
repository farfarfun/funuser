from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
    verify_password_or_dummy,
)
from ..database.database import get_db
from ..models.user import User
from ..schemas.user import (
    ChangePassword,
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
    UserUpdate,
)

router = APIRouter()


@router.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Annotated[Session, Depends(get_db)]) -> User:
    """注册用户。

    参数为注册字段和请求数据库会话；成功时返回新用户，用户名或邮箱重复时返回 400。
    """
    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    db_user = User(
        username=user.username,
        email=user.email,
        phone=user.phone,
        password=get_password_hash(user.password),
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.post("/login", response_model=Token)
def login(
    credentials: UserLogin, db: Annotated[Session, Depends(get_db)]
) -> dict[str, str]:
    """校验用户名和密码并返回访问令牌，凭据错误时返回 401。

    凭据必须通过 JSON 请求体传递，不能作为 URL 查询参数（会被记入访问日志/代理日志）。

    用户名不存在和密码错误返回完全相同的状态码、错误信息，且都会执行一次
    bcrypt 校验（见 `verify_password_or_dummy`），耗时也保持一致，避免被用来
    枚举已注册用户名。
    """
    user = db.query(User).filter(User.username == credentials.username).first()
    password_matches = verify_password_or_dummy(
        credentials.password, user.password if user else None
    )
    if not user or not password_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    if user.status != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User is disabled"
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/users/me", response_model=UserResponse)
def read_users_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """返回访问令牌对应的当前用户。"""
    return current_user


@router.put("/users/me", response_model=UserResponse)
def update_user_me(
    user_update: UserUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """更新当前用户的邮箱或手机号，邮箱重复时返回 400。"""
    if user_update.email is not None and user_update.email != current_user.email:
        if db.query(User).filter(User.email == user_update.email).first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )
        current_user.email = user_update.email

    if user_update.phone is not None:
        current_user.phone = user_update.phone

    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/users/me/change-password")
def change_password(
    password_update: ChangePassword,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, str]:
    """校验旧密码后更新当前用户密码，旧密码错误时返回 400。"""
    if not verify_password(password_update.old_password, current_user.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect password"
        )

    current_user.password = get_password_hash(password_update.new_password)
    db.commit()
    return {"message": "Password updated successfully"}
