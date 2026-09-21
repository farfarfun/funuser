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
)
from ..database.database import get_db
from ..models.user import User
from ..schemas.user import ChangePassword, Token, UserCreate, UserResponse, UserUpdate

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
    username: str, password: str, db: Annotated[Session, Depends(get_db)]
) -> dict[str, str]:
    """校验用户名和密码并返回访问令牌，凭据错误时返回 401。"""
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
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
