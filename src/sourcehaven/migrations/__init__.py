"""Alembic migrations, packaged so that production images can migrate without the source tree."""

from functools import cache

import psycopg
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, NullPool, create_engine

SCRIPT_LOCATION: str = "sourcehaven:migrations"
APP_ROLE: str = "sourcehaven_app"
MAINTENANCE_ROLE: str = "sourcehaven_maintenance"


def _script_config() -> Config:
    config: Config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    return config


@cache
def packaged_head() -> str:
    """Return the newest migration revision shipped in the package."""
    head: str | None = ScriptDirectory.from_config(_script_config()).get_current_head()
    if head is None:
        raise LookupError("The package contains no migrations")
    return head


def upgrade_database(
    *, admin_url: SecretStr, app_role_password: SecretStr, maintenance_role_password: SecretStr
) -> None:
    """Migrate the database to the latest revision and let the application roles log in.

    Also resets the roles' privilege attributes, so a role that already existed with other
    attributes ends up as the schema expects: neither role is a superuser, `sourcehaven_app` is
    subject to row-level security and `sourcehaven_maintenance` bypasses it. Changing these
    attributes requires the owner role to be a superuser.

    Everything runs in one transaction as the database owner, so a failure leaves the schema,
    the role attributes and the role passwords unchanged. Roles are cluster-wide: these changes
    affect every database in the same PostgreSQL cluster.

    Args:
        admin_url: SQLAlchemy URL (psycopg driver) of the owner role that may create roles.
        app_role_password: Login password assigned to `sourcehaven_app`.
        maintenance_role_password: Login password assigned to `sourcehaven_maintenance`.
    """
    engine: Engine = create_engine(admin_url.get_secret_value(), poolclass=NullPool)
    try:
        with engine.begin() as connection:
            upgrade_on_connection(
                connection,
                app_role_password=app_role_password,
                maintenance_role_password=maintenance_role_password,
            )
    finally:
        engine.dispose()


def upgrade_on_connection(
    connection: Connection, *, app_role_password: SecretStr, maintenance_role_password: SecretStr
) -> None:
    """Run the `upgrade_database` steps inside the caller's transaction on an owner connection.

    The caller decides whether to commit; rolling back undoes the schema, attribute and password
    changes alike.

    Args:
        connection: Owner-role connection (psycopg driver) with an open transaction.
        app_role_password: Login password assigned to `sourcehaven_app`.
        maintenance_role_password: Login password assigned to `sourcehaven_maintenance`.
    """
    config: Config = _script_config()
    config.attributes["connection"] = connection
    command.upgrade(config, "head")
    _enable_login(connection, APP_ROLE, app_role_password, bypass_rls=False)
    _enable_login(connection, MAINTENANCE_ROLE, maintenance_role_password, bypass_rls=True)


def _enable_login(
    connection: Connection, role: str, password: SecretStr, *, bypass_rls: bool
) -> None:
    # ALTER ROLE accepts no bind parameters, so the password is quoted by psycopg instead.
    driver_connection: object = connection.connection.driver_connection
    if not isinstance(driver_connection, psycopg.Connection):
        raise TypeError("Migrations require the psycopg driver (postgresql+psycopg://)")
    statement: sql.Composed = sql.SQL("ALTER ROLE {} LOGIN NOSUPERUSER {} PASSWORD {}").format(
        sql.Identifier(role),
        sql.SQL("BYPASSRLS" if bypass_rls else "NOBYPASSRLS"),
        sql.Literal(password.get_secret_value()),
    )
    with driver_connection.cursor() as cursor:
        cursor.execute(statement)
