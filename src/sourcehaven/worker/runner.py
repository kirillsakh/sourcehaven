import asyncio
import contextlib
import logging
from typing import Final

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from sourcehaven.composition import AppContainer, build_ingestion_pipeline
from sourcehaven.domain.models import OwnerScope
from sourcehaven.ingestion.pipeline import JOB_LEASE, ClaimedJob, IngestionPipeline
from sourcehaven.storage.db import system_session

logger: logging.Logger = logging.getLogger(__name__)

MAX_CONCURRENT_JOBS: Final[int] = 2


async def claim_job(container: AppContainer) -> ClaimedJob | None:
    """Claim the oldest due job of any owner, taking a lease of `JOB_LEASE`.

    Due jobs are queued or retrying jobs whose `next_attempt_at` has passed, and running jobs
    whose lease has expired. Claiming increments the job's `attempts`.

    Returns:
        The claimed job, or None when no job is due.
    """
    session: AsyncSession
    async with system_session(container.sessions) as session:
        row: Row[tuple[object, ...]] | None = (
            await session.execute(
                text(
                    "SELECT job_id, owner_id, version_id"
                    " FROM sourcehaven_claim_ingestion_job(:lease_seconds, :now)"
                ),
                {"lease_seconds": int(JOB_LEASE.total_seconds()), "now": container.clock()},
            )
        ).one_or_none()
    if row is None:
        return None
    return ClaimedJob(job_id=row.job_id, owner=OwnerScope(row.owner_id), version_id=row.version_id)


async def run_once(container: AppContainer) -> bool:
    """Claim one due job and process it.

    Returns:
        Whether a job was claimed.
    """
    job: ClaimedJob | None = await claim_job(container)
    if job is None:
        return False
    await build_ingestion_pipeline(container).process(job)
    return True


async def run_worker(
    container: AppContainer, *, poll_seconds: float = 2.0, stop: asyncio.Event
) -> None:
    """Process due jobs, at most `MAX_CONCURRENT_JOBS` at a time, until `stop` is set.

    After `stop` is set no new job is claimed, and the call returns once running jobs finish.
    Errors from one job are logged by class and do not stop the loop; such a job is claimed
    again when its lease expires.

    Args:
        container: Application collaborators.
        poll_seconds: Wait between claims while no job is due.
        stop: Event that ends the loop.
    """
    pipeline: IngestionPipeline = build_ingestion_pipeline(container)
    slots: asyncio.Semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
    async with asyncio.TaskGroup() as jobs:
        while not stop.is_set():
            await slots.acquire()
            job: ClaimedJob | None = None
            if not stop.is_set():
                job = await _try_claim(container)
            if job is None:
                slots.release()
                await _wait(stop, poll_seconds)
                continue
            jobs.create_task(_process(pipeline, job, slots))


async def _try_claim(container: AppContainer) -> ClaimedJob | None:
    try:
        return await claim_job(container)
    except Exception as error:
        logger.warning("claiming an ingestion job raised %s", type(error).__name__)
        return None


async def _process(pipeline: IngestionPipeline, job: ClaimedJob, slots: asyncio.Semaphore) -> None:
    try:
        await pipeline.process(job)
    except Exception as error:
        # Raising would cancel the other running job through the task group.
        logger.warning("ingestion job %s raised %s", job.job_id, type(error).__name__)
    finally:
        slots.release()


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(seconds):
            await stop.wait()
