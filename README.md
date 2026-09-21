# funuser

基于 FastAPI、SQLAlchemy 和 JWT 的用户管理服务，提供注册、登录、个人信息与密码管理 API。

## 安装

```bash
pip install funuser
```

## 服务管理

安装后使用同一个具名 CLI 管理服务：

```bash
funuser server start                 # 后台启动
funuser server status                # 查看进程、端口和版本
funuser server stop                  # 停止服务
funuser server run --port 8080       # 前台运行
funuser server restart               # 重启服务
```

仓库检出环境也提供统一入口：

```bash
scripts/setup.sh install-dev
scripts/setup.sh start
scripts/setup.sh status
scripts/setup.sh stop
```

`scripts/setup.sh install-prod [版本]` 从 PyPI 安装正式包，`publish` 通过 `funbuild build` 发布。`upgrade [版本]`、`rollback <版本>` 和 `uninstall` 分别用于升级、回退和卸载。

## 配置

默认配置文件为 `${XDG_CONFIG_HOME:-~/.config}/farfarfun/funuser/config.toml`。也可通过 `--config` 指定 `.toml`、`.json` 或 `.env` 文件；命令行的 `--host`、`--port` 优先级最高。

```toml
[server]
host = "127.0.0.1"
port = 8000

[database]
url = "mysql+pymysql://user:password@127.0.0.1/funuser"
```

数据库地址和 JWT 密钥优先从 `FUNUSER_DATABASE_URL`、`FUNUSER_SECRET_KEY` 环境变量读取，也可存入 `funsecret`：

```bash
funsecret write 'mysql+pymysql://user:password@127.0.0.1/funuser' funuser database url
funsecret write 'replace-with-a-long-random-value' funuser security secret_key
```

未配置数据库时，服务安全地使用 XDG 配置目录下的本地 SQLite；未配置 JWT 密钥时会生成随机值并写入 `funsecret`。PID 和日志保存在实际配置文件同目录。

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
