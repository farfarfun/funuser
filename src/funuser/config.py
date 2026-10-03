"""funuser 配置加载。"""

import json
import os
import secrets
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 仅 Python 3.10 使用
    import tomli as tomllib

from funsecret import read_secret

PACKAGE_NAME = "funuser"


def default_state_dir() -> Path:
    """返回遵循 XDG 约定的默认配置与运行状态目录。

    目录可能承载本地 SQLite 数据库（含密码哈希）等敏感文件，调用方创建时
    应显式收紧为 0700，不要只依赖进程 umask（参见 #595 先例）。
    """
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "farfarfun" / PACKAGE_NAME


def _ensure_private_dir(path: Path) -> None:
    """创建目录并显式收紧为仅当前用户可读写执行（0700）。"""
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def default_config_path() -> Path:
    """返回默认配置文件路径。"""
    return default_state_dir() / "config.toml"


def resolve_config_path(path: Path | None = None) -> Path:
    """按显式参数、环境变量、默认值的顺序解析配置路径。"""
    configured = path or os.environ.get("FUNUSER_CONFIG_FILE")
    return Path(configured or default_config_path()).expanduser().resolve()


def _load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError(f"无效的 .env 配置行：{raw_line}")
        values[key.strip().lower()] = value.strip().strip("\"'")
    return values


def load_config(path: Path | None = None) -> dict[str, Any]:
    """读取 JSON、TOML 或 .env 配置；文件不存在时返回空配置。"""
    resolved = resolve_config_path(path)
    if not resolved.exists():
        return {}
    suffix = resolved.suffix.lower()
    if suffix == ".json":
        data = json.loads(resolved.read_text(encoding="utf-8-sig"))
    elif suffix == ".toml":
        with resolved.open("rb") as config_file:
            data = tomllib.load(config_file)
    elif suffix == ".env":
        data = _load_env(resolved)
    else:
        raise ValueError(f"不支持的配置文件格式：{suffix}（仅支持 .toml/.json/.env）")
    if not isinstance(data, dict):
        raise TypeError(f"配置文件顶层必须是对象：{resolved}")
    return data


def config_value(
    config: dict[str, Any], section: str, key: str, default: Any = None
) -> Any:
    """读取分节配置，并兼容 .env 的 ``SECTION_KEY`` 形式。"""
    section_data = config.get(section, {})
    if isinstance(section_data, dict) and key in section_data:
        return section_data[key]
    return config.get(f"{section}_{key}", config.get(key, default))


def database_url(path: Path | None = None) -> str:
    """读取数据库地址；缺省使用 XDG 目录下不含凭据的 SQLite。"""
    value = os.environ.get("FUNUSER_DATABASE_URL") or read_secret(
        "funuser", "database", "url"
    )
    if value:
        return str(value)
    state_dir = default_state_dir()
    _ensure_private_dir(state_dir)
    return f"sqlite:///{state_dir / 'funuser.db'}"


def secret_key(path: Path | None = None) -> str:
    """读取 JWT 密钥；未配置时生成并写入 funsecret。"""
    value = os.environ.get("FUNUSER_SECRET_KEY") or read_secret(
        "funuser", "security", "secret_key"
    )
    if value:
        return str(value)
    return str(
        read_secret(
            "funuser", "security", "secret_key", value=secrets.token_urlsafe(48)
        )
    )
