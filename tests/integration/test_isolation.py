"""Cross-visitor isolation through every M1 endpoint (spec §13.2).

Visitor X owns `visitor_x_en.pdf` (ALPHA-7731); visitor Y owns `visitor_y_en.pdf` (BRAVO-4410).
Each test acts as Y against X's identifiers and expects the same answer as for ids that never
existed, so that no response reveals whether another visitor's object exists.
"""

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from sourcehaven.domain.models import Evidence, OwnerScope
from sourcehaven.retrieval.search import search_evidence
from sourcehaven.storage.db import create_engine, make_sessionmaker, owner_session
from sourcehaven.storage.models import Document
from sourcehaven.storage.repositories.chunks import count_chunks
from sourcehaven.storage.repositories.conversations import (
    conversation_exists,
    document_readiness,
    list_turns,
)
from sourcehaven.storage.repositories.documents import (
    DocumentView,
    count_documents,
    find_by_content_hash,
    get_document,
    get_document_view,
    list_document_views,
)
from tests.support.db import TestDatabaseUrls
from tests.support.streaming import SseEvent
from tests.support.visitors import TwoReadyVisitors

pytestmark = pytest.mark.integration

X_MARKER: str = "ALPHA-7731"
Y_MARKER: str = "BRAVO-4410"
QUESTION_WITH_X_MARKER: str = f"What is the secret code {X_MARKER}?"


async def test_documents_list_never_shows_other_visitor(
    two_ready_visitors: TwoReadyVisitors,
) -> None:
    (x, _), (y, _) = two_ready_visitors
    x_names: list[str] = [d["display_name"] for d in (await x.client.get("/api/documents")).json()]
    y_names: list[str] = [d["display_name"] for d in (await y.client.get("/api/documents")).json()]
    assert x_names == ["visitor_x_en.pdf"]
    assert y_names == ["visitor_y_en.pdf"]


async def test_foreign_document_is_404_like_unknown(
    two_ready_visitors: TwoReadyVisitors,
) -> None:
    (x, x_docs), (y, _) = two_ready_visitors
    assert (await x.document(x_docs[0]))["display_name"] == "visitor_x_en.pdf"  # control
    foreign: httpx.Response = await y.client.get(f"/api/documents/{x_docs[0]}")
    unknown: httpx.Response = await y.client.get(f"/api/documents/{uuid4()}")
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json() == {"code": "not_found"}
    assert foreign.content == unknown.content


async def test_foreign_conversation_is_404_like_unknown(
    two_ready_visitors: TwoReadyVisitors,
) -> None:
    (x, _), (y, _) = two_ready_visitors
    assert (await x.conversation())["id"] == x.conversation_id  # control: the owner can read it
    foreign: httpx.Response = await y.client.get(f"/api/conversations/{x.conversation_id}")
    unknown: httpx.Response = await y.client.get(f"/api/conversations/{uuid4()}")
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json() == {"code": "not_found"}
    assert foreign.content == unknown.content


async def test_posting_into_foreign_conversation_is_404(
    two_ready_visitors: TwoReadyVisitors,
) -> None:
    (x, _), (y, y_docs) = two_ready_visitors
    assert (await x.conversation())["turns"] == []  # control: the conversation exists for X
    body: dict[str, object] = {
        "client_request_id": str(uuid4()),
        "kind": "question",
        "question": "?",
        "document_ids": y_docs,
    }
    foreign: httpx.Response = await y.client.post(
        f"/api/conversations/{x.conversation_id}/turns", json=body
    )
    unknown: httpx.Response = await y.client.post(f"/api/conversations/{uuid4()}/turns", json=body)
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.content == unknown.content
    assert (await x.conversation())["turns"] == []


async def test_asking_about_foreign_documents_is_404_like_unknown(
    two_ready_visitors: TwoReadyVisitors,
) -> None:
    (x, x_docs), (y, _) = two_ready_visitors
    assert (await x.document(x_docs[0]))["state"] == "ready"  # control: the ids are real
    question: dict[str, object] = {"question": QUESTION_WITH_X_MARKER, "document_ids": x_docs}
    foreign: httpx.Response = await y.post_turn(question)
    unknown: httpx.Response = await y.post_turn({**question, "document_ids": [str(uuid4())]})
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.content == unknown.content
    assert X_MARKER not in foreign.text.replace(QUESTION_WITH_X_MARKER, "")
    stored: str = json.dumps((await y.conversation())["turns"], ensure_ascii=False)
    assert X_MARKER not in stored
    assert (await y.conversation())["turns"] == []


async def test_answers_never_contain_other_visitors_markers(
    two_ready_visitors: TwoReadyVisitors,
) -> None:
    (x, x_docs), (y, y_docs) = two_ready_visitors
    own: list[SseEvent] = await x.ask("What is the secret code?", x_docs)  # control: X sees ALPHA
    assert X_MARKER in json.dumps([e.data for e in own], ensure_ascii=False)

    events: list[SseEvent] = await y.ask(QUESTION_WITH_X_MARKER, y_docs)
    assert [e.name for e in events][-2:] == ["sources", "done"]
    payload: str = json.dumps([e.data for e in events], ensure_ascii=False)
    assert X_MARKER not in payload
    assert Y_MARKER in payload
    sources: list[dict[str, Any]] = events[-2].data["sources"]
    assert sources
    assert all(source["document_id"] in y_docs for source in sources)
    turns: list[dict[str, Any]] = (await y.conversation())["turns"]
    stored_answers: str = json.dumps(
        [{key: value for key, value in turn.items() if key != "question"} for turn in turns],
        ensure_ascii=False,
    )
    assert X_MARKER not in stored_answers  # the stored question legitimately repeats it


async def test_without_cookie_everything_requires_session(
    two_ready_visitors: TwoReadyVisitors,
) -> None:
    (x, x_docs), _ = two_ready_visitors
    x.client.cookies.clear()
    requests: list[tuple[str, str]] = [
        ("GET", "/api/documents"),
        ("GET", f"/api/documents/{x_docs[0]}"),
        ("POST", "/api/documents"),
        ("POST", "/api/conversations"),
        ("GET", f"/api/conversations/{x.conversation_id}"),
        ("POST", f"/api/conversations/{x.conversation_id}/turns"),
    ]
    for method, path in requests:
        response: httpx.Response = await x.client.request(method, path)
        assert response.status_code == 401, (method, path, response.text)
        assert response.json() == {"code": "session_required"}, (method, path)


@pytest.fixture
async def bypassrls_sessions(
    database_urls: TestDatabaseUrls,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessions as `sourcehaven_maintenance`, a role that row-level security does not restrict."""
    engine: AsyncEngine = create_engine(database_urls.maintenance)
    try:
        yield make_sessionmaker(engine)
    finally:
        await engine.dispose()


async def test_application_filters_isolate_without_rls(
    two_ready_visitors: TwoReadyVisitors,
    bypassrls_sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The application filter (spec §5.1, first layer) isolates owners on its own.

    The queries run as a role that bypasses row-level security, so only their explicit owner
    predicates keep X's rows from Y.
    """
    (x, x_docs), (y, y_docs) = two_ready_visitors
    x_owner: OwnerScope = await x.owner()
    y_owner: OwnerScope = await y.owner()
    x_ids: list[UUID] = [UUID(document_id) for document_id in x_docs]
    assert x.conversation_id is not None
    x_conversation: UUID = UUID(x.conversation_id)
    await x.ask("What is the secret code?", x_docs)  # gives X's conversation a turn to hide
    query_vector: list[float] = await x.container.embedder.embed_query(QUESTION_WITH_X_MARKER)
    config_id: int = x.container.embedding_config_id

    async with owner_session(bypassrls_sessions, y_owner) as session:
        x_document: Document | None = await session.scalar(
            select(Document).where(Document.id == x_ids[0])
        )
        assert x_document is not None  # control: nothing but the application filter stops Y
        assert x_document.current_version_id is not None
        all_documents: int = await session.scalar(select(func.count()).select_from(Document)) or 0
        assert all_documents > len(y_docs)
        as_x: list[Evidence] = await search_evidence(
            session,
            owner=x_owner,
            document_ids=x_ids,
            query_vector=query_vector,
            embedding_config_id=config_id,
        )
        assert as_x  # control: the same query finds X's chunks for X

        as_y: list[Evidence] = await search_evidence(
            session,
            owner=y_owner,
            document_ids=x_ids,
            query_vector=query_vector,
            embedding_config_id=config_id,
        )
        assert as_y == []
        assert await get_document(session, y_owner, x_ids[0]) is None
        assert await get_document_view(session, y_owner, x_ids[0]) is None
        assert await find_by_content_hash(session, y_owner, x_document.content_sha256) is None
        assert await count_documents(session, y_owner) == len(y_docs)
        y_views: list[DocumentView] = await list_document_views(session, y_owner)
        assert [str(view.id) for view in y_views] == y_docs
        assert await count_chunks(session, y_owner, x_document.current_version_id) == 0
        assert await conversation_exists(session, y_owner, x_conversation) is False
        assert await document_readiness(session, y_owner, x_ids) == {}
        assert await list_turns(session, y_owner, x_conversation) == []
        assert await list_turns(session, x_owner, x_conversation)  # control
