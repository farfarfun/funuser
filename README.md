# funuser

基于 FastAPI + SQLAlchemy 的用户管理服务：提供注册、登录（JWT）、查看/修改个人信息、修改密码等接口，并自带一个用 Click 封装的命令行工具，用来启动/停止/查看该 FastAPI 服务的进程。

## 安装

```bash
pip install funuser
```

## 命令行用法

安装后会提供 `funuser` 命令（对应 `funuser.cli:cli`）：

```bash
funuser start --host 0.0.0.0 --port 8000   # 启动服务（内部用 uvicorn 跑 funuser.main:app），加 --reload 开启自动重载
funuser status                              # 查看服务是否在运行
funuser stop                                # 停止服务
```

服务进程号会记录在 `~/.funuser/funuser.pid`，`stop`/`status` 依赖这个文件判断进程状态。

## 接口一览

服务启动后，接口统一挂在 `/api/v1` 前缀下：

- `POST /api/v1/register` — 注册（用户名、邮箱唯一）
- `POST /api/v1/login` — 登录，返回 JWT `access_token`
- `GET /api/v1/users/me` — 获取当前用户信息（需要 `Authorization: Bearer <token>`）
- `PUT /api/v1/users/me` — 修改邮箱/手机号
- `POST /api/v1/users/me/change-password` — 修改密码

## 数据存储与配置

使用 MySQL，通过 SQLAlchemy 连接（见 `funuser/database/database.py`）。密码用 `passlib`（bcrypt）加密存储，登录态用 `python-jose` 签发 JWT。

需要注意：当前源码里数据库连接串 `mysql+pymysql://root:root@localhost/funuser` 和 JWT 的 `SECRET_KEY` 都是写死在 `database.py` / `core/security.py` 里的常量，并未做成环境变量配置，自行部署到生产环境前需要先改这两处。
