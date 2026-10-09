# funuser

基于 FastAPI、SQLAlchemy 和 JWT 的用户管理服务，提供注册、登录、个人信息与密码管理 API。

## 安装

```bash
uv tool install funuser
```

## 服务管理

安装后使用同一个具名 CLI 管理服务：

```bash
funuser server start prod                 # 后台启动正式包
funuser server status                     # 非交互地汇总 dev、prod 状态
funuser server status prod                # 只查看正式环境
funuser server stop prod                  # 停止服务
funuser server run prod --port 8080       # 前台运行正式包
funuser server restart prod               # 重启服务
```

仓库检出环境也提供统一入口：

```bash
scripts/setup.sh install-dev
scripts/setup.sh run
scripts/setup.sh start
scripts/setup.sh status
scripts/setup.sh stop
scripts/setup.sh restart
```

`dev` 使用仓库依赖并开启自动重载，`prod` 只运行已安装的正式包。`start` 在后台运行，`run` 在前台运行，`stop`、`restart` 和带环境参数的 `status` 只操作目标环境；运行状态分别保存在 `${XDG_CONFIG_HOME:-~/.config}/farfarfun/funuser/.run/funuser-dev.*` 与 `${XDG_CONFIG_HOME:-~/.config}/farfarfun/funuser/.run/funuser-prod.*`，不受调用目录影响。`scripts/setup.sh` 的服务动作不带环境参数，始终转发给已安装 CLI 的 `prod` 实例；开发调试请直接使用 `funuser server <动作> dev`。脚本可从任意工作目录调用，并始终以脚本所在仓库为工作目录。

旧的顶层 `funuser start`、`funuser stop` 和 `funuser status` 仍可在兼容期内使用，但会发出 `DeprecationWarning`；请分别迁移为 `funuser server start`、`funuser server stop` 和 `funuser server status`。这些顶层命令计划在 `0.3.0` 移除。

`scripts/setup.sh install-prod [版本]` 使用 `uv tool` 从 PyPI 安装正式包；脚本的 `start` 和 `run` 只运行正式安装包，拒绝源码或 editable 安装。`scripts/setup.sh publish` 调用 `funbuild build` 的完整发布流程。`upgrade [版本]`、`rollback <版本>` 和 `uninstall` 分别用于升级、回退和卸载。

## 最小示例

在一个终端启动服务：

```bash
scripts/setup.sh run
```

在另一个终端注册、登录并访问受保护接口：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","email":"alice@example.com","password":"secret"}'

TOKEN=$(curl -sS -X POST http://127.0.0.1:8000/api/v1/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"secret"}' \
  | python -c 'import json, sys; print(json.load(sys.stdin)["access_token"])')

curl http://127.0.0.1:8000/api/v1/users/me \
  -H "Authorization: Bearer ${TOKEN}"
```

## 配置

默认配置文件为 `${XDG_CONFIG_HOME:-~/.config}/farfarfun/funuser/config.toml`。也可通过 `--config` 指定 `.toml`、`.json` 或 `.env` 文件；命令行的 `--host`、`--port` 优先级最高。

```toml
[server]
host = "127.0.0.1"
port = 8000
```

数据库地址和 JWT 密钥只能通过 `FUNUSER_DATABASE_URL`、`FUNUSER_SECRET_KEY` 环境变量或 `funsecret` 提供，不能写入 TOML、JSON 或 `.env` 配置文件：

```bash
funsecret write 'mysql+pymysql://user:password@127.0.0.1/funuser' funuser database url
funsecret write 'replace-with-a-long-random-value' funuser security secret_key
```

未配置数据库时，服务使用 XDG 配置目录下的本地 SQLite；未配置 JWT 密钥时会生成随机值并写入 `funsecret`。

## 接口

- `POST /api/v1/register`：注册用户，用户名和邮箱唯一。
- `POST /api/v1/login`：登录并返回 JWT 访问令牌。
- `GET /api/v1/users/me`：获取当前用户。
- `PUT /api/v1/users/me`：修改邮箱或手机号。
- `POST /api/v1/users/me/change-password`：修改密码。

服务启动后可访问 `/docs` 查看交互式 API 文档。

## 开发与发布

```bash
uv sync --group dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run funbuild install  # 本地构建并安装校验，不发布
uv build                 # 只构建分发产物
scripts/setup.sh publish # 完整发布流程：版本、构建、安装校验、发布、推送和标签
```

---

## 关于 farfarfun

[farfarfun](https://github.com/farfarfun) 是一个专注于实用工具库的开源组织，
涵盖云存储、数据处理、AI、多媒体与开发工具链等方向。

- 🏠 组织主页：<https://github.com/farfarfun>
- 📦 PyPI：<https://pypi.org/user/niuliangtao/>
- 📧 联系：farfarfun@qq.com

本项目基于 [MIT](LICENSE) 协议开源。
