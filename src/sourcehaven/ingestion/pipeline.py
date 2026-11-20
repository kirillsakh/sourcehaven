"""Turns a claimed ingestion job into published, embedded chunks (design spec section 6.1).

Every database step runs in its own `owner_session` for the job's owner, and every query filters
on that owner explicitly as well (design spec section 5.1). A job is fenced by the
attempt number its claim produced: the claim function increments `attempts`, so once a lease has
expired and another worker has claimed the job, the earlier worker's writes find a different
attempt number and are abandoned instead of racing the new holder.
"""

import asyncio
import logging
import shutil
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sourcehaven.config import Settings
from sourcehaven.domain.models import ChunkDraft, ExtractedSource, OwnerScope
from sourcehaven.embeddings.protocol import Embedder, EmbedderUnavailable, TokenCounter
from sourcehaven.ingestion.chunking import chunk_pages
from sourcehaven.ingestion.errors import IngestionError
from sourcehaven.ingestion.pdf import SourceAdapter
from sourcehaven.storage.db import owner_session
from sourcehaven.storage.files import FileStore
from sourcehaven.storage.models import Chunk, Document, DocumentVersion, IngestionJob
from sourcehaven.storage.repositories.chunks import replace_version_chunks

logger: logging.Logger = logging.getLogger(__name__)

JOB_LEASE: Final[timedelta] = timedelta(seconds=300)
MAX_ATTEMPTS: Final[int] = 3
RETRY_DELAYS: Final[tuple[timedelta, ...]] = (
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
)
EMBEDDING_BATCH_SIZE: Final[int] = 32


@dataclass(frozen=True)
class ClaimedJob:
    """A job this worker has claimed; the owner comes from the job row, never from a client."""

    job_id: UUID
    owner: OwnerScope
    version_id: UUID


@dataclass(frozen=True)
class _Attempt:
    number: int
    document_id: UUID
    file_key: str


@dataclass(frozen=True)
class _Prepared:
    source: ExtractedSource
    drafts: list[ChunkDraft]
    token_count: int


class _LeaseLost(Exception):
    """The job was deleted or claimed again by another worker after this lease expired."""


class IngestionPipeline:
    """Parses, chunks, embeds and publishes one claimed document version."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        file_store: FileStore,
        adapter: SourceAdapter,
        embedder: Embedder,
        counter: TokenCounter,
        settings: Settings,
        embedding_config_id: int,
        clock: Callable[[], datetime],
    ) -> None:
        self._sessions: async_sessionmaker[AsyncSession] = sessions
        self._file_store: FileStore = file_store
        self._adapter: SourceAdapter = adapter
        self._embedder: Embedder = embedder
        self._counter: TokenCounter = counter
        self._settings: Settings = settings
        self._embedding_config_id: int = embedding_config_id
        self._clock: Callable[[], datetime] = clock

    async def process(self, job: ClaimedJob) -> None:
        """Ingest the job's version and publish it, or record why it failed.

        An `IngestionError` that is retryable puts the job back in the queue with a backoff until
        it has run `MAX_ATTEMPTS` times; any other error fails the version with its code. Other
        exceptions count as a retryable `internal` error. A job claimed more than `MAX_ATTEMPTS`
        times, which happens when workers crash while holding it, fails as `internal` unprocessed.

        Raises:
            Exception: Database errors while starting the attempt or recording its outcome; the
                job then stays leased and is claimed again once the lease expires.
        """
        attempt: _Attempt | None = await self._begin(job)
        if attempt is None:
            return
        try:
            await self._ingest(job, attempt)
        except _LeaseLost:
            logger.warning("ingestion job %s lost its lease; abandoning attempt", job.job_id)
        except IngestionError as error:
            await self._record_failure(job, attempt, error)
        except Exception as error:
            # Parser and embedder messages may quote the document, so only the class is logged.
            logger.warning(
                "ingestion job %s for document %s raised %s",
                job.job_id,
                attempt.document_id,
                type(error).__name__,
            )
            await self._record_failure(job, attempt, IngestionError("internal", retryable=True))

    async def _begin(self, job: ClaimedJob) -> _Attempt | None:
        async with owner_session(self._sessions, job.owner) as session:
            row: IngestionJob | None = await _lock_job(session, job.owner, job.job_id)
            version: DocumentVersion | None = await _get_version(session, job.owner, job.version_id)
            if row is None or version is None or row.status != "running":
                return None
            attempt: _Attempt = _Attempt(
                number=row.attempts, document_id=version.document_id, file_key=version.file_key
            )
            if row.attempts > MAX_ATTEMPTS:
                _fail(row, version, "internal")
                logger.warning(
                    "ingestion job %s for document %s exceeded %d attempts; failed as internal",
                    job.job_id,
                    attempt.document_id,
                    MAX_ATTEMPTS,
                )
                return None
            version.state = "processing"
            version.error_code = None
            _set_progress(row, "parsing", done=0, total=0, lease_until=self._lease_until())
            return attempt

    async def _ingest(self, job: ClaimedJob, attempt: _Attempt) -> None:
        prepared: _Prepared = await asyncio.to_thread(self._prepare, attempt.file_key)
        total: int = len(prepared.drafts)
        await self._update_progress(job, attempt, "embedding", done=0, total=total)
        vectors: list[list[float]] = []
        for start in range(0, total, EMBEDDING_BATCH_SIZE):
            batch: list[ChunkDraft] = prepared.drafts[start : start + EMBEDDING_BATCH_SIZE]
            vectors.extend(await self._embed([draft.text for draft in batch]))
            done: int = len(vectors)
            stage: str = "publishing" if done == total else "embedding"
            await self._update_progress(job, attempt, stage, done=done, total=total)
        await self._publish(job, attempt, prepared, vectors)
        logger.info("ingestion job %s for document %s succeeded", job.job_id, attempt.document_id)

    def _prepare(self, file_key: str) -> _Prepared:
        """Extract and chunk the stored file; runs in a worker thread because it is CPU-bound."""
        with tempfile.TemporaryDirectory(prefix="sourcehaven-ingest-") as scratch:
            local_copy: Path = Path(scratch) / "source.pdf"
            try:
                with self._file_store.open(file_key) as stored, local_copy.open("wb") as copy:
                    shutil.copyfileobj(stored, copy)
            except FileNotFoundError as error:
                # The adapter would report an unreadable path as a damaged PDF, but a lost upload
                # is our fault and will not reappear on retry.
                raise IngestionError("internal") from error
            source: ExtractedSource = self._adapter.extract(
                local_copy, max_pages=self._settings.max_pages_per_document
            )
        text_pages: list[str] = [page.text for page in source.pages if page.has_text_layer]
        if not text_pages:
            raise IngestionError("empty")
        # Chunk limits come from the embedding configuration recorded on the version, so the
        # stored chunks always match the configuration they claim to be embedded with.
        drafts: list[ChunkDraft] = chunk_pages(
            source.pages,
            self._counter,
            chunk_tokens=self._embedder.config.chunk_tokens,
            chunk_overlap=self._embedder.config.chunk_overlap,
        )
        if not drafts:
            raise IngestionError("empty")
        token_count: int = sum(self._counter.count(text) for text in text_pages)
        return _Prepared(source=source, drafts=drafts, token_count=token_count)

    async def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            return await self._embedder.embed_documents(texts)
        except EmbedderUnavailable as error:
            raise IngestionError("embedding_unavailable", retryable=True) from error
        except httpx.HTTPStatusError as error:
            # TEI rejected the request itself (for example an over-long input); retrying the
            # same chunks would be rejected again.
            raise IngestionError("internal") from error

    async def _update_progress(
        self, job: ClaimedJob, attempt: _Attempt, stage: str, *, done: int, total: int
    ) -> None:
        async with owner_session(self._sessions, job.owner) as session:
            row: IngestionJob = await _fenced_job(session, job, attempt)
            _set_progress(row, stage, done=done, total=total, lease_until=self._lease_until())

    async def _publish(
        self,
        job: ClaimedJob,
        attempt: _Attempt,
        prepared: _Prepared,
        vectors: list[list[float]],
    ) -> None:
        """Make the version queryable in one transaction (design spec section 6.1, step 8)."""
        owner_id: UUID = job.owner.owner_id
        chunks: list[Chunk] = [
            Chunk(
                owner_id=owner_id,
                document_id=attempt.document_id,
                version_id=job.version_id,
                embedding_config_id=self._embedding_config_id,
                ordinal=draft.ordinal,
                text=draft.text,
                token_count=draft.token_count,
                page_start=draft.span.start,
                page_end=draft.span.end,
                char_start=draft.char_start,
                char_end=draft.char_end,
                embedding=vector,
            )
            for draft, vector in zip(prepared.drafts, vectors, strict=True)
        ]
        async with owner_session(self._sessions, job.owner) as session:
            document: Document | None = await _lock_document(
                session, job.owner, attempt.document_id
            )
            if document is None:
                raise _LeaseLost
            row: IngestionJob = await _fenced_job(session, job, attempt)
            version: DocumentVersion | None = await _get_version(session, job.owner, job.version_id)
            if version is None:
                raise _LeaseLost
            await replace_version_chunks(session, job.owner, job.version_id, chunks)
            version.state = "ready"
            version.error_code = None
            version.page_count = prepared.source.page_count
            version.token_count = prepared.token_count
            version.parser_name = prepared.source.parser_name
            version.parser_version = prepared.source.parser_version
            version.embedding_config_id = self._embedding_config_id
            version.ready_at = self._clock()
            document.current_version_id = job.version_id
            row.status = "succeeded"
            row.lease_expires_at = None
            row.last_error_code = None

    async def _record_failure(
        self, job: ClaimedJob, attempt: _Attempt, error: IngestionError
    ) -> None:
        async with owner_session(self._sessions, job.owner) as session:
            try:
                row: IngestionJob = await _fenced_job(session, job, attempt)
            except _LeaseLost:
                logger.warning("ingestion job %s lost its lease before failing", job.job_id)
                return
            if error.retryable and attempt.number < MAX_ATTEMPTS:
                row.status = "retry"
                row.next_attempt_at = self._clock() + RETRY_DELAYS[attempt.number - 1]
                row.lease_expires_at = None
                row.last_error_code = error.code
                logger.warning(
                    "ingestion job %s for document %s will retry after %s",
                    job.job_id,
                    attempt.document_id,
                    error.code,
                )
                return
            version: DocumentVersion | None = await _get_version(session, job.owner, job.version_id)
            if version is None:
                return
            _fail(row, version, error.code)
            logger.warning(
                "ingestion job %s for document %s failed with %s",
                job.job_id,
                attempt.document_id,
                error.code,
            )

    def _lease_until(self) -> datetime:
        return self._clock() + JOB_LEASE


async def _lock_job(session: AsyncSession, owner: OwnerScope, job_id: UUID) -> IngestionJob | None:
    job: IngestionJob | None = await session.scalar(
        select(IngestionJob)
        .where(IngestionJob.owner_id == owner.owner_id, IngestionJob.id == job_id)
        .with_for_update()
    )
    return job


async def _lock_document(
    session: AsyncSession, owner: OwnerScope, document_id: UUID
) -> Document | None:
    """Lock the document row so that it cannot be removed until the transaction ends.

    Removal locks the document before its cascade reaches the job row, so publishing takes the
    document before the job too; the opposite order lets the two deadlock.
    """
    document: Document | None = await session.scalar(
        select(Document)
        .where(Document.owner_id == owner.owner_id, Document.id == document_id)
        .with_for_update(key_share=True)  # renders FOR NO KEY UPDATE on PostgreSQL
    )
    return document


async def _get_version(
    session: AsyncSession, owner: OwnerScope, version_id: UUID
) -> DocumentVersion | None:
    version: DocumentVersion | None = await session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.owner_id == owner.owner_id, DocumentVersion.id == version_id
        )
    )
    return version


async def _fenced_job(session: AsyncSession, job: ClaimedJob, attempt: _Attempt) -> IngestionJob:
    """Lock the job row and check this attempt still holds it.

    Raises:
        _LeaseLost: If the job is gone, no longer running, or was claimed again since.
    """
    row: IngestionJob | None = await _lock_job(session, job.owner, job.job_id)
    if row is None or row.status != "running" or row.attempts != attempt.number:
        raise _LeaseLost
    return row


def _set_progress(
    row: IngestionJob, stage: str, *, done: int, total: int, lease_until: datetime
) -> None:
    row.stage = stage
    row.progress_done = done
    row.progress_total = total
    row.lease_expires_at = lease_until


def _fail(row: IngestionJob, version: DocumentVersion, code: str) -> None:
    row.status = "failed"
    row.lease_expires_at = None
    row.last_error_code = code
    version.state = "failed"
    version.error_code = code
