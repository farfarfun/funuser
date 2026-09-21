"""funuser 配置、API、安全辅助函数和 CLI 测试。"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def isolated_runtime(tmp_path_factory: pytest.TempPathFactory):
    """把测试数据库、密钥和运行状态隔离到临时目录。"""
    root = tmp_path_factory.mktemp("funuser")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root / "config"))
    monkeypatch.setenv("FUN_SECRET_PATH", str(root / "secret"))
    monkeypatch.setenv("FUNUSER_DATABASE_URL", f"sqlite:///{root / 'test.db'}")
    monkeypatch.setenv("FUNUSER_SECRET_KEY", "test-only-secret-key")
    yield
    monkeypatch.undo()


@pytest.fixture(scope="session")
def client() -> TestClient:
    """返回使用真实临时 SQLite 的测试客户端。"""
    from funuser.main import app

    with TestClient(app) as test_client:
        yield test_client


def register(client: TestClient, username: str, email: str, password: str = "secret"):
    """调用注册接口并返回响应。"""
    return client.post(
        "/api/v1/register",
        json={"username": username, "email": email, "password": password},
    )


def login(client: TestClient, username: str, password: str = "secret"):
    """调用登录接口并返回响应。"""
    return client.post(
        "/api/v1/login", params={"username": username, "password": password}
    )


def auth_header(client: TestClient, username: str, password: str = "secret"):
    """返回指定测试用户的 Bearer 请求头。"""
    token = login(client, username, password).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_import_public_modules() -> None:
    """所有公开模块都可安全导入。"""
    for module_name in (
        "funuser",
        "funuser.cli",
        "funuser.config",
        "funuser.core.security",
        "funuser.database.database",
        "funuser.models.user",
        "funuser.schemas.user",
        "funuser.routers.user",
    ):
        __import__(module_name)


def test_config_formats_and_cli_priority(tmp_path: Path, monkeypatch) -> None:
    """三种配置格式均可读取，环境变量优先于配置文件。"""
    from funuser.config import database_url, load_config

    toml_config = tmp_path / "config.toml"
    toml_config.write_text("[server]\nport = 9001\n", encoding="utf-8")
    assert load_config(toml_config)["server"]["port"] == 9001

    json_config = tmp_path / "config.json"
    json_config.write_text('{"server": {"port": 9002}}', encoding="utf-8")
    assert load_config(json_config)["server"]["port"] == 9002

    env_config = tmp_path / "config.env"
    env_config.write_text("SERVER_PORT=9003\n", encoding="utf-8")
    assert load_config(env_config)["server_port"] == "9003"

    monkeypatch.setenv("FUNUSER_DATABASE_URL", "sqlite:///environment.db")
    assert database_url(json_config) == "sqlite:///environment.db"


def test_register_and_duplicate_boundaries(client: TestClient) -> None:
    """注册成功，并拒绝重复用户名、重复邮箱和无效邮箱。"""
    response = register(client, "alice", "alice@example.com")
    assert response.status_code == 200
    assert response.json()["username"] == "alice"

    response = register(client, "alice", "alice2@example.com")
    assert response.status_code == 400
    assert response.json()["detail"] == "Username already registered"

    response = register(client, "alice2", "alice@example.com")
    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"

    response = register(client, "invalid", "not-an-email")
    assert response.status_code == 422


def test_login_and_current_user_boundaries(client: TestClient) -> None:
    """登录与当前用户接口覆盖成功、错误密码和未认证路径。"""
    assert register(client, "bob", "bob@example.com", "hunter2").status_code == 200

    response = login(client, "bob", "hunter2")
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"

    assert login(client, "bob", "wrong").status_code == 401
    assert client.get("/api/v1/users/me").status_code == 401

    response = client.get(
        "/api/v1/users/me", headers=auth_header(client, "bob", "hunter2")
    )
    assert response.status_code == 200
    assert response.json()["username"] == "bob"


def test_update_user_normal_and_duplicate_email(client: TestClient) -> None:
    """更新个人信息成功，并拒绝占用其他用户的邮箱。"""
    assert register(client, "carol", "carol@example.com").status_code == 200
    assert register(client, "dave", "dave@example.com").status_code == 200
    headers = auth_header(client, "carol")

    response = client.put(
        "/api/v1/users/me",
        headers=headers,
        json={"email": "carol2@example.com", "phone": "13800138000"},
    )
    assert response.status_code == 200
    assert response.json()["phone"] == "13800138000"

    response = client.put(
        "/api/v1/users/me", headers=headers, json={"email": "dave@example.com"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"


def test_change_password_normal_and_wrong_old_password(client: TestClient) -> None:
    """修改密码成功，并拒绝错误旧密码。"""
    assert register(client, "erin", "erin@example.com", "old-secret").status_code == 200
    headers = auth_header(client, "erin", "old-secret")

    response = client.post(
        "/api/v1/users/me/change-password",
        headers=headers,
        json={"old_password": "wrong", "new_password": "new-secret"},
    )
    assert response.status_code == 400

    response = client.post(
        "/api/v1/users/me/change-password",
        headers=headers,
        json={"old_password": "old-secret", "new_password": "new-secret"},
    )
    assert response.status_code == 200
    assert login(client, "erin", "old-secret").status_code == 401
    assert login(client, "erin", "new-secret").status_code == 200


def test_password_hash_and_access_token() -> None:
    """密码哈希可验证，签发的 JWT 可使用当前密钥解码。"""
    from jose import jwt

    from funuser.config import secret_key
    from funuser.core.security import (
        ALGORITHM,
        create_access_token,
        get_password_hash,
        verify_password,
    )

    hashed = get_password_hash("plain-password")
    assert verify_password("plain-password", hashed)
    assert not verify_password("wrong-password", hashed)

    token = create_access_token({"sub": "frank"})
    assert jwt.decode(token, secret_key(), algorithms=[ALGORITHM])["sub"] == "frank"


def test_cli_exposes_service_and_package_commands() -> None:
    """CLI 暴露服务分组和包管理命令。"""
    from click.testing import CliRunner

    from funuser.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    for command in ("server", "upgrade", "rollback", "uninstall"):
        assert command in result.output

    result = runner.invoke(cli, ["server", "--help"])
    assert result.exit_code == 0
    for command in ("start", "run", "stop", "restart", "status"):
        assert command in result.output


def test_cli_server_options_prefer_flags(tmp_path: Path) -> None:
    """显式服务参数优先于配置文件。"""
    from funuser.cli import _server_settings

    config = tmp_path / "config.toml"
    config.write_text('[server]\nhost = "127.0.0.2"\nport = 9000\n', encoding="utf-8")
    assert _server_settings(config, "0.0.0.0", 8080) == ("0.0.0.0", 8080)


def test_cli_start_and_stop_paths(tmp_path: Path, monkeypatch) -> None:
    """后台启动委派到已安装 CLI，停止操作按监听端口终止进程。"""
    import funshell
    from click.testing import CliRunner

    from funuser import cli as cli_module

    config = tmp_path / "config.toml"
    config.write_text("[server]\nport = 8765\n", encoding="utf-8")
    commands = []

    def fake_popen(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(poll=lambda: None)

    monkeypatch.setattr(cli_module, "_read_active_config", lambda: None)
    monkeypatch.setattr(cli_module, "_read_pid", lambda _config: 321)
    monkeypatch.setattr(cli_module, "_pid_is_live", lambda _pid: True)
    monkeypatch.setattr(cli_module.shutil, "which", lambda _name: "/bin/funuser")
    monkeypatch.setattr(cli_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cli_module.time, "sleep", lambda _seconds: None)

    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["server", "start", "--config", str(config)])
    assert result.exit_code == 0, result.output
    assert commands[0][:3] == ["/bin/funuser", "server", "run"]

    states = iter((True, False))
    monkeypatch.setattr(cli_module, "_pid_is_live", lambda _pid: next(states))
    monkeypatch.setattr(funshell, "kill_process", lambda **_kwargs: [(321, True)])
    result = runner.invoke(
        cli_module.cli,
        ["server", "stop", "--config", str(config), "--port", "8765"],
    )
    assert result.exit_code == 0, result.output
    assert "已停止" in result.output


def test_cli_console_script_help() -> None:
    """模块入口可显示命令帮助。"""
    result = subprocess.run(
        [sys.executable, "-m", "funuser.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert "server" in result.stdout
