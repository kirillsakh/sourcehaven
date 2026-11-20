from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from sourcehaven.api.app import create_app
from sourcehaven.composition import AppContainer, ContainerOverrides
from sourcehaven.config import Settings
from tests.support.db import TestDatabaseUrls


class ApiClient(httpx.AsyncClient):
    """HTTP client that calls the application in-process and exposes its container."""

    def __init__(self, app: FastAPI, container: AppContainer) -> None:
        super().__init__(transport=httpx.ASGITransport(app=app), base_url="https://testserver")
        self.app: FastAPI = app
        self.container: AppContainer = container


ApiClientFactory = Callable[..., AbstractAsyncContextManager[ApiClient]]


@pytest.fixture
def make_api_client(database_urls: TestDatabaseUrls, tmp_path: Path) -> ApiClientFactory:
    """Return a factory of clients for an app wired to the test database with offline fakes."""

    @asynccontextmanager
    async def build(
        *,
        overrides: ContainerOverrides | None = None,
        settings_overrides: Mapping[str, object] | None = None,
    ) -> AsyncIterator[ApiClient]:
        values: dict[str, object] = {
            "database_url": database_urls.app,
            "maintenance_database_url": database_urls.maintenance,
            "generation_provider": "fake",
            "embedding_provider": "hash",
            "human_verification": "disabled",
            "cookie_secure": False,
            "uploads_dir": tmp_path / "uploads",
            **(settings_overrides or {}),
        }
        app: FastAPI = create_app(Settings.model_validate(values), overrides)
        async with (
            app.router.lifespan_context(app),
            ApiClient(app, app.state.container) as client,
        ):
            yield client

    return build


@pytest.fixture
async def api_client(make_api_client: ApiClientFactory) -> AsyncIterator[ApiClient]:
    async with make_api_client() as client:
        yield client
