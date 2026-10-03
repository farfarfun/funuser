from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserBase(BaseModel):
    """用户公开字段。"""

    username: str
    email: EmailStr
    phone: str | None = None


class UserCreate(UserBase):
    """注册用户时接收的字段。"""

    password: str


class UserLogin(BaseModel):
    """登录时接收的字段（JSON 请求体，避免凭据出现在 URL 查询串/访问日志中）。"""

    username: str
    password: str


class UserUpdate(BaseModel):
    """更新当前用户时允许修改的字段。"""

    email: EmailStr | None = None
    phone: str | None = None


class ChangePassword(BaseModel):
    """修改密码时接收的新旧密码。"""

    old_password: str
    new_password: str


class UserResponse(UserBase):
    """返回给客户端的用户信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: int
    created_at: datetime
    updated_at: datetime | None = None


class Token(BaseModel):
    """登录成功后返回的访问令牌。"""

    access_token: str
    token_type: str


class TokenData(BaseModel):
    """访问令牌中的用户标识。"""

    username: str
