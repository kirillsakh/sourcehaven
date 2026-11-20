import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4, uuid7

import httpx
import pytest
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sourcehaven.composition import ContainerOverrides
from sourcehaven.domain.models import OwnerScope
from sourcehaven.storage.db import owner_session
from sourcehaven.storage.files import LocalFileStore
from sourcehaven.storage.models import Chunk, Document, DocumentVersion, IngestionJob, TurnSource
from sourcehaven.storage.repositories.conversations import (
    NewTurn,
    add_generating_turn,
    document_readiness,
)
from sourcehaven.storage.repositories.documents import RemovalOutcome, delete_document
from sourcehaven.worker.runner import run_once
from tests.support.clock import FakeClock
from tests.support.db import TestDatabaseUrls
from tests.support.jobs import retire_all_jobs
from tests.support.visitors import ReadyVisitorFactory, Visitor

pytestmark = pytest.mark.integration

NOT_FOUND_BODY: Final[dict[str, object]] = {"code": "not_found"}
IN_USE_BODY: Final[dict[str, object]] = {"code": "document_in_use"}
RECENT: Final[timedelta] = timedelta(minutes=1)
STALE: Final[timedelta] = timedelta(minutes=11)
BLOCKED_FOR: Final[float] = 0.3
TIMEOUT: Final[float] = 10.0


@pytest.fixture(autouse=True)
async def no_leftover_jobs(database_urls: TestDatabaseUrls) -> None:
    await retire_all_jobs(database_urls.maintenance)


async def _row_counts(visitor: Visitor, document_id: str) -> dict[str, int]:
    """Count the rows that belong to the document, as the visitor's owner sees them."""
    owner: OwnerScope = await visitor.owner()
    document: UUID = UUID(document_id)
    async with owner_session(visitor.container.sessions, owner) as session:
        return {
            "documents": await _count(session, select(Document.id).where(Document.id == document)),
            "versions": await _count(
                session, select(DocumentVersion.id).where(DocumentVersion.document_id == document)
            ),
            "jobs": await _count(
                session,
                select(IngestionJob.id).where(
                    IngestionJob.version_id.in_(
                        select(DocumentVersion.id).where(DocumentVersion.document_id == document)
                    )
                ),
            ),
            "chunks": await _count(session, select(Chunk.id).where(Chunk.document_id == document)),
        }


async def _count(session: AsyncSession, statement: Select[UUID]) -> int:
    count: int | None = await session.scalar(select(func.count()).select_from(statement.subquery()))
    assert count is not None
    return count


def _stored_files(visitor: Visitor, document_id: str, owner: OwnerScope) -> list[Path]:
    directory: Path = visitor.container.settings.uploads_dir / str(owner.owner_id) / document_id
    return [path for path in directory.rglob("*") if path.is_file()] if directory.exists() else []


async def _insert_generating_turn(
    visitor: Visitor, document_ids: Sequence[str], *, created_at: datetime
) -> None:
    """Store a `generating` turn that selects the documents, as if an answer were being written."""
    owner: OwnerScope = await visitor.owner()
    assert visitor.conversation_id is not None
    async with owner_session(visitor.container.sessions, owner) as session:
        await add_generating_turn(
            session,
            NewTurn(
                id=uuid7(),
                owner=owner,
                conversation_id=UUID(visitor.conversation_id),
                client_request_id=uuid4(),
                question="warranty?",
                selected_document_ids=[UUID(document_id) for document_id in document_ids],
                model=None,
                created_at=created_at,
            ),
        )


async def _source_rows(visitor: Visitor) -> list[TurnSource]:
    owner: OwnerScope = await visitor.owner()
    async with owner_session(visitor.container.sessions, owner) as session:
        return list((await session.scalars(select(TurnSource))).all())


async def test_removal_deletes_document_rows_and_file(ready_visitor: ReadyVisitorFactory) -> None:
    visitor, (doc,) = await ready_visitor("facts_small_en.pdf")
    owner: OwnerScope = await visitor.owner()
    before: dict[str, int] = await _row_counts(visitor, doc)
    assert all(count > 0 for count in before.values()), (
        before
    )  # control: there is something to remove
    assert len(_stored_files(visitor, doc, owner)) == 1

    response: httpx.Response = await visitor.client.delete(f"/api/documents/{doc}")

    assert response.status_code == 204 and response.content == b""
    assert await _row_counts(visitor, doc) == {
        "documents": 0,
        "versions": 0,
        "jobs": 0,
        "chunks": 0,
    }
    assert _stored_files(visitor, doc, owner) == []
    listed: list[dict[str, Any]] = (await visitor.client.get("/api/documents")).json()
    assert listed == []


async def test_removal_keeps_turns_and_marks_sources_deleted(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    visitor, (removed, kept) = await ready_visitor("facts_small_en.pdf", "multipage_en.pdf")
    await visitor.ask("How long is the warranty period?", [removed, kept])
    await visitor.ask("When was the bridge completed?", [removed, kept])
    before: dict[str, Any] = await visitor.conversation()
    sources_before: list[dict[str, Any]] = [s for t in before["turns"] for s in t["sources"]]
    assert {s["document_id"] for s in sources_before} == {removed, kept}  # control

    response: httpx.Response = await visitor.client.delete(f"/api/documents/{removed}")

    assert response.status_code == 204
    after: dict[str, Any] = await visitor.conversation()
    assert len(after["turns"]) == len(before["turns"]) == 2
    for turn_before, turn_after in zip(before["turns"], after["turns"], strict=True):
        assert turn_after["question"] == turn_before["question"]
        assert turn_after["text"] == turn_before["text"]
        assert len(turn_after["sources"]) == len(turn_before["sources"])
        for source_before, source_after in zip(
            turn_before["sources"], turn_after["sources"], strict=True
        ):
            if source_before["document_id"] == removed:
                assert source_after["document_id"] is None and source_after["quote"] == ""
                for kept_field in ("label", "document_name", "pages", "cited"):
                    assert source_after[kept_field] == source_before[kept_field]
            else:
                assert source_after == source_before
    rows: list[TurnSource] = await _source_rows(visitor)
    assert UUID(removed) not in {row.document_id for row in rows}
    assert all((row.document_id is None) == (row.quote_snapshot == "") for row in rows)


async def test_removal_is_refused_while_an_answer_is_generating(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    visitor, (doc,) = await ready_visitor("facts_small_en.pdf")
    await visitor.ask("How long is the warranty period?", [doc])
    await _insert_generating_turn(visitor, [doc], created_at=visitor.container.clock() - RECENT)
    quotes_before: list[str] = [row.quote_snapshot for row in await _source_rows(visitor)]
    assert quotes_before and all(quotes_before)

    response: httpx.Response = await visitor.client.delete(f"/api/documents/{doc}")

    assert response.status_code == 409 and response.json() == IN_USE_BODY
    assert (await visitor.document(doc))["state"] == "ready"
    assert [row.quote_snapshot for row in await _source_rows(visitor)] == quotes_before
    assert all(row.document_id is not None for row in await _source_rows(visitor))


async def test_generating_turn_of_another_document_does_not_block_removal(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    visitor, (doc, other) = await ready_visitor("facts_small_en.pdf", "multipage_en.pdf")
    await _insert_generating_turn(visitor, [other], created_at=visitor.container.clock())
    assert (await visitor.client.delete(f"/api/documents/{doc}")).status_code == 204


async def test_stale_generating_turn_does_not_block_removal(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    clock: FakeClock = FakeClock(datetime.now(UTC))
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(clock=clock)
    )
    await _insert_generating_turn(visitor, [doc], created_at=clock() - STALE)
    response: httpx.Response = await visitor.client.delete(f"/api/documents/{doc}")
    assert response.status_code == 204


async def test_generating_turn_blocks_removal_until_it_is_stale(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    clock: FakeClock = FakeClock(datetime.now(UTC))
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(clock=clock)
    )
    await _insert_generating_turn(visitor, [doc], created_at=clock())
    assert (await visitor.client.delete(f"/api/documents/{doc}")).status_code == 409
    clock.advance(STALE)
    assert (await visitor.client.delete(f"/api/documents/{doc}")).status_code == 204


async def test_removal_twice_is_404(ready_visitor: ReadyVisitorFactory) -> None:
    visitor, (doc,) = await ready_visitor("facts_small_en.pdf")
    assert (await visitor.client.delete(f"/api/documents/{doc}")).status_code == 204
    second: httpx.Response = await visitor.client.delete(f"/api/documents/{doc}")
    assert second.status_code == 404 and second.json() == NOT_FOUND_BODY


async def test_unknown_id_is_404(visitor: Visitor) -> None:
    response: httpx.Response = await visitor.client.delete(f"/api/documents/{uuid4()}")
    assert response.status_code == 404 and response.json() == NOT_FOUND_BODY


async def test_removal_during_ingestion_publishes_nothing(visitor: Visitor) -> None:
    doc: str = (await visitor.upload("facts_small_en.pdf")).json()["id"]
    assert (await visitor.document(doc))["state"] == "queued"

    assert (await visitor.client.delete(f"/api/documents/{doc}")).status_code == 204
    while await run_once(visitor.container):
        pass

    assert await _row_counts(visitor, doc) == {
        "documents": 0,
        "versions": 0,
        "jobs": 0,
        "chunks": 0,
    }
    assert (await visitor.client.get("/api/documents")).json() == []


async def test_same_file_can_be_uploaded_again_after_removal(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    visitor, (doc,) = await ready_visitor("facts_small_en.pdf")
    assert (await visitor.client.delete(f"/api/documents/{doc}")).status_code == 204

    again: httpx.Response = await visitor.upload("facts_small_en.pdf")

    assert again.status_code == 202
    assert again.json()["id"] != doc


class _UnremovableFileStore(LocalFileStore):
    """A file store that keeps and serves files but cannot remove them, like a read-only mount."""

    async def delete_prefix(self, prefix: str) -> None:
        raise OSError("disk is read-only")


async def test_file_removal_failure_still_succeeds(
    ready_visitor: ReadyVisitorFactory, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    store: _UnremovableFileStore = _UnremovableFileStore(tmp_path / "uploads")
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(file_store=store)
    )
    caplog.set_level(logging.ERROR)

    response: httpx.Response = await visitor.client.delete(f"/api/documents/{doc}")

    assert response.status_code == 204
    assert await _row_counts(visitor, doc) == {
        "documents": 0,
        "versions": 0,
        "jobs": 0,
        "chunks": 0,
    }
    failures: list[logging.LogRecord] = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(failures) == 1
    assert doc in failures[0].getMessage()
    assert "facts_small_en" not in caplog.text


async def _remove(visitor: Visitor, document_id: UUID, owner: OwnerScope) -> RemovalOutcome:
    async with owner_session(visitor.container.sessions, owner) as session:
        return await delete_document(session, owner, document_id, now=visitor.container.clock())


async def test_question_scope_check_serialises_with_removal(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    visitor, (doc,) = await ready_visitor("facts_small_en.pdf")
    owner: OwnerScope = await visitor.owner()
    assert visitor.conversation_id is not None
    document: UUID = UUID(doc)
    turn: NewTurn = NewTurn(
        id=uuid7(),
        owner=owner,
        conversation_id=UUID(visitor.conversation_id),
        client_request_id=uuid4(),
        question="warranty?",
        selected_document_ids=[document],
        model=None,
        created_at=visitor.container.clock(),
    )

    async with owner_session(visitor.container.sessions, owner) as question_session:
        assert await document_readiness(question_session, owner, [document], lock=True) == {
            document: True
        }
        removal: asyncio.Task[RemovalOutcome] = asyncio.create_task(
            _remove(visitor, document, owner)
        )
        try:
            done, _pending = await asyncio.wait({removal}, timeout=BLOCKED_FOR)
            assert not done, "removal must wait for the question that has locked the document"
            await add_generating_turn(question_session, turn)
        except BaseException:
            removal.cancel()
            raise

    assert await asyncio.wait_for(removal, TIMEOUT) is RemovalOutcome.IN_USE
    assert (await visitor.document(doc))["state"] == "ready"


async def test_question_scope_check_after_removal_finds_the_document_gone(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    visitor, (doc,) = await ready_visitor("facts_small_en.pdf")
    owner: OwnerScope = await visitor.owner()
    document: UUID = UUID(doc)

    async def check_scope() -> dict[UUID, bool]:
        async with owner_session(visitor.container.sessions, owner) as session:
            return await document_readiness(session, owner, [document], lock=True)

    check: asyncio.Task[dict[UUID, bool]]
    async with owner_session(visitor.container.sessions, owner) as removal_session:
        outcome: RemovalOutcome = await delete_document(
            removal_session, owner, document, now=visitor.container.clock()
        )
        assert outcome is RemovalOutcome.REMOVED
        check = asyncio.create_task(check_scope())
        try:
            done, _pending = await asyncio.wait({check}, timeout=BLOCKED_FOR)
            assert not done, (
                "the scope check must wait for the removal that has locked the document"
            )
        except BaseException:
            check.cancel()
            raise

    assert await asyncio.wait_for(check, TIMEOUT) == {}
