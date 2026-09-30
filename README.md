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
funuser server status prod                # 查看进程、端口和版本
funuser server stop prod                  # 停止服务
funuser server run prod --port 8080       # 前台运行正式包
funuser server restart prod               # 重启服务
```

仓库检出环境也提供统一入口：

```bash
scripts/setup.sh install-dev
scripts/setup.sh start dev
scripts/setup.sh status dev
scripts/setup.sh stop dev
```

`scripts/setup.sh install-prod [版本]` 使用 `uv tool` 从 PyPI 安装正式包；`start prod` 和 `run prod` 会拒绝源码或 editable 安装。`publish` 通过锁定在开发依赖中的 `funbuild` 发布。`upgrade [版本]`、`rollback <版本>` 和 `uninstall` 分别用于升级、回退和卸载。

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

未配置数据库时，服务使用 XDG 配置目录下的本地 SQLite；未配置 JWT 密钥时会生成随机值并写入 `funsecret`。PID 和日志统一保存在服务工作目录的 `.run/` 中。

## 接口

- `POST /api/v1/register`：注册用户，用户名和邮箱唯一。
- `POST /api/v1/login`：登录并返回 JWT 访问令牌。
- `GET /api/v1/users/me`：获取当前用户。
- `PUT /api/v1/users/me`：修改邮箱或手机号。
- `POST /api/v1/users/me/change-password`：修改密码。

服务启动后可访问 `/docs` 查看交互式 API 文档。

---

## 关于 farfarfun

[farfarfun](https://github.com/farfarfun) 是一个专注于实用工具库的开源组织，
涵盖云存储、数据处理、AI、多媒体与开发工具链等方向。

- 🏠 组织主页：<https://github.com/farfarfun>
- 📦 PyPI：<https://pypi.org/user/niuliangtao/>
- 📧 联系：farfarfun@qq.com

本项目基于 [MIT](LICENSE) 协议开源。
