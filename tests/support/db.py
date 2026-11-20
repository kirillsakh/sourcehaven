import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import ClassVar, Literal
from uuid import UUID, uuid7

from pydantic import SecretStr
from sqlalchemy import TableClause, column, select, table, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from sourcehaven.domain.models import OwnerScope
from sourcehaven.storage.db import create_engine, owner_session
from sourcehaven.storage.models import Document, Owner

RoleAttribute = Literal["rolbypassrls", "rolcanlogin", "rolsuper"]


@dataclass(frozen=True)
class TestDatabaseUrls:
    """Connection URLs for one migrated throwaway test database, one per database role."""

    __test__: ClassVar[bool] = False

    app: SecretStr
    maintenance: SecretStr
    admin: SecretStr


@asynccontextmanager
async def admin_connection(admin_url: SecretStr) -> AsyncIterator[AsyncConnection]:
    """Open a short-lived connection as the database owner, bypassing row-level security."""
    engine: AsyncEngine = create_engine(admin_url)
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


async def create_owner(sessions: async_sessionmaker[AsyncSession]) -> OwnerScope:
    owner: OwnerScope = OwnerScope(owner_id=uuid7())
    async with owner_session(sessions, owner) as session:
        session.add(Owner(id=owner.owner_id, kind="anonymous_session"))
    return owner


async def insert_document(
    sessions: async_sessionmaker[AsyncSession], owner: OwnerScope, *, display_name: str
) -> UUID:
    document: Document = Document(
        owner_id=owner.owner_id,
        display_name=display_name,
        content_sha256=hashlib.sha256(uuid7().bytes).digest(),
    )
    async with owner_session(sessions, owner) as session:
        session.add(document)
    return document.id


async def current_revision(admin_url: SecretStr) -> str | None:
    async with admin_connection(admin_url) as connection:
        revision: str | None = await connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
    return revision


async def role_attribute(admin_url: SecretStr, role: str, attribute: RoleAttribute) -> bool:
    pg_roles: TableClause = table("pg_roles", column("rolname"), column(attribute))
    async with admin_connection(admin_url) as connection:
        value: object = await connection.scalar(
            select(pg_roles.c[attribute]).where(pg_roles.c.rolname == role)
        )
    if not isinstance(value, bool):
        raise LookupError(f"Role {role} does not exist")
    return value
