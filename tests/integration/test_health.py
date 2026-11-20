from types import TracebackType

import httpx
import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sourcehaven.composition import ContainerOverrides
from tests.support.app import ApiClientFactory
from tests.support.embeddings import NotReadyEmbedder

pytestmark = pytest.mark.integration


async def test_live(api_client: httpx.AsyncClient) -> None:
    response: httpx.Response = await api_client.get("/api/health/live")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


async def test_ready_with_hash_embedder(api_client: httpx.AsyncClient) -> None:
    response: httpx.Response = await api_client.get("/api/health/ready")
    assert response.status_code == 200 and response.json() == {"status": "ready"}


async def test_not_ready_when_embedder_mismatch(make_api_client: ApiClientFactory) -> None:
    async with make_api_client(overrides=ContainerOverrides(embedder=NotReadyEmbedder())) as client:
        response: httpx.Response = await client.get("/api/health/ready")
    assert response.status_code == 503 and response.json()["reason"] == "embeddings"


class UnreachableSession:
    """Stands in for `system_session` when the database refuses connections."""

    def __init__(self, _: async_sessionmaker[AsyncSession]) -> None:
        pass

    async def __aenter__(self) -> AsyncSession:
        raise OperationalError("SELECT 1", None, ConnectionError("connection refused"))

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


async def test_not_ready_when_database_is_unreachable(
    api_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sourcehaven.api.routes.health.system_session", UnreachableSession)
    response: httpx.Response = await api_client.get("/api/health/ready")
    assert response.status_code == 503 and response.json() == {
        "status": "not_ready",
        "reason": "database",
    }


async def test_not_ready_when_revision_is_not_head(
    api_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sourcehaven.api.routes.health.packaged_head", lambda: "9999")
    response: httpx.Response = await api_client.get("/api/health/ready")
    assert response.status_code == 503 and response.json()["reason"] == "migrations"
