from datetime import datetime, timedelta
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from sourcehaven.composition import AppContainer
from sourcehaven.storage.db import create_engine
from sourcehaven.storage.models import DocumentVersion, IngestionJob


async def force_requeue(container: AppContainer, document_id: str) -> None:
    """Make the document's ingestion job look like it was held by a worker that crashed.

    The job becomes `running` with a lease that has already expired, so the next claim picks it up
    again. Connects as the maintenance role because the test does not act as the job's owner.
    """
    expired: datetime = container.clock() - timedelta(seconds=1)
    maintenance_url: SecretStr | None = container.settings.maintenance_database_url
    assert maintenance_url is not None
    engine: AsyncEngine = create_engine(maintenance_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                update(IngestionJob)
                .where(
                    IngestionJob.version_id.in_(
                        select(DocumentVersion.id).where(
                            DocumentVersion.document_id == UUID(document_id)
                        )
                    )
                )
                .values(status="running", lease_expires_at=expired)
            )
    finally:
        await engine.dispose()


async def retire_all_jobs(maintenance_url: SecretStr) -> None:
    """Mark every ingestion job in the database failed, so earlier tests' uploads are not claimed.

    The test database is shared by the whole session, and the claim function picks the oldest due
    job of any owner.
    """
    engine: AsyncEngine = create_engine(maintenance_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(update(IngestionJob).values(status="failed"))
    finally:
        await engine.dispose()
