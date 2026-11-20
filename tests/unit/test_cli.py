import asyncio
import json
import os
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from sourcehaven import __version__
from sourcehaven.cli import main
from sourcehaven.config import Settings


def test_version_is_set() -> None:
    assert __version__ == "0.1.0"


def test_help_lists_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out: str = capsys.readouterr().out
    for command in ("serve", "worker", "migrate", "openapi"):
        assert command in out


def test_migrate_upgrades_with_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def record_upgrade(
        *, admin_url: SecretStr, app_role_password: SecretStr, maintenance_role_password: SecretStr
    ) -> None:
        calls.append(
            (
                admin_url.get_secret_value(),
                app_role_password.get_secret_value(),
                maintenance_role_password.get_secret_value(),
            )
        )

    monkeypatch.setattr("sourcehaven.cli.upgrade_database", record_upgrade)
    monkeypatch.setenv("SOURCEHAVEN_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("SOURCEHAVEN_ADMIN_DATABASE_URL", "postgresql+psycopg://admin:a@db/x")
    monkeypatch.setenv("SOURCEHAVEN_APP_ROLE_PASSWORD", "app-secret")
    monkeypatch.setenv("SOURCEHAVEN_MAINTENANCE_ROLE_PASSWORD", "maintenance-secret")

    assert main(["migrate"]) == 0
    assert calls == [("postgresql+psycopg://admin:a@db/x", "app-secret", "maintenance-secret")]


@pytest.mark.parametrize(
    "missing",
    [
        "SOURCEHAVEN_ADMIN_DATABASE_URL",
        "SOURCEHAVEN_APP_ROLE_PASSWORD",
        "SOURCEHAVEN_MAINTENANCE_ROLE_PASSWORD",
    ],
)
def test_migrate_fails_when_a_credential_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], missing: str
) -> None:
    def fail_upgrade(**_: SecretStr) -> None:
        raise AssertionError("migrations must not start without all credentials")

    monkeypatch.setattr("sourcehaven.cli.upgrade_database", fail_upgrade)
    monkeypatch.setenv("SOURCEHAVEN_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("SOURCEHAVEN_ADMIN_DATABASE_URL", "postgresql+psycopg://admin:a@db/x")
    monkeypatch.setenv("SOURCEHAVEN_APP_ROLE_PASSWORD", "app-secret")
    monkeypatch.setenv("SOURCEHAVEN_MAINTENANCE_ROLE_PASSWORD", "maintenance-secret")
    monkeypatch.delenv(missing)

    assert main(["migrate"]) == 2
    assert missing in capsys.readouterr().err


def _use_offline_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCEHAVEN_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("SOURCEHAVEN_GENERATION_PROVIDER", "fake")
    monkeypatch.setenv("SOURCEHAVEN_HUMAN_VERIFICATION", "disabled")
    monkeypatch.setenv("SOURCEHAVEN_COOKIE_SECURE", "false")


def test_openapi_command_prints_schema_offline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_offline_settings(monkeypatch)

    assert main(["openapi"]) == 0

    schema: dict[str, object] = json.loads(capsys.readouterr().out)
    assert "openapi" in schema
    assert "/api/health/live" in cast("dict[str, object]", schema["paths"])


def test_serve_runs_uvicorn_behind_the_trusted_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_offline_settings(monkeypatch)
    monkeypatch.setenv("SOURCEHAVEN_TRUSTED_PROXY", "10.0.0.1")
    calls: list[tuple[object, dict[str, object]]] = []

    def record_run(app: object, **options: object) -> None:
        calls.append((app, options))

    monkeypatch.setattr("sourcehaven.cli.uvicorn.run", record_run)

    assert main(["serve"]) == 0

    assert len(calls) == 1
    app, options = calls[0]
    assert isinstance(app, FastAPI)
    assert options == {
        "host": "0.0.0.0",
        "port": 8000,
        "proxy_headers": True,
        "forwarded_allow_ips": "10.0.0.1",
        "access_log": False,
    }


def test_worker_runs_until_a_termination_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_offline_settings(monkeypatch)
    container: object = object()
    seen: list[object] = []

    @asynccontextmanager
    async def fake_build_container(settings: Settings) -> AsyncIterator[object]:
        yield container

    async def fake_run_worker(running: object, *, stop: asyncio.Event) -> None:
        seen.append(running)
        os.kill(os.getpid(), signal.SIGTERM)
        async with asyncio.timeout(5):
            await stop.wait()

    monkeypatch.setattr("sourcehaven.cli.build_container", fake_build_container)
    monkeypatch.setattr("sourcehaven.cli.run_worker", fake_run_worker)

    assert main(["worker"]) == 0

    assert seen == [container]
