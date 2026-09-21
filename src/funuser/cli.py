"""funuser 服务与包管理命令行入口。"""

import os
import shutil
import subprocess
import sys
import time
from importlib.metadata import version as package_version
from pathlib import Path
from typing import NoReturn

import click

from .config import (
    PACKAGE_NAME,
    config_value,
    default_state_dir,
    load_config,
    resolve_config_path,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
STOP_TIMEOUT_SECONDS = 10


def _fail(message: str) -> NoReturn:
    raise click.ClickException(message)


def _active_config_file() -> Path:
    return default_state_dir() / "active-config"


def _read_active_config() -> Path | None:
    try:
        value = _active_config_file().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return Path(value) if value else None


def _resolved_config(config: Path | None, *, use_active: bool = False) -> Path:
    if config is None and use_active:
        config = _read_active_config()
    return resolve_config_path(config)


def _state_paths(config: Path) -> tuple[Path, Path]:
    return config.parent / "funuser.pid", config.parent / "funuser.log"


def _read_pid(config: Path) -> int | None:
    pid_file, _ = _state_paths(config)
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


def _write_state(config: Path, pid: int) -> None:
    pid_file, _ = _state_paths(config)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(f"{pid}\n", encoding="utf-8")
    active = _active_config_file()
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text(f"{config}\n", encoding="utf-8")


def _clear_state(config: Path) -> None:
    pid_file, _ = _state_paths(config)
    pid_file.unlink(missing_ok=True)
    active = _active_config_file()
    if _read_active_config() == config:
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
    return package_version(PACKAGE_NAME)


def _run_server(
    config: Path | None, host: str | None, port: int | None, *, reload: bool = False
) -> None:
    resolved = _resolved_config(config)
    resolved_host, resolved_port = _server_settings(resolved, host, port)
    existing = _read_pid(resolved)
    if existing is not None and existing != os.getpid() and _pid_is_live(existing):
        _fail(f"funuser 已在运行（pid {existing}）")

    os.environ["FUNUSER_CONFIG_FILE"] = str(resolved)
    _write_state(resolved, os.getpid())
    try:
        import uvicorn

        uvicorn.run(
            "funuser.main:app",
            host=resolved_host,
            port=resolved_port,
            reload=reload,
        )
    finally:
        _clear_state(resolved)


def _start_server(config: Path | None, host: str | None, port: int | None) -> None:
    active = _read_active_config()
    if active is not None:
        active_pid = _read_pid(active)
        if active_pid is not None and _pid_is_live(active_pid):
            _fail(f"funuser 已在运行（pid {active_pid}）")
        _clear_state(active)

    resolved = _resolved_config(config)
    _, resolved_port = _server_settings(resolved, host, port)
    _, log_file = _state_paths(resolved)
    executable = shutil.which(PACKAGE_NAME)
    if executable is None:
        _fail("未找到已安装的 funuser 命令；请先安装软件包")

    command = [executable, "server", "run", "--config", str(resolved)]
    if host is not None:
        command.extend(("--host", host))
    if port is not None:
        command.extend(("--port", str(port)))
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("ab") as log:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    time.sleep(1)
    pid = _read_pid(resolved)
    if process.poll() is not None or pid is None or not _pid_is_live(pid):
        _clear_state(resolved)
        _fail(f"funuser 启动失败，请查看日志：{log_file}")
    click.echo(f"funuser 已启动（pid {pid}，端口 {resolved_port}，日志 {log_file}）")


def _stop_server(config: Path | None, port: int | None) -> None:
    resolved = _resolved_config(config, use_active=True)
    pid = _read_pid(resolved)
    if pid is None or not _pid_is_live(pid):
        _clear_state(resolved)
        click.echo("funuser 未在运行")
        return

    _, resolved_port = _server_settings(resolved, None, port)
    from funshell import kill_process

    outcomes = kill_process(port=resolved_port, sig="TERM")
    if not outcomes:
        _fail(f"未找到监听端口 {resolved_port} 的 funuser 进程")

    deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
    while _pid_is_live(pid):
        if time.monotonic() >= deadline:
            _fail(f"funuser 在 {STOP_TIMEOUT_SECONDS}s 内未退出（pid {pid}）")
        time.sleep(0.2)
    _clear_state(resolved)
    click.echo("funuser 已停止")


def _status_server(config: Path | None, port: int | None) -> None:
    resolved = _resolved_config(config, use_active=True)
    pid = _read_pid(resolved)
    _, resolved_port = _server_settings(resolved, None, port)
    if pid is not None and _pid_is_live(pid):
        click.echo(f"运行中（funuser@{_version()}，pid {pid}，端口 {resolved_port}）")
    elif pid is not None:
        click.echo(f"PID 文件已失效（pid {pid}，funuser@{_version()}）")
    else:
        click.echo(f"未在运行（funuser@{_version()}）")


def _run_pip(arguments: list[str]) -> None:
    result = subprocess.run([sys.executable, "-m", "pip", *arguments], check=False)
    if result.returncode != 0:
        _fail(f"pip 执行失败（退出码 {result.returncode}）")


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
@_server_options
def server_run(host: str | None, port: int | None, config: Path | None) -> None:
    """在前台运行 API 服务。"""
    _run_server(config, host, port)


@server.command("start")
@_server_options
def server_start(host: str | None, port: int | None, config: Path | None) -> None:
    """在后台启动 API 服务。"""
    _start_server(config, host, port)


@server.command("stop")
@click.option("--port", type=click.IntRange(1, 65535), help="监听端口")
@click.option("--config", type=click.Path(path_type=Path), help="启动时使用的配置文件")
def server_stop(port: int | None, config: Path | None) -> None:
    """停止后台 API 服务。"""
    _stop_server(config, port)


@server.command("restart")
@_server_options
def server_restart(host: str | None, port: int | None, config: Path | None) -> None:
    """停止后重新启动 API 服务。"""
    _stop_server(config, port)
    _start_server(config, host, port)


@server.command("status")
@click.option("--port", type=click.IntRange(1, 65535), help="监听端口")
@click.option("--config", type=click.Path(path_type=Path), help="启动时使用的配置文件")
def server_status(port: int | None, config: Path | None) -> None:
    """显示 API 服务状态和已安装版本。"""
    _status_server(config, port)


@cli.command("upgrade")
@click.argument("version", required=False)
def upgrade(version: str | None) -> None:
    """升级到最新版或指定版本。"""
    target = f"{PACKAGE_NAME}=={version}" if version else PACKAGE_NAME
    _run_pip(["install", "--upgrade", target])


@cli.command("rollback")
@click.argument("version")
def rollback(version: str) -> None:
    """强制安装指定旧版本。"""
    _run_pip(
        ["install", "--upgrade", "--force-reinstall", f"{PACKAGE_NAME}=={version}"]
    )


@cli.command("uninstall")
def uninstall() -> None:
    """停止服务后卸载 funuser。"""
    _stop_server(None, None)
    _run_pip(["uninstall", "-y", PACKAGE_NAME])


@cli.command("start", hidden=True, deprecated=True)
@click.option("--host", default=DEFAULT_HOST)
@click.option("--port", type=click.IntRange(1, 65535), default=DEFAULT_PORT)
@click.option("--reload", is_flag=True)
def legacy_start(host: str, port: int, reload: bool) -> None:
    """兼容旧版前台启动命令；请改用 ``server run``。"""
    _run_server(None, host, port, reload=reload)


@cli.command("stop", hidden=True, deprecated=True)
def legacy_stop() -> None:
    """兼容旧版停止命令；请改用 ``server stop``。"""
    _stop_server(None, None)


@cli.command("status", hidden=True, deprecated=True)
def legacy_status() -> None:
    """兼容旧版状态命令；请改用 ``server status``。"""
    _status_server(None, None)


if __name__ == "__main__":
    cli()
