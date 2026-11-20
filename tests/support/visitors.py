from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import exists, select

from sourcehaven.api.deps import SESSION_COOKIE, get_session_service
from sourcehaven.composition import AppContainer, ContainerOverrides
from sourcehaven.domain.models import Evidence, OwnerScope
from sourcehaven.retrieval.search import search_evidence
from sourcehaven.sessions.service import ResolvedSession, SessionService
from sourcehaven.storage.db import owner_session
from sourcehaven.storage.models import Chunk, DocumentVersion, Turn, TurnSource
from sourcehaven.storage.repositories.chunks import count_chunks
from sourcehaven.worker.runner import run_once
from tests.support.app import ApiClient, ApiClientFactory
from tests.support.db import TestDatabaseUrls
from tests.support.jobs import retire_all_jobs
from tests.support.streaming import SseEvent, SseStream, StreamingASGITransport, parse_sse

FIXTURE_DOCUMENTS: Path = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


@dataclass(frozen=True)
class StoredTurn:
    """A turn as stored, including what the API does not expose.

    Attributes:
        status: The turn status.
        error_code: Why the turn did not complete, if it did not.
        sources: `(label, cited)` of every stored source row, ordered by label number.
    """

    status: str
    error_code: str | None
    sources: list[tuple[str, bool]]


class Visitor:
    """A client with an established anonymous session, plus helpers for common requests.

    Add helpers here as features need them instead of writing parallel test utilities.
    """

    def __init__(self, client: ApiClient) -> None:
        self.client: ApiClient = client
        self.conversation_id: str | None = None

    @property
    def container(self) -> AppContainer:
        return self.client.container

    async def owner(self) -> OwnerScope:
        """The owner this visitor's session resolves to, as the server sees it."""
        service: SessionService = get_session_service(self.container)
        resolved: ResolvedSession | None = await service.resolve(
            self.client.cookies[SESSION_COOKIE]
        )
        assert resolved is not None
        return resolved.owner

    async def upload_bytes(self, name: str, data: bytes) -> httpx.Response:
        return await self.client.post(
            "/api/documents", files={"file": (name, data, "application/pdf")}
        )

    async def upload(self, fixture_name: str) -> httpx.Response:
        return await self.upload_bytes(
            fixture_name, (FIXTURE_DOCUMENTS / fixture_name).read_bytes()
        )

    async def document(self, document_id: str) -> dict[str, object]:
        response: httpx.Response = await self.client.get(f"/api/documents/{document_id}")
        assert response.status_code == 200, response.text
        body: dict[str, object] = response.json()
        return body

    async def chunk_count(self, document_id: str) -> int:
        """Count the chunks of the document's latest version, as this visitor's owner sees them."""
        owner: OwnerScope = await self.owner()
        async with owner_session(self.container.sessions, owner) as session:
            version_id: UUID | None = await session.scalar(
                select(DocumentVersion.id)
                .where(DocumentVersion.document_id == UUID(document_id))
                .order_by(DocumentVersion.version_no.desc())
                .limit(1)
            )
            assert version_id is not None
            return await count_chunks(session, owner, version_id)

    async def chunk_texts_contain(self, needle: str) -> bool:
        """Whether any chunk visible to this visitor's owner contains `needle`."""
        owner: OwnerScope = await self.owner()
        async with owner_session(self.container.sessions, owner) as session:
            found: bool | None = await session.scalar(
                select(exists().where(Chunk.text.contains(needle, autoescape=True)))
            )
        return found is True

    async def search(self, question: str, document_ids: Sequence[str]) -> list[Evidence]:
        """Embed `question` and retrieve candidates from the given documents as this owner."""
        owner: OwnerScope = await self.owner()
        query_vector: list[float] = await self.container.embedder.embed_query(question)
        async with owner_session(self.container.sessions, owner) as session:
            return await search_evidence(
                session,
                owner=owner,
                document_ids=[UUID(document_id) for document_id in document_ids],
                query_vector=query_vector,
                embedding_config_id=self.container.embedding_config_id,
            )

    async def search_unfiltered(self, question: str) -> list[UUID]:
        """Find the nearest chunks with no owner, document or configuration predicate.

        Only row-level security restricts the result, which is what makes this a test of the
        second isolation layer. Never use it in application code.
        """
        owner: OwnerScope = await self.owner()
        query_vector: list[float] = await self.container.embedder.embed_query(question)
        async with owner_session(self.container.sessions, owner) as session:
            rows: Sequence[UUID] = (
                await session.scalars(
                    select(Chunk.id)
                    .order_by(Chunk.embedding.cosine_distance(query_vector))
                    .limit(20)
                )
            ).all()
        return list(rows)

    async def start_conversation(self) -> str:
        """Start a conversation and make it the one the question helpers use."""
        response: httpx.Response = await self.client.post("/api/conversations", json={})
        assert response.status_code == 201, response.text
        conversation_id: str = response.json()["id"]
        self.conversation_id = conversation_id
        return conversation_id

    async def _conversation_id(self) -> str:
        return self.conversation_id or await self.start_conversation()

    @staticmethod
    def _turn_body(body: Mapping[str, object], client_request_id: str | None) -> dict[str, object]:
        return {
            "client_request_id": client_request_id or str(uuid4()),
            "kind": "question",
            **body,
        }

    async def post_turn(
        self, body: Mapping[str, object], *, client_request_id: str | None = None
    ) -> httpx.Response:
        """Post a turn request to the current conversation and read the whole response.

        `client_request_id` (a fresh one by default) and `kind: question` are filled in unless
        `body` sets them.
        """
        conversation_id: str = await self._conversation_id()
        return await self.client.post(
            f"/api/conversations/{conversation_id}/turns",
            json=self._turn_body(body, client_request_id),
        )

    async def ask(
        self,
        question: str,
        document_ids: Sequence[str],
        *,
        client_request_id: str | None = None,
    ) -> list[SseEvent]:
        """Ask a question in the current conversation and return every streamed event."""
        response: httpx.Response = await self.post_turn(
            {"question": question, "document_ids": list(document_ids)},
            client_request_id=client_request_id,
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        return parse_sse(response.text)

    @asynccontextmanager
    async def stream_question(
        self, question: str, document_ids: Sequence[str]
    ) -> AsyncIterator[SseStream]:
        """Ask a question and read its events while the answer is still being generated.

        Leaving the block closes the HTTP stream, which the app sees as a client disconnect.
        """
        conversation_id: str = await self._conversation_id()
        body: dict[str, object] = self._turn_body(
            {"question": question, "document_ids": list(document_ids)}, None
        )
        async with (
            httpx.AsyncClient(
                transport=StreamingASGITransport(self.client.app),
                base_url=self.client.base_url,
                cookies=self.client.cookies,
            ) as streaming_client,
            streaming_client.stream(
                "POST", f"/api/conversations/{conversation_id}/turns", json=body
            ) as response,
        ):
            assert response.status_code == 200
            yield SseStream(response)

    async def conversation(self) -> dict[str, Any]:
        """The current conversation as `GET /api/conversations/{id}` returns it."""
        conversation_id: str = await self._conversation_id()
        response: httpx.Response = await self.client.get(f"/api/conversations/{conversation_id}")
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    async def stored_turn(self, turn_id: str) -> StoredTurn:
        """Read a turn and its source rows from the database as this visitor's owner."""
        owner: OwnerScope = await self.owner()
        async with owner_session(self.container.sessions, owner) as session:
            turn: Turn | None = await session.scalar(
                select(Turn).where(Turn.owner_id == owner.owner_id, Turn.id == UUID(turn_id))
            )
            assert turn is not None
            rows: Sequence[TurnSource] = (
                await session.scalars(select(TurnSource).where(TurnSource.turn_id == turn.id))
            ).all()
        sources: list[tuple[str, bool]] = sorted(
            ((row.label, row.cited) for row in rows), key=lambda source: int(source[0][1:])
        )
        return StoredTurn(status=turn.status, error_code=turn.error_code, sources=sources)

    async def last_turn(self) -> dict[str, Any]:
        turns: list[dict[str, Any]] = (await self.conversation())["turns"]
        assert turns, "the conversation has no turns"
        return turns[-1]


VisitorFactory = Callable[..., Awaitable[Visitor]]


async def _start_session(client: ApiClient) -> Visitor:
    response: httpx.Response = await client.post("/api/session", json={})
    assert response.status_code == 200, response.text
    return Visitor(client)


@pytest.fixture
async def make_visitor(make_api_client: ApiClientFactory) -> AsyncIterator[VisitorFactory]:
    """Return a factory of visitors; it takes the same keywords as `make_api_client`."""
    async with AsyncExitStack() as stack:

        async def build(
            *,
            overrides: ContainerOverrides | None = None,
            settings_overrides: Mapping[str, object] | None = None,
        ) -> Visitor:
            client: ApiClient = await stack.enter_async_context(
                make_api_client(overrides=overrides, settings_overrides=settings_overrides)
            )
            return await _start_session(client)

        yield build


@pytest.fixture
async def visitor(make_visitor: VisitorFactory) -> Visitor:
    return await make_visitor()


@pytest.fixture
async def two_visitors(make_visitor: VisitorFactory) -> AsyncIterator[tuple[Visitor, Visitor]]:
    """Two visitors with separate cookies that share one application and container."""
    first: Visitor = await make_visitor()
    async with ApiClient(first.client.app, first.container) as second_client:
        yield first, await _start_session(second_client)


ReadyVisitor = tuple[Visitor, list[str]]
ReadyVisitorFactory = Callable[..., Awaitable[ReadyVisitor]]
TwoReadyVisitors = tuple[ReadyVisitor, ReadyVisitor]


async def _upload_and_ingest(visitor: Visitor, fixture_names: Sequence[str]) -> list[str]:
    """Upload the fixtures, run the worker until it is idle and require every document ready."""
    document_ids: list[str] = []
    for name in fixture_names:
        response: httpx.Response = await visitor.upload(name)
        assert response.status_code in (200, 202), response.text
        document_ids.append(response.json()["id"])
    while await run_once(visitor.container):
        pass
    for document_id in document_ids:
        document: dict[str, object] = await visitor.document(document_id)
        assert document["state"] == "ready", document
    return document_ids


@pytest.fixture
async def ready_visitor(
    make_visitor: VisitorFactory, database_urls: TestDatabaseUrls
) -> ReadyVisitorFactory:
    """Return a factory of visitors whose uploaded fixtures are already ingested and ready.

    The factory takes fixture names followed by the keywords of `make_visitor`, and returns the
    visitor, with a conversation started, and its document ids in upload order. The shared test
    database is cleared of earlier tests' jobs first, because the worker claims the oldest job of
    any owner.
    """

    async def build(
        *fixture_names: str,
        overrides: ContainerOverrides | None = None,
        settings_overrides: Mapping[str, object] | None = None,
    ) -> ReadyVisitor:
        await retire_all_jobs(database_urls.maintenance)
        visitor: Visitor = await make_visitor(
            overrides=overrides, settings_overrides=settings_overrides
        )
        document_ids: list[str] = await _upload_and_ingest(visitor, fixture_names)
        await visitor.start_conversation()
        return visitor, document_ids

    return build


@pytest.fixture
async def two_ready_visitors(
    two_visitors: tuple[Visitor, Visitor], database_urls: TestDatabaseUrls
) -> TwoReadyVisitors:
    """Visitor X with `visitor_x_en.pdf` and visitor Y with `visitor_y_en.pdf`, ingested.

    Each visitor has a conversation started.
    """
    await retire_all_jobs(database_urls.maintenance)
    x, y = two_visitors
    x_documents: list[str] = await _upload_and_ingest(x, ["visitor_x_en.pdf"])
    y_documents: list[str] = await _upload_and_ingest(y, ["visitor_y_en.pdf"])
    await x.start_conversation()
    await y.start_conversation()
    return (x, x_documents), (y, y_documents)
