import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from psycopg.errors import ForeignKeyViolation
from pydantic import SecretStr
from sqlalchemy import (
    Connection,
    Engine,
    Executable,
    NullPool,
    RootTransaction,
    Row,
    create_engine,
    delete,
    func,
    insert,
    make_url,
    select,
    text,
    update,
)
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sourcehaven.domain.models import OwnerScope
from sourcehaven.migrations import packaged_head, upgrade_on_connection
from sourcehaven.storage.db import owner_session, system_session
from sourcehaven.storage.models import (
    AnonymousSession,
    Base,
    Chunk,
    Conversation,
    Document,
    DocumentVersion,
    EmbeddingConfigRow,
    IngestionJob,
    Owner,
    Turn,
    TurnSource,
)
from tests.support.db import (
    TestDatabaseUrls,
    admin_connection,
    create_owner,
    current_revision,
    insert_document,
    role_attribute,
)

pytestmark = pytest.mark.integration

OWNER_SCOPED_TABLES: frozenset[str] = frozenset(
    {
        "owners",
        "anonymous_sessions",
        "documents",
        "document_versions",
        "ingestion_jobs",
        "chunks",
        "conversations",
        "turns",
        "turn_sources",
    }
)
# Far before any clock other tests use, so claims here never pick up their jobs and vice versa.
EPOCH: datetime = datetime(2000, 1, 1, tzinfo=UTC)


async def test_migrations_reach_head(database_urls: TestDatabaseUrls) -> None:
    assert await current_revision(database_urls.admin) == packaged_head()


async def test_app_role_can_read_the_applied_revision(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with system_session(app_sessions) as session:
        revision: str | None = await session.scalar(text("SELECT version_num FROM alembic_version"))
    assert revision == packaged_head()


async def test_models_match_migration(database_urls: TestDatabaseUrls) -> None:
    def differences(connection: Connection) -> list[object]:
        found: list[object] = compare_metadata(
            MigrationContext.configure(connection), Base.metadata
        )
        return found

    async with admin_connection(database_urls.admin) as connection:
        diff: list[object] = await connection.run_sync(differences)
    assert diff == []


async def test_owner_sees_only_own_documents(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    owner_a: OwnerScope = await create_owner(app_sessions)
    owner_b: OwnerScope = await create_owner(app_sessions)
    await insert_document(app_sessions, owner_a, display_name="a.pdf")
    async with owner_session(app_sessions, owner_b) as session:
        rows: Sequence[Document] = (await session.scalars(select(Document))).all()
    assert rows == []


async def test_without_owner_context_nothing_is_visible(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    owner: OwnerScope = await create_owner(app_sessions)
    await insert_document(app_sessions, owner, display_name="a.pdf")
    async with system_session(app_sessions) as session:
        assert (await session.scalars(select(Document))).all() == []


async def test_cannot_insert_row_for_another_owner(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    owner_a: OwnerScope = await create_owner(app_sessions)
    owner_b: OwnerScope = await create_owner(app_sessions)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with owner_session(app_sessions, owner_a) as session:
            session.add(
                Document(
                    owner_id=owner_b.owner_id, display_name="x.pdf", content_sha256=b"\x00" * 32
                )
            )


async def test_app_role_cannot_bypass_rls(database_urls: TestDatabaseUrls) -> None:
    assert await role_attribute(database_urls.admin, "sourcehaven_app", "rolbypassrls") is False


async def test_roles_can_log_in_and_only_maintenance_bypasses_rls(
    database_urls: TestDatabaseUrls,
) -> None:
    admin = database_urls.admin
    assert await role_attribute(admin, "sourcehaven_app", "rolcanlogin") is True
    assert await role_attribute(admin, "sourcehaven_app", "rolsuper") is False
    assert await role_attribute(admin, "sourcehaven_maintenance", "rolcanlogin") is True
    assert await role_attribute(admin, "sourcehaven_maintenance", "rolbypassrls") is True
    assert await role_attribute(admin, "sourcehaven_maintenance", "rolsuper") is False


def _password(url: SecretStr) -> SecretStr:
    password: str | None = make_url(url.get_secret_value()).password
    assert password is not None
    return SecretStr(password)


def _role_flags(connection: Connection, role: str) -> tuple[bool, bool]:
    row: Row[bool, bool] = connection.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = :role"), {"role": role}
    ).one()
    return row[0], row[1]


def test_migrate_resets_privileges_of_existing_roles(database_urls: TestDatabaseUrls) -> None:
    """Escalate, migrate and assert inside one transaction that is always rolled back.

    Roles are cluster-wide and shared with the dev stack. Role attributes are transactional, so
    no other connection ever sees the escalated roles, and an interrupted run leaves nothing
    behind.
    """
    engine: Engine = create_engine(database_urls.admin.get_secret_value(), poolclass=NullPool)
    try:
        with engine.connect() as connection, engine.connect() as observer:
            transaction: RootTransaction = connection.begin()
            try:
                connection.execute(text("ALTER ROLE sourcehaven_app SUPERUSER BYPASSRLS"))
                connection.execute(text("ALTER ROLE sourcehaven_maintenance SUPERUSER"))
                assert _role_flags(connection, "sourcehaven_app") == (True, True)  # control
                assert _role_flags(observer, "sourcehaven_app") == (False, False)  # not visible

                upgrade_on_connection(
                    connection,
                    app_role_password=_password(database_urls.app),
                    maintenance_role_password=_password(database_urls.maintenance),
                )

                assert _role_flags(connection, "sourcehaven_app") == (False, False)
                assert _role_flags(connection, "sourcehaven_maintenance") == (False, True)
            finally:
                transaction.rollback()
            assert _role_flags(observer, "sourcehaven_app") == (False, False)
            assert _role_flags(observer, "sourcehaven_maintenance") == (False, True)
    finally:
        engine.dispose()


async def test_exactly_the_owner_scoped_tables_force_rls(database_urls: TestDatabaseUrls) -> None:
    async with admin_connection(database_urls.admin) as connection:
        rows: Sequence[Row[str, bool, bool]] = (
            await connection.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class"
                    " WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'"
                )
            )
        ).all()
    forced: set[str] = {name for name, enabled, force in rows if enabled and force}
    unprotected: set[str] = {name for name, enabled, force in rows if not enabled and not force}
    assert forced == OWNER_SCOPED_TABLES
    assert unprotected == {"alembic_version", "embedding_configs"}


async def test_owner_context_ends_with_each_transaction(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    owner: OwnerScope = await create_owner(app_sessions)
    async with owner_session(app_sessions, owner) as session:
        backend: int | None = await session.scalar(text("SELECT pg_backend_pid()"))
    with pytest.raises(LookupError):
        async with owner_session(app_sessions, owner) as session:
            raise LookupError
    async with system_session(app_sessions) as session:
        reused_backend: int | None = await session.scalar(text("SELECT pg_backend_pid()"))
        leftover: str | None = await session.scalar(
            text("SELECT current_setting('app.owner_id', true)")
        )
        owners: Sequence[Owner] = (await session.scalars(select(Owner))).all()
    assert reused_backend == backend, "the pooled connection should have been reused"
    assert leftover in (None, "")
    assert owners == []


async def test_resolve_session_returns_only_live_sessions(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    owner: OwnerScope = await create_owner(app_sessions)
    now: datetime = EPOCH
    live: AnonymousSession = _anonymous_session(owner, now)
    idle_expired: AnonymousSession = _anonymous_session(owner, now, idle_expires_at=now)
    absolute_expired: AnonymousSession = _anonymous_session(owner, now, absolute_expires_at=now)
    ended: AnonymousSession = _anonymous_session(owner, now, ended_at=now)
    async with owner_session(app_sessions, owner) as session:
        session.add_all([live, idle_expired, absolute_expired, ended])

    assert await _resolve(app_sessions, live.token_hash, now) == [(live.id, owner.owner_id)]
    for rejected in (idle_expired, absolute_expired, ended):
        assert await _resolve(app_sessions, rejected.token_hash, now) == []
    assert await _resolve(app_sessions, hashlib.sha256(b"unknown").digest(), now) == []


async def test_claim_ingestion_job_leases_due_jobs_once(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    owner: OwnerScope = await create_owner(app_sessions)
    try:
        due: IngestionJob = await _insert_job(app_sessions, owner, next_attempt_at=EPOCH, order=0)
        await _insert_job(app_sessions, owner, next_attempt_at=EPOCH + timedelta(hours=1), order=1)
        now: datetime = EPOCH + timedelta(minutes=1)

        assert await _claim(app_sessions, now) == [(due.id, owner.owner_id, due.version_id)]
        assert await _claim(app_sessions, now) == []
        async with owner_session(app_sessions, owner) as session:
            claimed: IngestionJob | None = await session.get(IngestionJob, due.id)
        assert claimed is not None
        assert claimed.status == "running" and claimed.attempts == 1
        assert claimed.lease_expires_at == now + timedelta(seconds=300)

        after_lease: datetime = now + timedelta(seconds=301)
        assert await _claim(app_sessions, after_lease) == [(due.id, owner.owner_id, due.version_id)]
    finally:
        await _delete_owner(app_sessions, owner)


async def test_security_definer_functions_are_private_to_the_app_role(
    database_urls: TestDatabaseUrls,
) -> None:
    async with admin_connection(database_urls.admin) as connection:
        rows: Sequence[Row[str, bool, str, list[str], list[str]]] = (
            await connection.execute(
                text(
                    "SELECT p.proname, p.prosecdef, pg_get_userbyid(p.proowner), p.proconfig,"
                    " array(SELECT coalesce(nullif(a.grantee, 0)::regrole::text, 'PUBLIC')"
                    "       FROM aclexplode(p.proacl) AS a"
                    "       WHERE a.privilege_type = 'EXECUTE' ORDER BY 1)"
                    " FROM pg_proc AS p WHERE p.proname LIKE 'sourcehaven\\_%' ORDER BY 1"
                )
            )
        ).all()
    assert [row[0] for row in rows] == [
        "sourcehaven_claim_ingestion_job",
        "sourcehaven_resolve_session",
    ]
    for _, security_definer, function_owner, config, executors in rows:
        assert security_definer is True
        assert function_owner == "sourcehaven_maintenance"
        assert config == ["search_path=public"]
        assert executors == ["sourcehaven_app", "sourcehaven_maintenance"]


async def test_deleting_an_owner_removes_all_owner_data(
    app_sessions: async_sessionmaker[AsyncSession], database_urls: TestDatabaseUrls
) -> None:
    owner: OwnerScope = await create_owner(app_sessions)
    async with system_session(app_sessions) as session:
        config: EmbeddingConfigRow = _embedding_config()
        session.add(config)
    version: DocumentVersion = await _insert_version(app_sessions, owner)
    conversation: Conversation = Conversation(id=uuid7(), owner_id=owner.owner_id)
    turn: Turn = _turn(owner, conversation.id)
    async with owner_session(app_sessions, owner) as session:
        session.add(_anonymous_session(owner, EPOCH))
        session.add(
            IngestionJob(
                owner_id=owner.owner_id,
                version_id=version.id,
                status="queued",
                next_attempt_at=EPOCH + timedelta(days=1),
            )
        )
        session.add(_chunk(owner, version, config.id))
        session.add(conversation)
        await session.flush()
        session.add(turn)
        await session.flush()
        session.add(_turn_source(owner, turn.id, version))

    await _delete_owner(app_sessions, owner)

    async with admin_connection(database_urls.admin) as connection:
        for table_name in sorted(OWNER_SCOPED_TABLES - {"owners"}):
            remaining: int | None = await connection.scalar(
                text(f"SELECT count(*) FROM {table_name} WHERE owner_id = :owner"),
                {"owner": owner.owner_id},
            )
            assert remaining == 0, table_name
        owners_left: int | None = await connection.scalar(
            select(func.count()).select_from(Owner).where(Owner.id == owner.owner_id)
        )
        configs_left: int | None = await connection.scalar(
            select(func.count())
            .select_from(EmbeddingConfigRow)
            .where(EmbeddingConfigRow.id == config.id)
        )
    assert owners_left == 0
    assert configs_left == 1


@dataclass(frozen=True)
class OwnedRows:
    """Ids of one owner's rows of every referenceable kind, created by `_insert_owned_rows`."""

    document_id: UUID
    version_id: UUID
    conversation_id: UUID
    turn_id: UUID
    client_request_id: UUID
    embedding_config_id: int


# Each builds a statement that writes a row of the acting owner (first argument) whose reference
# is the given parent id. Values that are unique per owner (version 1, chunk 0, label S1, a
# generating turn, the client request id) repeat the other owner's rows on purpose: a key that
# was not owner-scoped would then fail with a unique violation instead of a foreign-key one.
ReferenceWrite = Callable[[OwnerScope, OwnedRows, UUID], Executable]

REFERENCE_WRITES: dict[str, tuple[str, ReferenceWrite]] = {
    "version_to_document": (
        "document_id",
        lambda owner, own, ref: insert(DocumentVersion).values(
            owner_id=owner.owner_id,
            document_id=ref,
            version_no=1,
            content_sha256=b"\x01" * 32,
            byte_size=1,
            file_key="k",
            state="queued",
        ),
    ),
    "current_version_of_document": (
        "version_id",
        lambda owner, own, ref: (
            update(Document).where(Document.id == own.document_id).values(current_version_id=ref)
        ),
    ),
    "job_to_version": (
        "version_id",
        lambda owner, own, ref: insert(IngestionJob).values(
            owner_id=owner.owner_id, version_id=ref, status="queued", next_attempt_at=EPOCH
        ),
    ),
    "chunk_to_document": (
        "document_id",
        lambda owner, own, ref: insert(Chunk).values(
            _chunk_values(own, owner, document_id=ref, version_id=own.version_id, ordinal=1)
        ),
    ),
    "chunk_to_version": (
        "version_id",
        lambda owner, own, ref: insert(Chunk).values(
            _chunk_values(own, owner, document_id=own.document_id, version_id=ref, ordinal=0)
        ),
    ),
    "turn_to_conversation": (
        "conversation_id",
        lambda owner, own, ref: insert(Turn).values(
            owner_id=owner.owner_id,
            conversation_id=ref,
            client_request_id=own.client_request_id,
            kind="question",
            status="generating",
        ),
    ),
    "source_to_turn": (
        "turn_id",
        lambda owner, own, ref: insert(TurnSource).values(
            _source_values(owner, turn_id=ref, label="S1")
        ),
    ),
    "source_to_document": (
        "document_id",
        lambda owner, own, ref: insert(TurnSource).values(
            _source_values(owner, turn_id=own.turn_id, label="S2", document_id=ref)
        ),
    ),
    "source_to_version": (
        "version_id",
        lambda owner, own, ref: insert(TurnSource).values(
            _source_values(owner, turn_id=own.turn_id, label="S3", version_id=ref)
        ),
    ),
}


@pytest.mark.parametrize("case", sorted(REFERENCE_WRITES))
async def test_reference_to_another_owners_row_fails_like_a_missing_one(
    app_sessions: async_sessionmaker[AsyncSession], case: str
) -> None:
    parent, write = REFERENCE_WRITES[case]
    owner_a: OwnerScope = await create_owner(app_sessions)
    owner_b: OwnerScope = await create_owner(app_sessions)
    try:
        config_id: int = await _insert_embedding_config(app_sessions)
        rows_a: OwnedRows = await _insert_owned_rows(app_sessions, owner_a, config_id)
        rows_b: OwnedRows = await _insert_owned_rows(app_sessions, owner_b, config_id)
        # Owner A's rows, but reusing B's client request id so that a turn would collide with B's.
        acting_rows: OwnedRows = replace(rows_a, client_request_id=rows_b.client_request_id)
        foreign_id: UUID = getattr(rows_b, parent)

        foreign: str = await _failure(
            app_sessions, owner_a, write(owner_a, acting_rows, foreign_id)
        )
        missing: str = await _failure(app_sessions, owner_a, write(owner_a, acting_rows, uuid7()))
    finally:
        await _delete_owner(app_sessions, owner_a)
        await _delete_owner(app_sessions, owner_b)
    assert foreign == missing == ForeignKeyViolation.sqlstate


async def test_deleting_an_owner_with_a_current_version(
    app_sessions: async_sessionmaker[AsyncSession], database_urls: TestDatabaseUrls
) -> None:
    owner: OwnerScope = await create_owner(app_sessions)
    config_id: int = await _insert_embedding_config(app_sessions)
    rows: OwnedRows = await _insert_owned_rows(app_sessions, owner, config_id)
    async with owner_session(app_sessions, owner) as session:
        document: Document | None = await session.get(Document, rows.document_id)
        assert document is not None and document.current_version_id == rows.version_id

    await _delete_owner(app_sessions, owner)

    async with admin_connection(database_urls.admin) as connection:
        documents_left: int | None = await connection.scalar(
            select(func.count()).select_from(Document).where(Document.owner_id == owner.owner_id)
        )
        versions_left: int | None = await connection.scalar(
            select(func.count())
            .select_from(DocumentVersion)
            .where(DocumentVersion.owner_id == owner.owner_id)
        )
    assert documents_left == versions_left == 0


async def test_deleting_a_document_keeps_its_cited_sources(
    app_sessions: async_sessionmaker[AsyncSession],
) -> None:
    owner: OwnerScope = await create_owner(app_sessions)
    try:
        config_id: int = await _insert_embedding_config(app_sessions)
        rows: OwnedRows = await _insert_owned_rows(app_sessions, owner, config_id)
        async with owner_session(app_sessions, owner) as session:
            await session.execute(delete(Document).where(Document.id == rows.document_id))
        async with owner_session(app_sessions, owner) as session:
            source: TurnSource | None = await session.get(
                TurnSource, (owner.owner_id, rows.turn_id, "S1")
            )
            versions: Sequence[DocumentVersion] = (
                await session.scalars(select(DocumentVersion))
            ).all()
    finally:
        await _delete_owner(app_sessions, owner)
    assert source is not None
    assert (source.document_id, source.version_id) == (None, None)
    assert source.document_name_snapshot == "job.pdf"
    assert versions == []


def _anonymous_session(
    owner: OwnerScope,
    now: datetime,
    *,
    idle_expires_at: datetime | None = None,
    absolute_expires_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> AnonymousSession:
    return AnonymousSession(
        owner_id=owner.owner_id,
        token_hash=hashlib.sha256(uuid7().bytes).digest(),
        created_at=now,
        last_active_at=now,
        idle_expires_at=idle_expires_at or now + timedelta(hours=24),
        absolute_expires_at=absolute_expires_at or now + timedelta(days=7),
        ended_at=ended_at,
    )


async def _resolve(
    sessions: async_sessionmaker[AsyncSession], token_hash: bytes, now: datetime
) -> list[tuple[UUID, UUID]]:
    async with system_session(sessions) as session:
        rows: Sequence[Row[UUID, UUID]] = (
            await session.execute(
                text("SELECT session_id, owner_id FROM sourcehaven_resolve_session(:hash, :now)"),
                {"hash": token_hash, "now": now},
            )
        ).all()
    return [(session_id, owner_id) for session_id, owner_id in rows]


async def _claim(
    sessions: async_sessionmaker[AsyncSession], now: datetime
) -> list[tuple[UUID, UUID, UUID]]:
    async with system_session(sessions) as session:
        rows: Sequence[Row[UUID, UUID, UUID]] = (
            await session.execute(
                text(
                    "SELECT job_id, owner_id, version_id"
                    " FROM sourcehaven_claim_ingestion_job(:lease, :now)"
                ),
                {"lease": 300, "now": now},
            )
        ).all()
    return [(job_id, owner_id, version_id) for job_id, owner_id, version_id in rows]


async def _insert_version(
    sessions: async_sessionmaker[AsyncSession], owner: OwnerScope
) -> DocumentVersion:
    document_id: UUID = await insert_document(sessions, owner, display_name="job.pdf")
    version: DocumentVersion = DocumentVersion(
        id=uuid7(),
        owner_id=owner.owner_id,
        document_id=document_id,
        version_no=1,
        content_sha256=hashlib.sha256(uuid7().bytes).digest(),
        byte_size=1024,
        file_key=f"{owner.owner_id}/{document_id}/v1.pdf",
        state="queued",
    )
    async with owner_session(sessions, owner) as session:
        session.add(version)
    return version


async def _insert_job(
    sessions: async_sessionmaker[AsyncSession],
    owner: OwnerScope,
    *,
    next_attempt_at: datetime,
    order: int,
) -> IngestionJob:
    version: DocumentVersion = await _insert_version(sessions, owner)
    job: IngestionJob = IngestionJob(
        owner_id=owner.owner_id,
        version_id=version.id,
        status="queued",
        next_attempt_at=next_attempt_at,
        created_at=EPOCH + timedelta(seconds=order),
    )
    async with owner_session(sessions, owner) as session:
        session.add(job)
    return job


async def _failure(
    sessions: async_sessionmaker[AsyncSession], owner: OwnerScope, statement: Executable
) -> str:
    """Run `statement` in an owner transaction and return the SQLSTATE it fails with."""
    with pytest.raises(IntegrityError) as raised:
        async with owner_session(sessions, owner) as session:
            await session.execute(statement)
    sqlstate: str | None = getattr(raised.value.orig, "sqlstate", None)
    assert sqlstate is not None
    return sqlstate


async def _insert_embedding_config(sessions: async_sessionmaker[AsyncSession]) -> int:
    config: EmbeddingConfigRow = _embedding_config()
    async with system_session(sessions) as session:
        session.add(config)
    return config.id


async def _insert_owned_rows(
    sessions: async_sessionmaker[AsyncSession], owner: OwnerScope, embedding_config_id: int
) -> OwnedRows:
    """Create a document with a current version, job and chunk, and a generating cited turn."""
    version: DocumentVersion = await _insert_version(sessions, owner)
    conversation: Conversation = Conversation(id=uuid7(), owner_id=owner.owner_id)
    turn: Turn = _turn(owner, conversation.id)
    turn.status = "generating"
    async with owner_session(sessions, owner) as session:
        await session.execute(
            update(Document)
            .where(Document.id == version.document_id)
            .values(current_version_id=version.id)
        )
        session.add(
            IngestionJob(
                owner_id=owner.owner_id,
                version_id=version.id,
                status="succeeded",
                next_attempt_at=EPOCH,
            )
        )
        session.add(_chunk(owner, version, embedding_config_id))
        session.add(conversation)
        await session.flush()
        session.add(turn)
        await session.flush()
        session.add(_turn_source(owner, turn.id, version))
    return OwnedRows(
        document_id=version.document_id,
        version_id=version.id,
        conversation_id=conversation.id,
        turn_id=turn.id,
        client_request_id=turn.client_request_id,
        embedding_config_id=embedding_config_id,
    )


def _chunk_values(
    own: OwnedRows, owner: OwnerScope, *, document_id: UUID, version_id: UUID, ordinal: int
) -> dict[str, object]:
    return {
        "owner_id": owner.owner_id,
        "document_id": document_id,
        "version_id": version_id,
        "embedding_config_id": own.embedding_config_id,
        "ordinal": ordinal,
        "text": "x",
        "token_count": 1,
        "page_start": 1,
        "page_end": 1,
        "char_start": 0,
        "char_end": 1,
        "embedding": [1.0, 0.0, 0.0],
    }


def _source_values(
    owner: OwnerScope,
    *,
    turn_id: UUID,
    label: str,
    document_id: UUID | None = None,
    version_id: UUID | None = None,
) -> dict[str, object]:
    return {
        "owner_id": owner.owner_id,
        "turn_id": turn_id,
        "label": label,
        "cited": True,
        "document_id": document_id,
        "version_id": version_id,
        "document_name_snapshot": "x.pdf",
        "page_start": 1,
        "page_end": 1,
        "quote_snapshot": "x",
    }


def _embedding_config() -> EmbeddingConfigRow:
    return EmbeddingConfigRow(
        fingerprint=uuid7().hex,
        provider="hash",
        model_id="hash-bow",
        model_revision="1",
        dimensions=3,
        query_prefix="",
        document_prefix="",
        normalize=True,
        max_input_tokens=2048,
        distance="cosine",
        chunk_tokens=400,
        chunk_overlap=60,
    )


def _chunk(owner: OwnerScope, version: DocumentVersion, embedding_config_id: int) -> Chunk:
    return Chunk(
        owner_id=owner.owner_id,
        document_id=version.document_id,
        version_id=version.id,
        embedding_config_id=embedding_config_id,
        ordinal=0,
        text="Synthetic chunk.",
        token_count=2,
        page_start=1,
        page_end=1,
        char_start=0,
        char_end=16,
        embedding=[1.0, 0.0, 0.0],
    )


def _turn(owner: OwnerScope, conversation_id: UUID) -> Turn:
    return Turn(
        id=uuid7(),
        owner_id=owner.owner_id,
        conversation_id=conversation_id,
        client_request_id=uuid7(),
        kind="question",
        question="What is this?",
        status="complete",
        text="An answer [S1].",
    )


def _turn_source(owner: OwnerScope, turn_id: UUID, version: DocumentVersion) -> TurnSource:
    return TurnSource(
        owner_id=owner.owner_id,
        turn_id=turn_id,
        label="S1",
        cited=True,
        document_id=version.document_id,
        version_id=version.id,
        document_name_snapshot="job.pdf",
        page_start=1,
        page_end=1,
        quote_snapshot="Synthetic chunk.",
    )


async def _delete_owner(sessions: async_sessionmaker[AsyncSession], owner: OwnerScope) -> None:
    async with owner_session(sessions, owner) as session:
        await session.execute(delete(Owner).where(Owner.id == owner.owner_id))
