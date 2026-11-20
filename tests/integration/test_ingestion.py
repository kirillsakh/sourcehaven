import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from sourcehaven.composition import AppContainer, ContainerOverrides, build_ingestion_pipeline
from sourcehaven.domain.models import OwnerScope
from sourcehaven.embeddings.config import EmbeddingConfig
from sourcehaven.embeddings.hashing import HashEmbedder
from sourcehaven.ingestion.pipeline import JOB_LEASE, ClaimedJob
from sourcehaven.storage.db import owner_session
from sourcehaven.storage.models import Document, DocumentVersion, IngestionJob
from sourcehaven.worker.runner import claim_job, run_once, run_worker
from tests.support.clock import FakeClock
from tests.support.db import TestDatabaseUrls
from tests.support.embeddings import FailingEmbedder, tei_with_response
from tests.support.jobs import force_requeue, retire_all_jobs
from tests.support.visitors import Visitor, VisitorFactory

pytestmark = pytest.mark.integration

START: datetime = datetime(2026, 11, 20, tzinfo=UTC)
RETRY_DELAYS: tuple[timedelta, ...] = (timedelta(0), timedelta(seconds=30), timedelta(minutes=2))


@pytest.fixture(autouse=True)
async def no_leftover_jobs(database_urls: TestDatabaseUrls) -> None:
    await retire_all_jobs(database_urls.maintenance)


async def test_upload_then_worker_makes_document_ready(visitor: Visitor) -> None:
    doc_id: str = (await visitor.upload("facts_small_en.pdf")).json()["id"]
    assert await run_once(visitor.container) is True
    document: dict[str, object] = await visitor.document(doc_id)
    assert document["state"] == "ready" and document["page_count"] == 2


async def test_pdf_without_text_fails_with_empty(visitor: Visitor) -> None:
    doc_id: str = (await visitor.upload("blank_pages.pdf")).json()["id"]
    await run_once(visitor.container)
    document: dict[str, object] = await visitor.document(doc_id)
    assert document["state"] == "failed" and document["error_code"] == "empty"


async def test_rerunning_a_job_does_not_duplicate_chunks(visitor: Visitor) -> None:
    doc_id: str = (await visitor.upload("multipage_en.pdf")).json()["id"]
    await run_once(visitor.container)
    first: int = await visitor.chunk_count(doc_id)
    await force_requeue(visitor.container, doc_id)  # simulates a crashed worker whose lease expired
    await run_once(visitor.container)
    assert await visitor.chunk_count(doc_id) == first > 0


async def test_embedding_outage_retries_then_fails(make_visitor: VisitorFactory) -> None:
    clock: FakeClock = FakeClock(datetime(2026, 11, 20, tzinfo=UTC))
    visitor: Visitor = await make_visitor(
        overrides=ContainerOverrides(embedder=FailingEmbedder(), clock=clock)
    )
    doc_id: str = (await visitor.upload("facts_small_en.pdf")).json()["id"]
    for delay in (timedelta(0), timedelta(seconds=30), timedelta(minutes=2)):
        clock.advance(delay)
        assert await run_once(visitor.container) is True
    document: dict[str, object] = await visitor.document(doc_id)
    assert document["state"] == "failed" and document["error_code"] == "embedding_unavailable"


async def test_worker_runs_job_under_owner_context(two_visitors: tuple[Visitor, Visitor]) -> None:
    x, y = two_visitors
    await x.upload("visitor_x_en.pdf")
    await y.upload("visitor_y_en.pdf")
    await run_once(x.container)
    await run_once(x.container)
    assert await x.chunk_texts_contain("ALPHA-7731") and not await x.chunk_texts_contain(
        "BRAVO-4410"
    )
    assert await y.chunk_texts_contain("BRAVO-4410") and not await y.chunk_texts_contain(
        "ALPHA-7731"
    )


async def test_publication_records_the_version_and_completes_the_job(visitor: Visitor) -> None:
    doc_id: str = (await visitor.upload("facts_small_en.pdf")).json()["id"]
    await run_once(visitor.container)
    async with owner_session(visitor.container.sessions, await visitor.owner()) as session:
        document: Document | None = await session.get(Document, UUID(doc_id))
        assert document is not None and document.current_version_id is not None
        version: DocumentVersion | None = await session.get(
            DocumentVersion, document.current_version_id
        )
        job: IngestionJob | None = await session.scalar(
            select(IngestionJob).where(IngestionJob.version_id == document.current_version_id)
        )
    assert version is not None and job is not None
    assert version.state == "ready" and version.error_code is None
    assert version.embedding_config_id == visitor.container.embedding_config_id
    assert version.token_count is not None and version.token_count > 0
    assert version.ready_at is not None and version.parser_name == "pypdf"
    assert job.status == "succeeded" and job.lease_expires_at is None
    assert job.progress_total > 0 and job.progress_done == job.progress_total


async def test_tei_outage_is_retried_as_embedding_unavailable(
    make_visitor: VisitorFactory,
) -> None:
    clock: FakeClock = FakeClock(START)
    visitor: Visitor = await make_visitor(
        overrides=ContainerOverrides(
            embedder=tei_with_response(httpx.ConnectError("refused")), clock=clock
        )
    )
    doc_id: str = (await visitor.upload("facts_small_en.pdf")).json()["id"]
    assert await run_once(visitor.container) is True
    assert (await visitor.document(doc_id))["state"] == "processing"
    assert await run_once(visitor.container) is False  # not due before the first backoff
    for delay in RETRY_DELAYS[1:]:
        clock.advance(delay)
        assert await run_once(visitor.container) is True
    document: dict[str, object] = await visitor.document(doc_id)
    assert document["state"] == "failed" and document["error_code"] == "embedding_unavailable"


async def test_tei_rejecting_the_input_fails_without_retry(make_visitor: VisitorFactory) -> None:
    visitor: Visitor = await make_visitor(
        overrides=ContainerOverrides(embedder=tei_with_response(httpx.Response(413)))
    )
    doc_id: str = (await visitor.upload("facts_small_en.pdf")).json()["id"]
    assert await run_once(visitor.container) is True
    document: dict[str, object] = await visitor.document(doc_id)
    assert document["state"] == "failed" and document["error_code"] == "internal"
    assert await run_once(visitor.container) is False


async def test_missing_upload_fails_as_internal_without_retry(visitor: Visitor) -> None:
    doc_id: str = (await visitor.upload("facts_small_en.pdf")).json()["id"]
    owner: OwnerScope = await visitor.owner()
    await visitor.container.file_store.delete_prefix(f"{owner.owner_id}/{doc_id}/")
    assert await run_once(visitor.container) is True
    document: dict[str, object] = await visitor.document(doc_id)
    assert document["state"] == "failed" and document["error_code"] == "internal"
    assert await run_once(visitor.container) is False


async def test_job_reclaimed_after_three_attempts_fails_as_internal(
    make_visitor: VisitorFactory,
) -> None:
    clock: FakeClock = FakeClock(START)
    visitor: Visitor = await make_visitor(overrides=ContainerOverrides(clock=clock))
    doc_id: str = (await visitor.upload("facts_small_en.pdf")).json()["id"]
    for _ in range(3):  # each claim stands for a worker that crashed while holding the job
        assert await claim_job(visitor.container) is not None
        clock.advance(JOB_LEASE + timedelta(seconds=1))
    assert await run_once(visitor.container) is True
    document: dict[str, object] = await visitor.document(doc_id)
    assert document["state"] == "failed" and document["error_code"] == "internal"
    assert await visitor.chunk_count(doc_id) == 0
    clock.advance(JOB_LEASE + timedelta(seconds=1))
    assert await run_once(visitor.container) is False


class ReclaimingEmbedder:
    """Embeds correctly, but first lets the lease lapse and has a second worker claim the job."""

    def __init__(self, clock: FakeClock) -> None:
        self._inner: HashEmbedder = HashEmbedder()
        self._clock: FakeClock = clock
        self.container: AppContainer | None = None
        self.reclaimed: ClaimedJob | None = None

    @property
    def config(self) -> EmbeddingConfig:
        return self._inner.config

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if self.reclaimed is None:
            assert self.container is not None
            self._clock.advance(JOB_LEASE + timedelta(seconds=1))
            self.reclaimed = await claim_job(self.container)
        return await self._inner.embed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        return await self._inner.embed_query(text)

    async def check_ready(self) -> None:
        await self._inner.check_ready()


async def test_worker_that_lost_its_lease_does_not_publish(make_visitor: VisitorFactory) -> None:
    clock: FakeClock = FakeClock(START)
    embedder: ReclaimingEmbedder = ReclaimingEmbedder(clock)
    visitor: Visitor = await make_visitor(
        overrides=ContainerOverrides(embedder=embedder, clock=clock)
    )
    embedder.container = visitor.container
    doc_id: str = (await visitor.upload("facts_small_en.pdf")).json()["id"]

    assert await run_once(visitor.container) is True

    assert embedder.reclaimed is not None
    assert await visitor.chunk_count(doc_id) == 0
    assert (await visitor.document(doc_id))["state"] == "processing"
    await build_ingestion_pipeline(visitor.container).process(embedder.reclaimed)
    assert (await visitor.document(doc_id))["state"] == "ready"
    assert await visitor.chunk_count(doc_id) > 0


async def test_worker_loop_runs_queued_jobs_and_stops(visitor: Visitor) -> None:
    doc_ids: list[str] = [
        (await visitor.upload(name)).json()["id"]
        for name in ("facts_small_en.pdf", "multipage_en.pdf", "visitor_x_en.pdf")
    ]
    stop: asyncio.Event = asyncio.Event()
    worker: asyncio.Task[None] = asyncio.create_task(
        run_worker(visitor.container, poll_seconds=0.01, stop=stop)
    )
    async with asyncio.timeout(30):
        while [(await visitor.document(doc_id))["state"] for doc_id in doc_ids] != ["ready"] * 3:
            await asyncio.sleep(0.05)
    stop.set()
    async with asyncio.timeout(5):
        await worker
