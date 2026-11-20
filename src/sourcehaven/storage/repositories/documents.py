from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid7

from sqlalchemy import Result, Row, ScalarSelect, Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from sourcehaven.domain.models import OwnerScope
from sourcehaven.storage.models import Document, DocumentVersion, IngestionJob

IN_PROGRESS_JOB_STATUSES: tuple[str, ...] = ("queued", "running", "retry")


@dataclass(frozen=True)
class DocumentView:
    """A document with the state of its current (else latest) version and its job progress."""

    id: UUID
    display_name: str
    state: str
    error_code: str | None
    page_count: int | None
    progress_stage: str | None
    progress_done: int | None
    progress_total: int | None
    created_at: datetime


@dataclass(frozen=True)
class NewDocument:
    """The identifiers and content facts of a first upload."""

    display_name: str
    content_sha256: bytes
    byte_size: int
    owner: OwnerScope
    document_id: UUID
    version_id: UUID
    file_key: str
    now: datetime


async def lock_owner_uploads(session: AsyncSession, owner: OwnerScope) -> None:
    """Serialise this owner's uploads until the transaction ends.

    Holds a transaction-scoped advisory lock keyed by the owner, so the document-count check and
    the insert that follows cannot interleave with another upload by the same owner.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:owner, 0))"),
        {"owner": str(owner.owner_id)},
    )


async def get_document(
    session: AsyncSession, owner: OwnerScope, document_id: UUID
) -> Document | None:
    """Load one of the owner's documents; another owner's id behaves like an unknown one."""
    document: Document | None = await session.scalar(
        select(Document).where(Document.owner_id == owner.owner_id, Document.id == document_id)
    )
    return document


async def find_by_content_hash(
    session: AsyncSession, owner: OwnerScope, content_sha256: bytes
) -> UUID | None:
    """Return the id of the owner's document with this content, if any."""
    result: Result[UUID] = await session.execute(
        select(Document.id).where(
            Document.owner_id == owner.owner_id, Document.content_sha256 == content_sha256
        )
    )
    return result.scalar_one_or_none()


async def count_documents(session: AsyncSession, owner: OwnerScope) -> int:
    result: Result[int] = await session.execute(
        select(func.count()).select_from(Document).where(Document.owner_id == owner.owner_id)
    )
    return result.scalar_one()


async def add_queued_document(session: AsyncSession, new: NewDocument) -> None:
    """Insert a document, its first version and its ingestion job, all queued.

    Flushes, so a duplicate `(owner_id, content_sha256)` raises `IntegrityError` here.
    The caller's transaction must be an `owner_session`.
    """
    owner_id: UUID = new.owner.owner_id
    session.add(
        Document(
            id=new.document_id,
            owner_id=owner_id,
            display_name=new.display_name,
            content_sha256=new.content_sha256,
            created_at=new.now,
        )
    )
    await session.flush()
    session.add(
        DocumentVersion(
            id=new.version_id,
            owner_id=owner_id,
            document_id=new.document_id,
            version_no=1,
            content_sha256=new.content_sha256,
            byte_size=new.byte_size,
            file_key=new.file_key,
            state="queued",
        )
    )
    await session.flush()
    session.add(
        IngestionJob(
            id=uuid7(),
            owner_id=owner_id,
            version_id=new.version_id,
            status="queued",
            next_attempt_at=new.now,
        )
    )
    await session.flush()


def _view(document: Document, version: DocumentVersion, job: IngestionJob | None) -> DocumentView:
    working: bool = job is not None and job.status in IN_PROGRESS_JOB_STATUSES
    return DocumentView(
        id=document.id,
        display_name=document.display_name,
        state=version.state,
        error_code=version.error_code,
        page_count=version.page_count,
        progress_stage=job.stage if job is not None and working else None,
        progress_done=job.progress_done if job is not None and working else None,
        progress_total=job.progress_total if job is not None and working else None,
        created_at=document.created_at,
    )


def _views_statement(owner: OwnerScope) -> Select[Document, DocumentVersion, IngestionJob]:
    latest_version_id: ScalarSelect[UUID] = (
        select(DocumentVersion.id)
        .where(
            DocumentVersion.owner_id == owner.owner_id,
            DocumentVersion.document_id == Document.id,
        )
        .order_by(DocumentVersion.version_no.desc())
        .limit(1)
        .correlate(Document)
        .scalar_subquery()
    )
    return (
        select(Document, DocumentVersion, IngestionJob)
        .join(
            DocumentVersion,
            (DocumentVersion.owner_id == owner.owner_id)
            & (DocumentVersion.id == func.coalesce(Document.current_version_id, latest_version_id)),
        )
        .outerjoin(
            IngestionJob,
            (IngestionJob.owner_id == owner.owner_id)
            & (IngestionJob.version_id == DocumentVersion.id),
        )
        .where(Document.owner_id == owner.owner_id)
    )


async def list_document_views(session: AsyncSession, owner: OwnerScope) -> list[DocumentView]:
    """List the owner's documents, newest first."""
    rows: Result[Document, DocumentVersion, IngestionJob] = await session.execute(
        _views_statement(owner).order_by(Document.created_at.desc(), Document.id.desc())
    )
    return [_view(document, version, job) for document, version, job in rows]


async def get_document_view(
    session: AsyncSession, owner: OwnerScope, document_id: UUID
) -> DocumentView | None:
    result: Result[Document, DocumentVersion, IngestionJob] = await session.execute(
        _views_statement(owner).where(Document.id == document_id)
    )
    row: Row[Document, DocumentVersion, IngestionJob] | None = result.one_or_none()
    return None if row is None else _view(*row)
