from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sourcehaven.api.errors import install_error_handlers
from sourcehaven.api.routes import conversations, documents, health, session
from sourcehaven.api.upload_limit import MULTIPART_ALLOWANCE_BYTES, UploadSizeLimitMiddleware
from sourcehaven.composition import ContainerOverrides, build_container
from sourcehaven.config import Settings


def create_app(settings: Settings, overrides: ContainerOverrides | None = None) -> FastAPI:
    """Build the FastAPI application.

    The container is created by the lifespan, so building the app contacts no service.

    Args:
        settings: Application settings.
        overrides: Collaborators to substitute for the ones built from `settings`.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with build_container(settings, overrides) as container:
            app.state.container = container
            yield

    app: FastAPI = FastAPI(title="Sourcehaven", lifespan=lifespan)
    app.add_middleware(
        UploadSizeLimitMiddleware,
        method="POST",
        path="/api/documents",
        max_body_bytes=settings.max_upload_bytes + MULTIPART_ALLOWANCE_BYTES,
    )
    install_error_handlers(app)
    app.include_router(health.router, prefix="/api/health")
    app.include_router(session.router, prefix="/api/session")
    app.include_router(documents.router, prefix="/api/documents")
    app.include_router(conversations.router, prefix="/api/conversations")
    return app
