"""funuser 服务与包管理命令行入口。"""

import os
import shutil
import subprocess
import sys
import time
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import NoReturn

import click

from .config import (
    PACKAGE_NAME,
    config_value,
    load_config,
    resolve_config_path,
)
from .config import _ensure_private_dir as _ensure_private_runtime_dir

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
STOP_TIMEOUT_SECONDS = 10


def _fail(message: str) -> NoReturn:
    raise click.ClickException(message)


def _active_config_file(environment: str) -> Path:
    return _runtime_dir() / f"funuser-{environment}.active-config"


def _runtime_dir() -> Path:
    return Path.cwd() / ".run"


def _read_active_config(environment: str) -> Path | None:
    try:
        value = _active_config_file(environment).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return Path(value) if value else None


def _resolved_config(
    config: Path | None, environment: str, *, use_active: bool = False
) -> Path:
    if config is None and use_active:
        config = _read_active_config(environment)
    return resolve_config_path(config)


def _state_paths(environment: str) -> tuple[Path, Path]:
    return (
        _runtime_dir() / f"funuser-{environment}.pid",
        _runtime_dir() / f"funuser-{environment}.log",
    )


def _read_pid(environment: str) -> int | None:
    pid_file, _ = _state_paths(environment)
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 1 else None


def _pid_is_live(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        stat = Path(f"/proc/{pid}/stat")
        return not stat.exists() or stat.read_text().split()[2] != "Z"
    except (OSError, IndexError):
        return False


def _pid_belongs_to_service(pid: int) -> bool:
    """确认 PID 的命令行属于 funuser，避免误停复用 PID 的其他进程。"""
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
    except OSError:
        return False
    return b"funuser" in command


def _write_state(environment: str, config: Path, pid: int) -> None:
    pid_file, _ = _state_paths(environment)
    _ensure_private_runtime_dir(pid_file.parent)
    pid_file.write_text(f"{pid}\n", encoding="utf-8")
    os.chmod(pid_file, 0o600)
    active = _active_config_file(environment)
    _ensure_private_runtime_dir(active.parent)
    active.write_text(f"{config}\n", encoding="utf-8")
    os.chmod(active, 0o600)


def _clear_state(environment: str, config: Path) -> None:
    pid_file, _ = _state_paths(environment)
    pid_file.unlink(missing_ok=True)
    active = _active_config_file(environment)
    if _read_active_config(environment) == config:
        active.unlink(missing_ok=True)


def _server_settings(
    config: Path, host: str | None, port: int | None
) -> tuple[str, int]:
    try:
        values = load_config(config)
        resolved_host = host or str(
            config_value(values, "server", "host", DEFAULT_HOST)
        )
        resolved_port = int(
            port
            if port is not None
            else config_value(values, "server", "port", DEFAULT_PORT)
        )
    except (OSError, ValueError) as error:
        _fail(f"读取配置失败（{config}）：{error}")
    if not 1 <= resolved_port <= 65535:
        _fail(f"端口必须在 1-65535 之间：{resolved_port}")
    return resolved_host, resolved_port


def _version() -> str:
    return distribution(PACKAGE_NAME).version


def _require_production_install() -> None:
    """拒绝用源码树或 editable 安装冒充正式发行包。"""
    try:
        installed = distribution(PACKAGE_NAME)
    except PackageNotFoundError:
        _fail("prod 模式要求先安装 funuser 正式发行包")
    direct_url = installed.read_text("direct_url.json") or ""
    if '"editable": true' in direct_url:
        _fail("prod 模式不能运行 editable 安装；请先安装正式发行包")
    source_root = Path.cwd().resolve()
    if (source_root / "pyproject.toml").is_file() and Path(
        __file__
    ).resolve().is_relative_to(source_root):
        _fail("prod 模式不能从当前源码目录运行；请使用已安装的正式发行包")


def _run_server(
    environment: str,
    config: Path | None,
    host: str | None,
    port: int | None,
) -> None:
    if environment == "prod":
        _require_production_install()
    resolved = _resolved_config(config, environment)
    resolved_host, resolved_port = _server_settings(resolved, host, port)
    existing = _read_pid(environment)
    if existing is not None and existing != os.getpid() and _pid_is_live(existing):
        _fail(f"funuser 已在运行（pid {existing}）")

    os.environ["FUNUSER_CONFIG_FILE"] = str(resolved)
    _write_state(environment, resolved, os.getpid())
    try:
        import uvicorn

        uvicorn.run(
            "funuser.main:app",
            host=resolved_host,
            port=resolved_port,
            reload=environment == "dev",
        )
    finally:
        _clear_state(environment, resolved)


def _start_server(
    environment: str, config: Path | None, host: str | None, port: int | None
) -> None:
    if environment == "prod":
        _require_production_install()
    active = _read_active_config(environment)
    if active is not None:
        active_pid = _read_pid(environment)
        if active_pid is not None and _pid_is_live(active_pid):
            _fail(f"funuser 已在运行（pid {active_pid}）")
        _clear_state(environment, active)

    resolved = _resolved_config(config, environment)
    _, resolved_port = _server_settings(resolved, host, port)
    _, log_file = _state_paths(environment)
    command = [
        sys.executable,
        "-m",
        "funuser.cli",
        "server",
        "run",
        environment,
        "--config",
        str(resolved),
    ]
    if host is not None:
        command.extend(("--host", host))
    if port is not None:
        command.extend(("--port", str(port)))
    _ensure_private_runtime_dir(log_file.parent)
    if not log_file.exists():
        log_file.touch()
    os.chmod(log_file, 0o600)
    with log_file.open("ab") as log:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    time.sleep(1)
    pid = _read_pid(environment)
    if process.poll() is not None or pid is None or not _pid_is_live(pid):
        _clear_state(environment, resolved)
        _fail(f"funuser 启动失败，请查看日志：{log_file}")
    click.echo(f"funuser 已启动（pid {pid}，端口 {resolved_port}，日志 {log_file}）")


def _stop_server(environment: str, config: Path | None, port: int | None) -> None:
    resolved = _resolved_config(config, environment, use_active=True)
    pid = _read_pid(environment)
    if pid is None or not _pid_is_live(pid):
        _clear_state(environment, resolved)
        click.echo("funuser 未在运行")
        return

    if not _pid_belongs_to_service(pid):
        _fail(f"PID {pid} 不属于 funuser，拒绝停止")
    try:
        os.kill(pid, 15)
    except OSError as error:
        _fail(f"无法停止 funuser（pid {pid}）：{error}")

    deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
    while _pid_is_live(pid):
        if time.monotonic() >= deadline:
            _fail(f"funuser 在 {STOP_TIMEOUT_SECONDS}s 内未退出（pid {pid}）")
        time.sleep(0.2)
    _clear_state(environment, resolved)
    click.echo("funuser 已停止")


def _status_server(environment: str, config: Path | None, port: int | None) -> None:
    resolved = _resolved_config(config, environment, use_active=True)
    pid = _read_pid(environment)
    _, resolved_port = _server_settings(resolved, None, port)
    if pid is not None and _pid_is_live(pid):
        click.echo(
            f"{environment}: 运行中（funuser@{_version()}，pid {pid}，端口 {resolved_port}）"
        )
    elif pid is not None:
        click.echo(f"{environment}: PID 文件已失效（pid {pid}，funuser@{_version()}）")
    else:
        click.echo(f"{environment}: 未在运行（funuser@{_version()}）")


def _run_uv(arguments: list[str]) -> None:
    executable = shutil.which("uv")
    if executable is None:
        _fail("未找到 uv；请先安装 uv")
    result = subprocess.run([executable, *arguments], check=False)
    if result.returncode != 0:
        _fail(f"uv 执行失败（退出码 {result.returncode}）")


@click.group(no_args_is_help=True)
@click.version_option(package_name=PACKAGE_NAME)
def cli() -> None:
    """funuser 用户管理服务。"""


@cli.group("server", no_args_is_help=True)
def server() -> None:
    """管理 API 服务生命周期。"""


def _server_options(function):
    function = click.option(
        "--config",
        type=click.Path(path_type=Path),
        help=".toml、.json 或 .env 配置文件",
    )(function)
    function = click.option("--port", type=click.IntRange(1, 65535), help="监听端口")(
        function
    )
    return click.option("--host", help="监听地址")(function)


@server.command("run")
@click.argument("environment", type=click.Choice(("dev", "prod")))
@_server_options
def server_run(
    environment: str, host: str | None, port: int | None, config: Path | None
) -> None:
    """在前台运行 API 服务。"""
    _run_server(environment, config, host, port)


@server.command("start")
@click.argument("environment", type=click.Choice(("dev", "prod")))
@_server_options
def server_start(
    environment: str, host: str | None, port: int | None, config: Path | None
) -> None:
    """在后台启动 API 服务。"""
    _start_server(environment, config, host, port)


@server.command("stop")
@click.argument("environment", type=click.Choice(("dev", "prod")))
@click.option("--port", type=click.IntRange(1, 65535), help="监听端口")
@click.option("--config", type=click.Path(path_type=Path), help="启动时使用的配置文件")
def server_stop(environment: str, port: int | None, config: Path | None) -> None:
    """停止后台 API 服务。"""
    _stop_server(environment, config, port)


@server.command("restart")
@click.argument("environment", type=click.Choice(("dev", "prod")))
@_server_options
def server_restart(
    environment: str, host: str | None, port: int | None, config: Path | None
) -> None:
    """停止后重新启动 API 服务。"""
    _stop_server(environment, config, port)
    _start_server(environment, config, host, port)


@server.command("status")
@click.argument("environment", type=click.Choice(("dev", "prod")), required=False)
@click.option("--port", type=click.IntRange(1, 65535), help="监听端口")
@click.option("--config", type=click.Path(path_type=Path), help="启动时使用的配置文件")
def server_status(
    environment: str | None, port: int | None, config: Path | None
) -> None:
    """显示 API 服务状态和已安装版本。"""
    environments = (environment,) if environment else ("dev", "prod")
    for target in environments:
        _status_server(target, config, port)


@cli.command("upgrade")
@click.argument("version", required=False)
def upgrade(version: str | None) -> None:
    """升级到最新版或指定版本。"""
    target = f"{PACKAGE_NAME}=={version}" if version else PACKAGE_NAME
    _run_uv(["tool", "install", "--upgrade", target])


@cli.command("rollback")
@click.argument("version")
def rollback(version: str) -> None:
    """强制安装指定旧版本。"""
    _run_uv(["tool", "install", "--force", f"{PACKAGE_NAME}=={version}"])


@cli.command("uninstall")
def uninstall() -> None:
    """停止服务后卸载 funuser。"""
    for environment in ("dev", "prod"):
        _stop_server(environment, None, None)
    _run_uv(["tool", "uninstall", PACKAGE_NAME])


if __name__ == "__main__":
    cli()
