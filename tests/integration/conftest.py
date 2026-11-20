import os
import secrets
from collections.abc import AsyncIterator, Iterator

import pytest
from pydantic import SecretStr
from sqlalchemy import URL, Engine, NullPool, make_url, text
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sourcehaven.migrations import upgrade_database
from sourcehaven.storage.db import create_engine, make_sessionmaker
from tests.support.db import TestDatabaseUrls

# The development stack uses these passwords too. Roles are cluster-wide, so tests must assign the
# same values or the running stack's logins would break.
DEFAULT_DEVELOPMENT_PASSWORD: str = "devpassword"
START_DATABASE_COMMAND: str = "docker compose -f compose.yaml -f compose.dev.yaml up -d db"


def _environment_secret(name: str) -> SecretStr:
    return SecretStr(os.environ.get(name, DEFAULT_DEVELOPMENT_PASSWORD))


def _server_admin_url() -> URL:
    configured: str | None = os.environ.get("SOURCEHAVEN_TEST_ADMIN_URL")
    if configured:
        return make_url(configured)
    return URL.create(
        "postgresql+psycopg",
        username="sourcehaven_admin",
        password=_environment_secret("POSTGRES_PASSWORD").get_secret_value(),
        host="127.0.0.1",
        port=55432,
        database="postgres",
    )


def _secret_url(url: URL) -> SecretStr:
    return SecretStr(url.render_as_string(hide_password=False))


@pytest.fixture(scope="session")
def database_urls() -> Iterator[TestDatabaseUrls]:
    """Create and migrate a throwaway database, dropping it after the test session."""
    server_url: URL = _server_admin_url()
    database_name: str = f"sh_test_{secrets.token_hex(4)}"
    server: Engine = create_sync_engine(
        server_url, isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    try:
        with server.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    except OperationalError as error:
        server.dispose()
        pytest.fail(
            f"Postgres is unreachable at {server_url.render_as_string(hide_password=True)}: "
            f"{error.orig}\nStart it with: {START_DATABASE_COMMAND}",
            pytrace=False,
        )
    try:
        admin_url: URL = server_url.set(database=database_name)
        app_password: SecretStr = _environment_secret("SOURCEHAVEN_APP_ROLE_PASSWORD")
        maintenance_password: SecretStr = _environment_secret(
            "SOURCEHAVEN_MAINTENANCE_ROLE_PASSWORD"
        )
        upgrade_database(
            admin_url=_secret_url(admin_url),
            app_role_password=app_password,
            maintenance_role_password=maintenance_password,
        )
        yield TestDatabaseUrls(
            app=_secret_url(
                admin_url.set(username="sourcehaven_app", password=app_password.get_secret_value())
            ),
            maintenance=_secret_url(
                admin_url.set(
                    username="sourcehaven_maintenance",
                    password=maintenance_password.get_secret_value(),
                )
            ),
            admin=_secret_url(admin_url),
        )
    finally:
        with server.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
        server.dispose()


@pytest.fixture
async def app_sessions(
    database_urls: TestDatabaseUrls,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessions connected as `sourcehaven_app`, the role used for request handling."""
    engine: AsyncEngine = create_engine(database_urls.app)
    try:
        yield make_sessionmaker(engine)
    finally:
        await engine.dispose()
