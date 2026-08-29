"""Lightweight smoke tests for funuser.

funuser is a FastAPI + SQLAlchemy user management service. The source
contains a hardcoded MySQL DSN (funuser.database.database.SQLALCHEMY_DATABASE_URL
= "mysql+pymysql://root:root@localhost/funuser") and a hardcoded JWT secret
(funuser.core.security.SECRET_KEY = "your-secret-key"). None of these tests
open a real MySQL connection or start a live uvicorn server: the one place
that would trigger a real connection attempt at import time
(``funuser.main`` calls ``User.Base.metadata.create_all(bind=engine)`` at
module scope) is patched out before import.
"""

import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. Import smoke tests
# ---------------------------------------------------------------------------


def test_import_top_level_package():
    import funuser  # noqa: F401


@pytest.mark.parametrize(
    "module_name",
    [
        "funuser.cli",
        "funuser.core",
        "funuser.core.security",
        "funuser.database",
        "funuser.database.database",
        "funuser.models",
        "funuser.models.user",
        "funuser.schemas",
        "funuser.schemas.user",
        "funuser.routers",
        "funuser.routers.user",
    ],
)
def test_import_submodules(module_name):
    """All obviously-public submodules should import without touching a real DB.

    None of these modules perform I/O at import time: SQLAlchemy's
    create_engine()/sessionmaker() are lazy and only connect when a query is
    actually executed.
    """
    __import__(module_name)


# ---------------------------------------------------------------------------
# 2. funuser.main / FastAPI app smoke tests (DB layer mocked)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    """Import funuser.main with the startup DB-schema creation mocked out.

    funuser/main.py runs ``user.Base.metadata.create_all(bind=engine)`` at
    module import time, which would otherwise attempt a real connection to
    the hardcoded MySQL server. We patch SQLAlchemy's create_all so import
    succeeds without any real database.
    """
    sys.modules.pop("funuser.main", None)
    with patch("funuser.models.user.Base.metadata.create_all") as mocked_create_all:
        import funuser.main as main_module
    assert mocked_create_all.called
    return main_module.app


def test_app_is_fastapi_instance(app):
    from fastapi import FastAPI

    assert isinstance(app, FastAPI)


def test_app_has_expected_routes(app):
    # Walk the OpenAPI schema rather than app.routes directly: starlette's
    # internal route-tree representation for included routers is not a
    # stable public API and has changed across major versions.
    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/register" in paths
    assert "/api/v1/login" in paths
    assert "/api/v1/users/me" in paths


def test_register_endpoint_with_mocked_db(app):
    """POST /api/v1/register with the DB session mocked out."""
    from datetime import datetime, timezone

    from fastapi.testclient import TestClient

    from funuser.database.database import get_db

    mock_db = MagicMock()
    # No existing user with this username/email.
    mock_db.query.return_value.filter.return_value.first.return_value = None

    def fake_refresh(obj):
        obj.id = 1
        obj.status = 1
        obj.created_at = datetime.now(timezone.utc)
        obj.updated_at = None

    mock_db.refresh.side_effect = fake_refresh

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/register",
            json={
                "username": "alice",
                "email": "alice@example.com",
                "password": "secret123",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["username"] == "alice"
        assert data["email"] == "alice@example.com"
    finally:
        app.dependency_overrides.clear()


def test_login_endpoint_with_mocked_db(app):
    """POST /api/v1/login with the DB session mocked out."""
    from fastapi.testclient import TestClient

    from funuser.core.security import get_password_hash
    from funuser.database.database import get_db
    from funuser.models.user import User

    fake_user = User(
        username="bob",
        email="bob@example.com",
        password=get_password_hash("hunter2"),
    )

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = fake_user

    def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        response = client.post(
            "/api/v1/login", params={"username": "bob", "password": "hunter2"}
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["token_type"] == "bearer"
        assert data["access_token"]
    finally:
        app.dependency_overrides.clear()


def test_read_users_me_endpoint_with_mocked_auth(app):
    """GET /api/v1/users/me with both the DB session and current-user auth mocked."""
    from datetime import datetime, timezone

    from fastapi.testclient import TestClient

    from funuser.core.security import get_current_user
    from funuser.database.database import get_db
    from funuser.models.user import User

    fake_user = User(
        username="carol",
        email="carol@example.com",
        password="irrelevant-hash",
        phone=None,
        status=1,
    )
    fake_user.id = 1
    fake_user.created_at = datetime.now(timezone.utc)
    fake_user.updated_at = None

    app.dependency_overrides[get_db] = lambda: iter([MagicMock()])
    app.dependency_overrides[get_current_user] = lambda: fake_user
    try:
        client = TestClient(app)
        response = client.get("/api/v1/users/me")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["username"] == "carol"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 3. Core security helpers (no DB involved)
# ---------------------------------------------------------------------------


def test_password_hash_roundtrip():
    from funuser.core.security import get_password_hash, verify_password

    hashed = get_password_hash("my-plain-password")
    assert hashed != "my-plain-password"
    assert verify_password("my-plain-password", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_create_access_token_and_decode():
    from jose import jwt

    from funuser.core.security import ALGORITHM, SECRET_KEY, create_access_token

    token = create_access_token({"sub": "dave"})
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["sub"] == "dave"
    assert "exp" in payload


# ---------------------------------------------------------------------------
# 4. Models / schemas construction (no DB I/O)
# ---------------------------------------------------------------------------


def test_user_model_construct():
    from funuser.models.user import User

    user = User(username="erin", email="erin@example.com", password="hashed")
    assert user.username == "erin"
    assert user.email == "erin@example.com"


def test_user_schemas_construct():
    from funuser.schemas.user import Token, UserCreate

    created = UserCreate(username="frank", email="frank@example.com", password="pw")
    assert created.username == "frank"

    token = Token(access_token="abc", token_type="bearer")
    assert token.token_type == "bearer"


def test_user_schema_rejects_invalid_email():
    from pydantic import ValidationError

    from funuser.schemas.user import UserCreate

    with pytest.raises(ValidationError):
        UserCreate(username="grace", email="not-an-email", password="pw")


# ---------------------------------------------------------------------------
# 5. CLI entry point
# ---------------------------------------------------------------------------


def test_cli_group_help():
    from click.testing import CliRunner

    from funuser.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "User Management System CLI" in result.output


@pytest.mark.parametrize("subcommand", ["start", "stop", "status"])
def test_cli_subcommand_help(subcommand):
    from click.testing import CliRunner

    from funuser.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, [subcommand, "--help"])
    assert result.exit_code == 0


def test_cli_console_script_help():
    """The [project.scripts] entry point `funuser` should invoke cleanly with --help.

    Run as `python -m funuser.cli --help` (equivalent entry point target)
    inside the current interpreter/venv so this doesn't depend on the
    console-script wrapper being on PATH.
    """
    result = subprocess.run(
        [sys.executable, "-m", "funuser.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "User Management System CLI" in result.stdout


# ---------------------------------------------------------------------------
# 6. Things we explicitly do NOT smoke test against real infra
# ---------------------------------------------------------------------------


def test_real_mysql_connection_skipped():
    pytest.skip(
        "funuser.database.database 使用硬编码的 MySQL 凭据"
        " (mysql+pymysql://root:root@localhost/funuser)，"
        "本地/CI 环境没有真实 MySQL 服务，无法也不应该在冒烟测试中连接真实数据库，故跳过。"
    )


def test_live_uvicorn_server_skipped():
    pytest.skip(
        "funuser.cli 的 start 命令会调用 uvicorn.run() 启动真实监听的服务进程，"
        "冒烟测试不应启动常驻服务，故跳过；改为通过 TestClient + mocked DB 覆盖路由逻辑。"
    )
