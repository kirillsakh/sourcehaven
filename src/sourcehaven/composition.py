import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sourcehaven.config import Settings
from sourcehaven.embeddings.config import EmbeddingConfig
from sourcehaven.embeddings.hashing import HashEmbedder, WhitespaceTokenCounter
from sourcehaven.embeddings.protocol import Embedder, TokenCounter
from sourcehaven.embeddings.tei import HfTokenCounter, TeiEmbedder
from sourcehaven.generation.chat import build_chat_model
from sourcehaven.generation.prompts import (
    estimate_tokens,
    make_token_counter,
    prompt_encoding_name,
)
from sourcehaven.ingestion.pdf import PdfAdapter, SourceAdapter
from sourcehaven.ingestion.pipeline import IngestionPipeline
from sourcehaven.sessions.verification import AllowAllVerifier, HumanVerifier
from sourcehaven.storage.db import (
    create_engine,
    ensure_rls_applies,
    make_sessionmaker,
    system_session,
)
from sourcehaven.storage.files import FileStore, LocalFileStore
from sourcehaven.storage.repositories.embedding_configs import ensure_embedding_config

logger: logging.Logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppContainer:
    """The long-lived collaborators of one running application."""

    settings: Settings
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    embedder: Embedder
    token_counter: TokenCounter
    clock: Callable[[], datetime]
    verifier: HumanVerifier
    file_store: FileStore
    source_adapter: SourceAdapter
    chat_model: BaseChatModel
    count_prompt_tokens: Callable[[str], int]
    embedding_config_id: int


@dataclass(frozen=True)
class ContainerOverrides:
    """Collaborators that tests substitute for the ones built from settings."""

    embedder: Embedder | None = None
    token_counter: TokenCounter | None = None
    clock: Callable[[], datetime] | None = None
    verifier: HumanVerifier | None = None
    file_store: FileStore | None = None
    source_adapter: SourceAdapter | None = None
    chat_model: BaseChatModel | None = None
    count_prompt_tokens: Callable[[str], int] | None = None


def utc_now() -> datetime:
    return datetime.now(UTC)


def select_token_counter(settings: Settings) -> TokenCounter:
    """Choose the token counter that matches the embedding provider.

    Raises:
        ValueError: If the `tei` provider is selected without `tokenizer_file`.
    """
    if settings.embedding_provider == "hash":
        return WhitespaceTokenCounter()
    if settings.tokenizer_file is None:
        raise ValueError("tokenizer_file is required when embedding_provider is tei")
    return HfTokenCounter(settings.tokenizer_file)


def select_verifier(settings: Settings) -> HumanVerifier:
    """Choose the human verifier for the configured mode.

    Raises:
        NotImplementedError: If `turnstile` is selected; it is not implemented yet.
    """
    if settings.human_verification == "disabled":
        return AllowAllVerifier()
    raise NotImplementedError(
        "human_verification=turnstile is not implemented yet; "
        "set SOURCEHAVEN_HUMAN_VERIFICATION=disabled"
    )


async def select_prompt_token_counter(
    settings: Settings,
    *,
    make_counter: Callable[[Settings], Callable[[str], int]] = make_token_counter,
) -> Callable[[str], int]:
    """Choose how prompts are measured against the context budget (spec section 7.4).

    The fake provider uses the conservative character estimate. The OpenAI provider uses the
    model's tiktoken encoding, loaded here once in a worker thread because its first use may
    download the encoding, which must never block the event loop. If it cannot be loaded, the
    character estimate is used instead and a warning naming the encoding is logged.

    Args:
        settings: Application settings.
        make_counter: Builds the model's token counter; replaced in tests.

    Returns:
        A token counter that never needs to load anything on first use.
    """
    if settings.generation_provider == "fake":
        return estimate_tokens
    counter: Callable[[str], int] = make_counter(settings)
    try:
        await asyncio.to_thread(counter, "")
    except Exception as error:
        # Only the encoding and the error class are logged: messages may embed URLs or paths.
        logger.warning(
            "prompt token encoding %s could not be loaded (%s); using the character estimate",
            prompt_encoding_name(settings),
            type(error).__name__,
        )
        return estimate_tokens
    return counter


@asynccontextmanager
async def build_container(
    settings: Settings, overrides: ContainerOverrides | None = None
) -> AsyncIterator[AppContainer]:
    """Create the application's collaborators and release them on exit.

    Checks that the database role is subject to row-level security and registers the active
    embedding configuration, so the database must be reachable and migrated.

    Args:
        settings: Application settings.
        overrides: Collaborators to use instead of the ones built from `settings`.

    Yields:
        The container; its engine and HTTP client are closed when the block exits.

    Raises:
        ValueError: If the settings cannot produce a token counter or a chat model.
        NotImplementedError: If the settings select Turnstile human verification.
        PrivilegedRoleError: If `database_url` connects as a superuser or `BYPASSRLS` role.
    """
    chosen: ContainerOverrides = overrides or ContainerOverrides()
    async with AsyncExitStack() as stack:
        chat_model: BaseChatModel = chosen.chat_model or build_chat_model(settings)
        token_counter: TokenCounter = chosen.token_counter or select_token_counter(settings)
        verifier: HumanVerifier = chosen.verifier or select_verifier(settings)
        count_prompt_tokens: Callable[[str], int] = (
            chosen.count_prompt_tokens or await select_prompt_token_counter(settings)
        )
        embedder: Embedder
        if chosen.embedder is not None:
            embedder = chosen.embedder
        elif settings.embedding_provider == "hash":
            embedder = HashEmbedder(config=EmbeddingConfig.from_settings(settings))
        else:
            client: httpx.AsyncClient = await stack.enter_async_context(
                httpx.AsyncClient(base_url=settings.tei_url)
            )
            embedder = TeiEmbedder(client, EmbeddingConfig.from_settings(settings))
        engine: AsyncEngine = create_engine(settings.database_url)
        stack.push_async_callback(engine.dispose)
        sessions: async_sessionmaker[AsyncSession] = make_sessionmaker(engine)
        async with system_session(sessions) as session:
            await ensure_rls_applies(session)
            embedding_config_id: int = await ensure_embedding_config(session, embedder.config)
        yield AppContainer(
            settings=settings,
            engine=engine,
            sessions=sessions,
            embedder=embedder,
            token_counter=token_counter,
            clock=chosen.clock or utc_now,
            verifier=verifier,
            file_store=chosen.file_store or LocalFileStore(settings.uploads_dir),
            source_adapter=chosen.source_adapter or PdfAdapter(),
            chat_model=chat_model,
            count_prompt_tokens=count_prompt_tokens,
            embedding_config_id=embedding_config_id,
        )


def build_ingestion_pipeline(container: AppContainer) -> IngestionPipeline:
    return IngestionPipeline(
        sessions=container.sessions,
        file_store=container.file_store,
        adapter=container.source_adapter,
        embedder=container.embedder,
        counter=container.token_counter,
        settings=container.settings,
        embedding_config_id=container.embedding_config_id,
        clock=container.clock,
    )
