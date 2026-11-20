"""ORM models for the database schema (design spec section 5.2).

Every table except `embedding_configs` holds visitor data: it carries `owner_id`, its foreign keys
cascade from `owners`, and the baseline migration protects it with forced row-level security.

Foreign-key and unique checks bypass row-level security, so references between owner data include
`owner_id` (`(owner_id, document_id) -> documents (owner_id, id)`), and every unique key holding a
reference column starts with `owner_id`. A reference to another owner's row then fails exactly like
a reference to a nonexistent one. Unique indexes are checked as each row is inserted, before the
statement-end foreign-key check, so a global key would otherwise report a collision first.
"""

from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID, uuid7

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: DateTime(timezone=True),
        UUID: Uuid(),
        bytes: LargeBinary(),
        str: Text(),
    }


def _owner_fk(*, index: bool = True) -> Mapped[UUID]:
    return mapped_column(ForeignKey("owners.id", ondelete="CASCADE"), index=index)


def _owned_fk(
    column: str, parent_table: str, *, ondelete: str, use_alter: bool = False
) -> ForeignKeyConstraint:
    # Foreign-key checks bypass row-level security, so a plain key on `column` would accept another
    # owner's parent id. Including owner_id makes such a reference fail like a nonexistent id.
    return ForeignKeyConstraint(
        ["owner_id", column],
        [f"{parent_table}.owner_id", f"{parent_table}.id"],
        ondelete=ondelete,
        use_alter=use_alter,
    )


def _owned_fk_set_null(
    column: str, parent_table: str, *, use_alter: bool = False
) -> ForeignKeyConstraint:
    # Only the reference column is cleared; owner_id stays (PostgreSQL 15+ column list).
    return _owned_fk(column, parent_table, ondelete=f"SET NULL ({column})", use_alter=use_alter)


def _created_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


def _one_of(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    allowed: str = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


class Owner(Base):
    __tablename__ = "owners"
    __table_args__ = (_one_of("kind", ("anonymous_session", "account"), "kind"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    kind: Mapped[str]
    created_at: Mapped[datetime] = _created_at()


class AnonymousSession(Base):
    __tablename__ = "anonymous_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    owner_id: Mapped[UUID] = _owner_fk()
    token_hash: Mapped[bytes] = mapped_column(unique=True)
    created_at: Mapped[datetime] = _created_at()
    last_active_at: Mapped[datetime]
    idle_expires_at: Mapped[datetime]
    absolute_expires_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]


class EmbeddingConfigRow(Base):
    """A registered embedding configuration; shared by all owners and not owner-scoped."""

    __tablename__ = "embedding_configs"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(unique=True)
    provider: Mapped[str]
    model_id: Mapped[str]
    model_revision: Mapped[str | None]
    dimensions: Mapped[int]
    query_prefix: Mapped[str]
    document_prefix: Mapped[str]
    normalize: Mapped[bool]
    max_input_tokens: Mapped[int]
    distance: Mapped[str]
    chunk_tokens: Mapped[int]
    chunk_overlap: Mapped[int]
    created_at: Mapped[datetime] = _created_at()


class Document(Base):
    __tablename__ = "documents"
    # The unique key makes concurrent uploads of the same file by one owner create one document.
    __table_args__ = (
        UniqueConstraint("owner_id", "content_sha256"),
        UniqueConstraint("owner_id", "id"),
        _owned_fk_set_null("current_version_id", "document_versions", use_alter=True),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    owner_id: Mapped[UUID] = _owner_fk(index=False)
    display_name: Mapped[str]
    content_sha256: Mapped[bytes]
    current_version_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = _created_at()


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("owner_id", "document_id", "version_no"),
        UniqueConstraint("owner_id", "id"),
        _owned_fk("document_id", "documents", ondelete="CASCADE"),
        _one_of("state", ("queued", "processing", "ready", "failed", "superseded"), "state"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    owner_id: Mapped[UUID] = _owner_fk(index=False)
    document_id: Mapped[UUID]
    version_no: Mapped[int]
    content_sha256: Mapped[bytes]
    byte_size: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int | None]
    file_key: Mapped[str]
    token_count: Mapped[int | None]
    parser_name: Mapped[str | None]
    parser_version: Mapped[str | None]
    chunker_fingerprint: Mapped[str | None]
    embedding_config_id: Mapped[int | None] = mapped_column(ForeignKey("embedding_configs.id"))
    ingestion_fingerprint: Mapped[str | None]
    state: Mapped[str]
    error_code: Mapped[str | None]
    skipped_pages: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=sql_text("'{}'::integer[]")
    )
    created_at: Mapped[datetime] = _created_at()
    ready_at: Mapped[datetime | None]


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        Index(None, "status", "next_attempt_at"),
        UniqueConstraint("owner_id", "version_id"),
        _owned_fk("version_id", "document_versions", ondelete="CASCADE"),
        _one_of("status", ("queued", "running", "retry", "succeeded", "failed"), "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    owner_id: Mapped[UUID] = _owner_fk(index=False)
    version_id: Mapped[UUID]
    status: Mapped[str]
    stage: Mapped[str | None]
    progress_done: Mapped[int] = mapped_column(server_default=sql_text("0"))
    progress_total: Mapped[int] = mapped_column(server_default=sql_text("0"))
    attempts: Mapped[int] = mapped_column(server_default=sql_text("0"))
    lease_expires_at: Mapped[datetime | None]
    next_attempt_at: Mapped[datetime]
    last_error_code: Mapped[str | None]
    created_at: Mapped[datetime] = _created_at()


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index(None, "owner_id", "document_id"),
        UniqueConstraint("owner_id", "version_id", "ordinal"),
        _owned_fk("document_id", "documents", ondelete="CASCADE"),
        _owned_fk("version_id", "document_versions", ondelete="CASCADE"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    owner_id: Mapped[UUID] = _owner_fk(index=False)
    document_id: Mapped[UUID]
    version_id: Mapped[UUID]
    embedding_config_id: Mapped[int] = mapped_column(ForeignKey("embedding_configs.id"))
    ordinal: Mapped[int]
    text: Mapped[str]
    token_count: Mapped[int]
    page_start: Mapped[int]
    page_end: Mapped[int]
    # Offsets into the concatenated version text, used to rebuild sections without overlap.
    char_start: Mapped[int]
    char_end: Mapped[int]
    heading: Mapped[str | None]
    # No fixed dimension: each embedding configuration has its own, and queries filter by config.
    embedding: Mapped[list[float]] = mapped_column(Vector())


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("owner_id", "id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    owner_id: Mapped[UUID] = _owner_fk(index=False)
    created_at: Mapped[datetime] = _created_at()


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (
        UniqueConstraint("owner_id", "conversation_id", "client_request_id"),
        UniqueConstraint("owner_id", "id"),
        _owned_fk("conversation_id", "conversations", ondelete="CASCADE"),
        # At most one answer per conversation may be generating at a time.
        Index(
            "uq_turns_owner_id_conversation_id_generating",
            "owner_id",
            "conversation_id",
            unique=True,
            postgresql_where=sql_text("status = 'generating'"),
        ),
        _one_of("kind", ("question", "summary"), "kind"),
        _one_of("status", ("generating", "complete", "interrupted", "failed"), "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    owner_id: Mapped[UUID] = _owner_fk(index=False)
    conversation_id: Mapped[UUID]
    client_request_id: Mapped[UUID]
    kind: Mapped[str]
    question: Mapped[str | None]
    selected_document_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid()), server_default=sql_text("'{}'::uuid[]")
    )
    status: Mapped[str]
    text: Mapped[str] = mapped_column(server_default=sql_text("''"))
    error_code: Mapped[str | None]
    model: Mapped[str | None]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    cost_micro_usd: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = _created_at()
    completed_at: Mapped[datetime | None]


class TurnSource(Base):
    """A source shown with an answer; snapshots keep it readable after its document is deleted."""

    __tablename__ = "turn_sources"
    __table_args__ = (
        _owned_fk("turn_id", "turns", ondelete="CASCADE"),
        _owned_fk_set_null("document_id", "documents"),
        _owned_fk_set_null("version_id", "document_versions"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), primary_key=True
    )
    turn_id: Mapped[UUID] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(primary_key=True)
    cited: Mapped[bool]
    document_id: Mapped[UUID | None]
    version_id: Mapped[UUID | None]
    document_name_snapshot: Mapped[str]
    page_start: Mapped[int]
    page_end: Mapped[int]
    quote_snapshot: Mapped[str]
