from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sourcehaven.domain.models import OwnerScope


def create_engine(url: SecretStr) -> AsyncEngine:
    """Create an async engine; the role in `url` decides which row-level security applies.

    SQL parameters are hidden from statement logs and exception messages, because they carry
    visitor content such as questions and answers.
    """
    return create_async_engine(url.get_secret_value(), pool_pre_ping=True, hide_parameters=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


class PrivilegedRoleError(RuntimeError):
    """The application is connected as a role that row-level security does not restrict."""


async def ensure_rls_applies(session: AsyncSession) -> None:
    """Refuse to continue as a superuser or `BYPASSRLS` role.

    Row-level security is the second isolation layer between visitors (design spec section 5.1);
    either attribute would silently switch it off for every request.

    Raises:
        PrivilegedRoleError: If the connected role is a superuser or has `BYPASSRLS`.
    """
    privileged: bool | None = await session.scalar(
        text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
    )
    if privileged is not False:
        raise PrivilegedRoleError(
            "The application database role is a superuser or has BYPASSRLS, which disables "
            "row-level security; set SOURCEHAVEN_DATABASE_URL to the sourcehaven_app role"
        )


@asynccontextmanager
async def owner_session(
    factory: async_sessionmaker[AsyncSession], owner: OwnerScope
) -> AsyncIterator[AsyncSession]:
    """Run one transaction in which row-level security exposes only `owner`'s rows.

    The transaction commits when the block exits normally and rolls back when it raises.
    Callers must not call `commit()` or `rollback()` themselves: a new transaction started
    inside the block would run without the owner and therefore see no owner-scoped rows.

    The owner is set with `set_config('app.owner_id', ..., true)`, which is transaction-local.
    Verified on 2026-11-19 against the official documentation:

    - PostgreSQL `set_config` (https://www.postgresql.org/docs/18/functions-admin.html):
      with `is_local` true "the new value will only apply during the current transaction".
    - PostgreSQL `SET` (https://www.postgresql.org/docs/18/sql-set.html): `SET LOCAL`
      effects "last only till the end of the current transaction, whether committed or not".
    - SQLAlchemy asyncio and session transactions
      (https://docs.sqlalchemy.org/en/21/orm/session_transaction.html): `session.begin()` as a
      context manager commits at the end or rolls back on an exception, and the connection is
      then released. The pool rolls back every returned connection by default ("Reset On
      Return", https://docs.sqlalchemy.org/en/21/core/pooling.html).

    So the owner never outlives this transaction, and a pooled connection reused by another
    owner or by `system_session` carries no owner. After such a transaction ends PostgreSQL
    reports the setting as an empty string rather than NULL (checked on PostgreSQL 18.7), which
    is why the policies treat an empty value as "no owner".

    Args:
        factory: Session factory bound to the `sourcehaven_app` role.
        owner: The owner whose rows the transaction may read and write.

    Yields:
        A session inside the owner-scoped transaction.
    """
    async with factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.owner_id', :owner, true)"),
            {"owner": str(owner.owner_id)},
        )
        yield session


@asynccontextmanager
async def system_session(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """Run one transaction without an owner, in which no owner-scoped row is visible.

    Use it only to call the cross-owner `SECURITY DEFINER` functions, such as session
    resolution and job claiming. Commit and rollback behave as in `owner_session`.

    Args:
        factory: Session factory bound to the `sourcehaven_app` role.

    Yields:
        A session inside a transaction with no owner set.
    """
    async with factory() as session, session.begin():
        yield session
