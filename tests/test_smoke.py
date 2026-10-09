"""funuser 配置、API、安全辅助函数和 CLI 测试。"""

import os
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
        "/api/v1/login", json={"username": username, "password": password}
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


def test_credentials_are_not_read_from_config(tmp_path: Path, monkeypatch) -> None:
    """数据库凭据和 JWT 密钥不能从普通配置文件读取。"""
    from funuser import config as config_module

    config = tmp_path / "config.toml"
    config.write_text(
        '[database]\nurl = "mysql://plain-text-password"\n'
        '[security]\nsecret_key = "plain-text-key"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("FUNUSER_DATABASE_URL")
    monkeypatch.delenv("FUNUSER_SECRET_KEY")
    monkeypatch.setattr(
        config_module,
        "read_secret",
        lambda *_args, **kwargs: kwargs.get("value"),
    )

    assert "plain-text-password" not in config_module.database_url(config)
    generated = config_module.secret_key(config)
    assert generated != "plain-text-key"


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


def test_disabled_user_cannot_log_in(client: TestClient) -> None:
    """status=0 的账户即使凭据正确也不得签发新的访问令牌。"""
    from funuser.database.database import SessionLocal
    from funuser.models.user import User

    assert register(client, "disabled", "disabled@example.com").status_code == 200
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "disabled").one()
        user.status = 0
        db.commit()

    response = login(client, "disabled")
    assert response.status_code == 403
    assert response.json()["detail"] == "User is disabled"


def test_login_unknown_username_still_runs_password_hash_check(
    client: TestClient, monkeypatch
) -> None:
    """用户名不存在时也要执行一次哈希校验，错误信息与耗时和密码错误保持一致。

    防止 /login 通过「是否触发 bcrypt 校验」的响应耗时差异被用来枚举用户名
    （对照：仅凭 `not user or ...` 短路会让未注册用户名明显更快返回）。
    """
    from funuser.core import security as security_module

    calls: list[str | None] = []
    original = security_module.pwd_context.verify

    def spy(plain_password: str, hashed_password: str) -> bool:
        calls.append(hashed_password)
        return original(plain_password, hashed_password)

    monkeypatch.setattr(security_module.pwd_context, "verify", spy)

    missing_response = login(client, "no-such-user", "whatever")
    assert missing_response.status_code == 401
    assert missing_response.json()["detail"] == "Incorrect username or password"
    assert len(calls) == 1
    assert calls[0] == security_module._UNKNOWN_USER_PASSWORD_HASH


def test_login_rejects_query_string_credentials(client: TestClient) -> None:
    """登录凭据必须是 JSON 请求体，不能作为 URL 查询参数传递（避免落入访问日志）。"""
    assert register(client, "quinn", "quinn@example.com", "q-secret").status_code == 200

    query_response = client.post(
        "/api/v1/login", params={"username": "quinn", "password": "q-secret"}
    )
    assert query_response.status_code == 422

    body_response = client.post(
        "/api/v1/login", json={"username": "quinn", "password": "q-secret"}
    )
    assert body_response.status_code == 200


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


def test_cli_service_environment_is_required_except_status(monkeypatch) -> None:
    """长期运行服务命令必须显式选择环境，status 可汇总所有环境。"""
    from click.testing import CliRunner

    from funuser import cli as cli_module

    runner = CliRunner()
    result = runner.invoke(cli_module.cli, ["server", "start"])
    assert result.exit_code != 0
    assert "dev|prod" in result.output
    statuses = []
    monkeypatch.setattr(
        cli_module,
        "_status_server",
        lambda environment, config, port: statuses.append(environment),
    )
    result = runner.invoke(cli_module.cli, ["server", "status"])
    assert result.exit_code == 0, result.output
    assert statuses == ["dev", "prod"]


def test_cli_start_and_stop_paths(tmp_path: Path, monkeypatch) -> None:
    """后台启动传递环境，停止操作只向记录且校验过的 PID 发信号。"""
    from click.testing import CliRunner

    from funuser import cli as cli_module

    config = tmp_path / "config.toml"
    config.write_text("[server]\nport = 8765\n", encoding="utf-8")
    commands = []

    def fake_popen(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(poll=lambda: None)

    pids = iter((None, 321, 321))
    monkeypatch.setattr(cli_module, "_read_pid", lambda _environment: next(pids))
    monkeypatch.setattr(cli_module, "_pid_is_live", lambda _pid: True)
    monkeypatch.setattr(cli_module, "_pid_belongs_to_service", lambda _pid: True)
    monkeypatch.setattr(cli_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cli_module.time, "sleep", lambda _seconds: None)

    runner = CliRunner()
    result = runner.invoke(
        cli_module.cli, ["server", "start", "dev", "--config", str(config)]
    )
    assert result.exit_code == 0, result.output
    assert commands[0][:6] == [
        sys.executable,
        "-m",
        "funuser.cli",
        "server",
        "run",
        "dev",
    ]

    states = iter((True, False))
    signals = []
    monkeypatch.setattr(cli_module, "_pid_is_live", lambda _pid: next(states))
    monkeypatch.setattr(
        cli_module.os, "kill", lambda pid, sig: signals.append((pid, sig))
    )
    result = runner.invoke(
        cli_module.cli,
        ["server", "stop", "dev", "--config", str(config), "--port", "8765"],
    )
    assert result.exit_code == 0, result.output
    assert signals == [(321, 15)]
    assert "已停止" in result.output


def test_cli_stop_uses_the_requested_environment(tmp_path: Path, monkeypatch) -> None:
    """停止 prod 不得读取或停止 dev 的运行状态。"""
    from click.testing import CliRunner

    from funuser import cli as cli_module

    config = tmp_path / "config.toml"
    requested_environments = []
    monkeypatch.setattr(
        cli_module,
        "_read_pid",
        lambda environment: requested_environments.append(environment) or None,
    )

    result = CliRunner().invoke(
        cli_module.cli, ["server", "stop", "prod", "--config", str(config)]
    )
    assert result.exit_code == 0, result.output
    assert requested_environments == ["prod"]


def test_runtime_files_use_environment_specific_dot_run(
    tmp_path: Path, monkeypatch
) -> None:
    """PID 和日志位于稳定的 XDG `.run` 目录，并按环境隔离。"""
    from funuser import cli as cli_module

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    other_working_directory = tmp_path / "other-working-directory"
    other_working_directory.mkdir()
    monkeypatch.chdir(other_working_directory)
    dev_pid, dev_log = cli_module._state_paths("dev")
    prod_pid, prod_log = cli_module._state_paths("prod")
    runtime_dir = tmp_path / "config/farfarfun/funuser/.run"
    assert dev_pid == runtime_dir / "funuser-dev.pid"
    assert dev_log == runtime_dir / "funuser-dev.log"
    assert prod_pid == runtime_dir / "funuser-prod.pid"
    assert prod_log == runtime_dir / "funuser-prod.log"


def test_cli_rejects_live_pid_only_when_it_is_funuser(tmp_path: Path, monkeypatch) -> None:
    """启动仅将命令行属于 funuser 的存活 PID 视为重复服务。"""
    import click
    from click.testing import CliRunner

    from funuser import cli as cli_module

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    config = tmp_path / "config.toml"
    cli_module._write_state("dev", config, 321)
    monkeypatch.setattr(cli_module, "_pid_is_live", lambda _pid: True)
    monkeypatch.setattr(cli_module, "_pid_belongs_to_service", lambda _pid: False)

    result = CliRunner().invoke(cli_module.cli, ["server", "status", "dev"])
    assert result.exit_code == 0, result.output
    assert "PID 文件陈旧" in result.output
    assert "运行中" not in result.output

    cli_module._clear_or_reject_existing_service("dev")
    pid_file, _ = cli_module._state_paths("dev")
    assert not pid_file.exists()
    assert not cli_module._has_state("dev")

    monkeypatch.setattr(cli_module, "_pid_belongs_to_service", lambda _pid: True)
    cli_module._write_state("dev", config, 321)
    with pytest.raises(click.ClickException, match="已在运行"):
        cli_module._clear_or_reject_existing_service("dev")


def test_cli_legacy_commands_warn_and_forward(monkeypatch) -> None:
    """顶层旧命令在弃用期内仍可调用对应的 server 命令。"""
    from click.testing import CliRunner

    from funuser import cli as cli_module

    calls = []
    monkeypatch.setattr(
        cli_module,
        "_start_server",
        lambda environment, config, host, port: calls.append(
            ("start", environment, config, host, port)
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "_stop_server",
        lambda environment, config, port: calls.append(("stop", environment, config, port)),
    )
    monkeypatch.setattr(
        cli_module,
        "_status_server",
        lambda environment, config, port: calls.append(("status", environment, config, port)),
    )

    runner = CliRunner()
    with pytest.warns(DeprecationWarning, match="server start.*0.3.0"):
        assert runner.invoke(cli_module.cli, ["start"]).exit_code == 0
    with pytest.warns(DeprecationWarning, match="server stop.*0.3.0"):
        assert runner.invoke(cli_module.cli, ["stop", "dev"]).exit_code == 0
    with pytest.warns(DeprecationWarning, match="server status.*0.3.0"):
        assert runner.invoke(cli_module.cli, ["status", "prod"]).exit_code == 0

    assert calls == [
        ("start", "prod", None, None, None),
        ("stop", "dev", None, None),
        ("status", "prod", None, None),
    ]


def test_state_dir_and_pid_file_permissions_are_private(
    tmp_path: Path, monkeypatch
) -> None:
    """落盘的数据库目录与 PID/active-config 文件权限显式收紧，不依赖 umask。"""
    import stat

    from funuser import cli as cli_module
    from funuser.config import database_url

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("FUNUSER_DATABASE_URL", raising=False)
    database_url()
    state_dir = tmp_path / "config" / "farfarfun" / "funuser"
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700

    config = tmp_path / "config.toml"
    cli_module._write_state("dev", config, 999)
    pid_file, _ = cli_module._state_paths("dev")
    assert stat.S_IMODE(pid_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(pid_file.parent.stat().st_mode) == 0o700
    active = cli_module._active_config_file("dev")
    assert stat.S_IMODE(active.stat().st_mode) == 0o600


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


def test_setup_service_actions_use_installed_cli(tmp_path: Path) -> None:
    """生命周期脚本不接受环境参数，且不通过仓库环境运行服务。"""
    executable = tmp_path / "funuser"
    arguments = tmp_path / "arguments"
    executable.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "$FUNUSER_ARGUMENTS"\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    environment = {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FUNUSER_ARGUMENTS": str(arguments),
        "FUNUSER_PORT": "8123",
    }
    script = Path(__file__).parents[1] / "scripts" / "setup.sh"

    result = subprocess.run(
        [str(script), "start"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert arguments.read_text(encoding="utf-8").splitlines() == [
        "server",
        "start",
        "prod",
        "--port",
        "8123",
    ]

    result = subprocess.run(
        [str(script), "start", "dev"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "不接受额外参数" in result.stderr
