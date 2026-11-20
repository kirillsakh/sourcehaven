import asyncio
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sourcehaven.api.schemas import QuestionRequest
from sourcehaven.composition import ContainerOverrides
from sourcehaven.generation.fake import ScriptedChatModel
from sourcehaven.qa import service as qa_service
from sourcehaven.qa.service import QAService, TurnStream
from sourcehaven.storage.repositories.conversations import NewTurn, add_generating_turn
from tests.support.embeddings import (
    CountingEmbedder,
    DocumentControlledEmbedder,
    QueryFailingEmbedder,
    QuoteFailingEmbedder,
)
from tests.support.streaming import SseEvent
from tests.support.visitors import ReadyVisitorFactory, StoredTurn, TwoReadyVisitors, Visitor
from tests.support.waiting import eventually

pytestmark = pytest.mark.integration

# multipage_en.pdf is one chunk spanning pages 1-6 with the default chunk size; at 40 tokens
# every page becomes its own chunk, so a page-specific citation is possible.
ONE_CHUNK_PER_PAGE: dict[str, object] = {"chunk_tokens": 40, "chunk_overlap": 5}
NO_EVIDENCE_ANSWER: str = "I couldn't find information about this in the selected documents."


async def test_answer_streams_and_cites_correct_page(ready_visitor: ReadyVisitorFactory) -> None:
    visitor, (doc,) = await ready_visitor("multipage_en.pdf", settings_overrides=ONE_CHUNK_PER_PAGE)
    events: list[SseEvent] = await visitor.ask("When was the bridge completed?", [doc])
    assert [e.name for e in events][:2] == ["turn", "progress"]
    assert [e.name for e in events][-2:] == ["sources", "done"]
    assert any(e.name == "delta" for e in events)
    cited: list[dict[str, object]] = [s for s in events[-2].data["sources"] if s["cited"]]
    assert cited and cited[0]["pages"] == {"start": 4, "end": 4}


async def test_first_delta_arrives_before_generation_finishes(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    gate: asyncio.Event = asyncio.Event()
    model: ScriptedChatModel = ScriptedChatModel(script=["Part one ", "part two [S1]"], gate=gate)
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(chat_model=model)
    )
    async with visitor.stream_question("warranty?", [doc]) as stream:
        names: list[str] = [await stream.next_event_name() for _ in range(3)]
        assert names == ["turn", "progress", "delta"]
        assert not gate.is_set()
        gate.set()
        assert (await stream.collect_rest())[-1].name == "done"
    assert model.calls  # the delta came from the model, not the no-evidence answer


async def test_mid_stream_error_keeps_partial_text_as_failed(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    model: ScriptedChatModel = ScriptedChatModel(script=["Partial ", "more"], fail_after=1)
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(chat_model=model)
    )
    events: list[SseEvent] = await visitor.ask("warranty?", [doc])
    assert events[-1].name == "error" and events[-1].data["status"] == "failed"
    assert events[-1].data == {
        "status": "failed",
        "code": "provider_error",
        "message": "The answer could not be completed. Please try again.",
        "retryable": True,
    }
    turn: dict[str, object] = (await visitor.conversation())["turns"][-1]
    assert turn["status"] == "failed" and turn["text"] == "Partial "


async def test_answer_cut_off_by_the_length_limit_is_interrupted(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    model: ScriptedChatModel = ScriptedChatModel(
        script=["Partial ", "answer [S1]"], finish_reason="length"
    )
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(chat_model=model)
    )
    events: list[SseEvent] = await visitor.ask("warranty?", [doc])
    assert [event.name for event in events if event.name in ("done", "sources")] == []
    assert events[-1].name == "error"
    assert events[-1].data == {
        "status": "interrupted",
        "code": "length_limit",
        "message": "This answer was cut off because it reached the length limit. Please try again.",
        "retryable": True,
    }
    turn: dict[str, object] = (await visitor.conversation())["turns"][-1]
    assert turn["status"] == "interrupted" and turn["text"] == "Partial answer [S1]"


@pytest.mark.parametrize(
    ("script", "finish_reason"), [([""], "length"), (["  ", "\n"], "stop"), ([""], None)]
)
async def test_answer_without_visible_text_is_failed(
    ready_visitor: ReadyVisitorFactory, script: list[str], finish_reason: str | None
) -> None:
    model: ScriptedChatModel = ScriptedChatModel(script=script, finish_reason=finish_reason)
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(chat_model=model)
    )
    events: list[SseEvent] = await visitor.ask("warranty?", [doc])
    assert events[-1].name == "error"
    assert events[-1].data == {
        "status": "failed",
        "code": "empty_answer",
        "message": "The answer could not be completed. Please try again.",
        "retryable": True,
    }
    turn: dict[str, object] = (await visitor.conversation())["turns"][-1]
    assert turn["status"] == "failed"


async def test_disconnect_mid_stream_marks_turn_interrupted(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    gate: asyncio.Event = asyncio.Event()
    model: ScriptedChatModel = ScriptedChatModel(script=["Started ", "never sent"], gate=gate)
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(chat_model=model)
    )
    async with visitor.stream_question("warranty?", [doc]) as stream:
        await stream.read_until("delta")
    # leaving the context closes the HTTP stream
    turn: dict[str, object] = await eventually(
        lambda: visitor.last_turn(), until=lambda t: t["status"] != "generating"
    )
    assert turn["status"] == "interrupted" and turn["text"] == "Started "
    assert turn["sources"] == []
    gate.set()  # the scripted model would otherwise pause the next answer after its first chunk
    assert (await visitor.ask("warranty?", [doc]))[-1].name == "done"  # conversation not blocked


async def test_insufficient_evidence_makes_no_llm_call(ready_visitor: ReadyVisitorFactory) -> None:
    model: ScriptedChatModel = ScriptedChatModel()
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf",
        overrides=ContainerOverrides(chat_model=model),
        settings_overrides={"evidence_threshold": 0.99},
    )
    events: list[SseEvent] = await visitor.ask("Who painted the Mona Lisa?", [doc])
    assert events[-1].name == "done" and model.calls == []
    assert [e.data["text"] for e in events if e.name == "delta"] == [NO_EVIDENCE_ANSWER]
    assert events[-2].data == {"sources": [], "invalid_citation_labels": []}
    turn: dict[str, Any] = await visitor.last_turn()
    assert turn["status"] == "complete" and turn["text"] == NO_EVIDENCE_ANSWER
    assert turn["sources"] == []


async def test_completed_turn_is_stored_with_its_sources(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    visitor, (doc,) = await ready_visitor("facts_small_en.pdf")
    events: list[SseEvent] = await visitor.ask("  How long is the warranty period?  ", [doc])
    streamed_text: str = "".join(e.data["text"] for e in events if e.name == "delta")
    usage: dict[str, Any] = events[-1].data["usage"]
    assert usage["input_tokens"] > 0 and usage["output_tokens"] > 0
    turn: dict[str, Any] = await visitor.last_turn()
    assert turn["id"] == events[0].data["turn_id"]
    assert turn["status"] == "complete"
    assert turn["question"] == "How long is the warranty period?"
    assert turn["text"] == streamed_text
    assert turn["sources"] == events[-2].data["sources"]
    first: dict[str, Any] = turn["sources"][0]
    assert first["label"] == "S1"
    assert first["cited"] is True and first["document_id"] == doc
    assert first["document_name"] == "facts_small_en.pdf"
    assert 0 < len(first["quote"]) <= 300


async def test_question_validation_errors(ready_visitor: ReadyVisitorFactory) -> None:
    visitor, (doc,) = await ready_visitor("facts_small_en.pdf")
    for body in (
        {"question": "   ", "document_ids": [doc]},
        {"question": "x" * 2001, "document_ids": [doc]},
        {"question": "ok?", "document_ids": []},
        {"question": "ok?", "document_ids": [str(uuid4()) for _ in range(11)]},
    ):
        response: httpx.Response = await visitor.post_turn(body)
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_request"
    assert (await visitor.conversation())["turns"] == []


async def test_question_of_maximum_length_is_accepted(ready_visitor: ReadyVisitorFactory) -> None:
    visitor, (doc,) = await ready_visitor("facts_small_en.pdf")
    events: list[SseEvent] = await visitor.ask("x" * 2000, [doc])
    assert events[-1].name == "done"


async def test_question_rejects_not_ready_document(visitor: Visitor) -> None:
    doc_id: str = (await visitor.upload("facts_small_en.pdf")).json()["id"]  # worker not run
    response: httpx.Response = await visitor.post_turn(
        {"question": "warranty?", "document_ids": [doc_id]}
    )
    assert response.status_code == 422 and response.json()["code"] == "document_not_ready"
    assert (await visitor.conversation())["turns"] == []


async def test_question_with_foreign_document_returns_404(
    two_ready_visitors: TwoReadyVisitors,
) -> None:
    (_, x_docs), (y, _) = two_ready_visitors
    foreign: httpx.Response = await y.post_turn({"question": "code?", "document_ids": x_docs})
    unknown: httpx.Response = await y.post_turn(
        {"question": "code?", "document_ids": [str(uuid4())]}
    )
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()


async def test_foreign_conversation_is_indistinguishable_from_unknown(
    two_ready_visitors: TwoReadyVisitors,
) -> None:
    (x, _), (y, y_docs) = two_ready_visitors
    assert x.conversation_id is not None
    body: dict[str, object] = {
        "client_request_id": str(uuid4()),
        "kind": "question",
        "question": "kód?",
        "document_ids": y_docs,
    }
    for conversation_id in (x.conversation_id, str(uuid4())):
        read: httpx.Response = await y.client.get(f"/api/conversations/{conversation_id}")
        asked: httpx.Response = await y.client.post(
            f"/api/conversations/{conversation_id}/turns", json=body
        )
        assert read.status_code == asked.status_code == 404
        assert read.json() == asked.json() == {"code": "not_found"}
    assert (await x.conversation())["turns"] == []


async def test_conversations_require_a_session(ready_visitor: ReadyVisitorFactory) -> None:
    visitor, _ = await ready_visitor()
    visitor.client.cookies.clear()
    response: httpx.Response = await visitor.client.post("/api/conversations", json={})
    assert response.status_code == 401 and response.json() == {"code": "session_required"}


async def test_duplicate_client_request_id_is_rejected(ready_visitor: ReadyVisitorFactory) -> None:
    visitor, (doc,) = await ready_visitor("facts_small_en.pdf")
    request_id: str = str(uuid4())
    events: list[SseEvent] = await visitor.ask("warranty?", [doc], client_request_id=request_id)
    response: httpx.Response = await visitor.post_turn(
        {"question": "warranty?", "document_ids": [doc]}, client_request_id=request_id
    )
    assert response.status_code == 409 and response.json()["code"] == "duplicate_request"
    assert response.json()["turn_id"] == events[0].data["turn_id"]


async def test_second_question_while_generating_is_rejected(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    gate: asyncio.Event = asyncio.Event()
    model: ScriptedChatModel = ScriptedChatModel(script=["One ", "two [S1]"], gate=gate)
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(chat_model=model)
    )
    async with visitor.stream_question("warranty?", [doc]) as stream:
        turn_id: str = (await stream.next_event()).data["turn_id"]
        await stream.read_until("delta")
        response: httpx.Response = await visitor.post_turn(
            {"question": "support?", "document_ids": [doc]}
        )
        assert response.status_code == 409
        assert response.json() == {"code": "turn_in_progress", "turn_id": turn_id}
        gate.set()
        assert (await stream.collect_rest())[-1].name == "done"
    assert [turn["status"] for turn in (await visitor.conversation())["turns"]] == ["complete"]


@pytest.mark.parametrize("events_read", [0, 2])
async def test_closing_an_unfinished_stream_marks_turn_interrupted(
    ready_visitor: ReadyVisitorFactory, events_read: int
) -> None:
    visitor, (doc,) = await ready_visitor("facts_small_en.pdf")
    assert visitor.conversation_id is not None
    request: QuestionRequest = QuestionRequest(
        client_request_id=uuid4(),
        kind="question",
        question="warranty?",
        document_ids=[UUID(doc)],
    )
    stream: TurnStream = await QAService(visitor.container).answer(
        await visitor.owner(), UUID(visitor.conversation_id), request
    )
    assert (await visitor.last_turn())["status"] == "generating"
    for _ in range(events_read):
        await anext(stream)
    await stream.aclose()  # GeneratorExit at the suspended yield, as when a response is dropped
    turn: dict[str, Any] = await visitor.last_turn()
    assert turn["status"] == "interrupted" and turn["text"] == ""


async def test_closing_after_the_no_evidence_answer_keeps_its_text(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", settings_overrides={"evidence_threshold": 0.99}
    )
    assert visitor.conversation_id is not None
    request: QuestionRequest = QuestionRequest(
        client_request_id=uuid4(), kind="question", question="Mona Lisa?", document_ids=[UUID(doc)]
    )
    stream: TurnStream = await QAService(visitor.container).answer(
        await visitor.owner(), UUID(visitor.conversation_id), request
    )
    assert [type(await anext(stream)).__name__ for _ in range(3)] == [
        "TurnStarted",
        "Progress",
        "Delta",
    ]
    await stream.aclose()
    turn: dict[str, Any] = await visitor.last_turn()
    assert turn["status"] == "interrupted" and turn["text"] == NO_EVIDENCE_ANSWER


def _supplied_labels(model: ScriptedChatModel) -> list[str]:
    """The passage labels of the model's first call, in prompt order."""
    prompt: str = str(model.calls[0][-1].content)
    return [f"S{number}" for number in range(1, prompt.count('<passage label="') + 1)]


async def test_partially_cited_answer_stores_uncited_passages(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    model: ScriptedChatModel = ScriptedChatModel(script=["Answer ", "[S1]"])
    visitor, (doc,) = await ready_visitor(
        "multipage_en.pdf",
        overrides=ContainerOverrides(chat_model=model),
        settings_overrides=ONE_CHUNK_PER_PAGE,
    )
    events: list[SseEvent] = await visitor.ask("When was the bridge completed?", [doc])
    labels: list[str] = _supplied_labels(model)
    assert len(labels) > 1
    stored: StoredTurn = await visitor.stored_turn(events[0].data["turn_id"])
    assert stored.sources == [(label, label == "S1") for label in labels]
    exposed: list[tuple[str, bool]] = [
        (source["label"], source["cited"]) for source in (await visitor.last_turn())["sources"]
    ]
    assert exposed == stored.sources


@pytest.mark.parametrize("ending", ["interrupted", "failed"])
async def test_incomplete_turn_stores_every_supplied_passage_uncited(
    ready_visitor: ReadyVisitorFactory, ending: str
) -> None:
    gate: asyncio.Event = asyncio.Event()
    model: ScriptedChatModel = (
        ScriptedChatModel(script=["Partial [S1] ", "more"], gate=gate)
        if ending == "interrupted"
        else ScriptedChatModel(script=["Partial [S1] ", "more"], fail_after=1)
    )
    visitor, (doc,) = await ready_visitor(
        "multipage_en.pdf",
        overrides=ContainerOverrides(chat_model=model),
        settings_overrides=ONE_CHUNK_PER_PAGE,
    )
    async with visitor.stream_question("When was the bridge completed?", [doc]) as stream:
        turn_id: str = (await stream.next_event()).data["turn_id"]
        await stream.read_until("delta")
        if ending == "failed":
            assert (await stream.collect_rest())[-1].name == "error"
    stored: StoredTurn = await visitor.stored_turn(turn_id)
    labels: list[str] = _supplied_labels(model)
    assert stored.status == ending and len(labels) > 1
    assert stored.sources == [(label, False) for label in labels]
    turn: dict[str, Any] = await visitor.last_turn()
    assert turn["status"] == ending and turn["sources"] == []  # nothing validated to show


async def test_retrieval_failure_fails_the_turn_without_calling_the_model(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    model: ScriptedChatModel = ScriptedChatModel()
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf",
        overrides=ContainerOverrides(chat_model=model, embedder=QueryFailingEmbedder()),
    )
    events: list[SseEvent] = await visitor.ask("warranty?", [doc])
    assert [e.name for e in events] == ["turn", "progress", "error"]
    assert events[-1].data == {
        "status": "failed",
        "code": "internal_error",
        "message": "The answer could not be completed. Please try again.",
        "retryable": True,
    }
    assert model.calls == []
    stored: StoredTurn = await visitor.stored_turn(events[0].data["turn_id"])
    assert stored == StoredTurn(status="failed", error_code="internal_error", sources=[])


def _collision() -> IntegrityError:
    return IntegrityError("INSERT INTO turns", None, Exception("unique violation"))


async def test_unexplained_insert_collisions_are_reported_as_turn_in_progress(
    ready_visitor: ReadyVisitorFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    visitor, (doc,) = await ready_visitor("facts_small_en.pdf")
    attempts: list[NewTurn] = []

    async def always_colliding(session: AsyncSession, new: NewTurn) -> None:
        attempts.append(new)
        raise _collision()

    monkeypatch.setattr(qa_service, "add_generating_turn", always_colliding)
    response: httpx.Response = await visitor.post_turn(
        {"question": "warranty?", "document_ids": [doc]}
    )
    assert response.status_code == 409 and response.json() == {"code": "turn_in_progress"}
    assert len(attempts) == qa_service.TURN_INSERT_ATTEMPTS == 2
    assert (await visitor.conversation())["turns"] == []


async def test_insert_collision_with_an_ended_turn_is_retried(
    ready_visitor: ReadyVisitorFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    visitor, (doc,) = await ready_visitor("facts_small_en.pdf")
    attempts: list[NewTurn] = []

    async def collide_once(session: AsyncSession, new: NewTurn) -> None:
        attempts.append(new)
        if len(attempts) == 1:
            raise _collision()
        await add_generating_turn(session, new)

    monkeypatch.setattr(qa_service, "add_generating_turn", collide_once)
    events: list[SseEvent] = await visitor.ask("warranty?", [doc])
    assert events[-1].name == "done" and len(attempts) == 2


async def test_quote_shows_the_supporting_sentence_not_the_passage_start(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    model: ScriptedChatModel = ScriptedChatModel(
        script=["Support requests are answered within 3 business days [S1]."]
    )
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(chat_model=model)
    )
    events: list[SseEvent] = await visitor.ask("How fast is support?", [doc])
    quote: str = events[-2].data["sources"][0]["quote"]
    assert quote.startswith("…") and "within 3 business days." in quote
    assert "warranty" not in quote
    assert (await visitor.last_turn())["sources"][0]["quote"] == quote


async def test_quote_selection_failure_keeps_the_passage_start_and_completes(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    model: ScriptedChatModel = ScriptedChatModel(script=["The warranty is 24 months [S1]."])
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf",
        overrides=ContainerOverrides(chat_model=model, embedder=QuoteFailingEmbedder()),
    )
    events: list[SseEvent] = await visitor.ask("How long is the warranty period?", [doc])
    assert events[-1].name == "done" and events[-1].data["status"] == "complete"
    assert events[-2].data["sources"][0]["quote"].startswith("The Sourcehaven warranty")


async def test_failed_answer_selects_no_quotes(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    embedder: CountingEmbedder = CountingEmbedder()
    model: ScriptedChatModel = ScriptedChatModel(script=["Partial [S1] ", "more"], fail_after=1)
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(chat_model=model, embedder=embedder)
    )
    embedder.reset()
    await visitor.ask("warranty?", [doc])
    assert embedder.query_batches == 0  # passage sentences may have been embedded meanwhile


async def test_passage_sentences_are_embedded_while_the_answer_streams(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    gate: asyncio.Event = asyncio.Event()
    embedder: CountingEmbedder = CountingEmbedder()
    model: ScriptedChatModel = ScriptedChatModel(
        script=["The warranty ", "is 24 months [S1]."], gate=gate
    )
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(chat_model=model, embedder=embedder)
    )
    embedder.reset()
    async with visitor.stream_question("How long is the warranty?", [doc]) as stream:
        await stream.read_until("delta")

        async def document_batches() -> int:
            return embedder.document_batches

        await eventually(document_batches, until=lambda batches: batches == 1)
        assert embedder.query_batches == 0
        gate.set()
        assert (await stream.collect_rest())[-1].name == "done"
    assert embedder.document_batches == 1 and embedder.query_batches == 1


async def test_passage_embedding_failure_keeps_the_passage_start_and_completes(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    embedder: DocumentControlledEmbedder = DocumentControlledEmbedder()
    model: ScriptedChatModel = ScriptedChatModel(script=["The warranty is 24 months [S1]."])
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(chat_model=model, embedder=embedder)
    )
    embedder.fail_documents = True
    events: list[SseEvent] = await visitor.ask("How long is the warranty period?", [doc])
    assert events[-1].name == "done" and events[-1].data["status"] == "complete"
    assert events[-2].data["sources"][0]["quote"].startswith("The Sourcehaven warranty")


async def test_quote_selection_timeout_keeps_the_passage_start_and_completes(
    ready_visitor: ReadyVisitorFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(qa_service, "QUOTE_SELECTION_TIMEOUT_SECONDS", 0.1)
    embedder: DocumentControlledEmbedder = DocumentControlledEmbedder()
    model: ScriptedChatModel = ScriptedChatModel(script=["The warranty is 24 months [S1]."])
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(chat_model=model, embedder=embedder)
    )
    embedder.block_documents = True
    events: list[SseEvent] = await visitor.ask("How long is the warranty period?", [doc])
    assert events[-1].name == "done" and events[-1].data["status"] == "complete"
    assert events[-2].data["sources"][0]["quote"].startswith("The Sourcehaven warranty")
    assert embedder.cancelled


async def test_disconnect_cancels_the_passage_embedding(
    ready_visitor: ReadyVisitorFactory,
) -> None:
    gate: asyncio.Event = asyncio.Event()
    embedder: DocumentControlledEmbedder = DocumentControlledEmbedder()
    model: ScriptedChatModel = ScriptedChatModel(script=["Started ", "never sent"], gate=gate)
    visitor, (doc,) = await ready_visitor(
        "facts_small_en.pdf", overrides=ContainerOverrides(chat_model=model, embedder=embedder)
    )
    embedder.block_documents = True
    async with visitor.stream_question("warranty?", [doc]) as stream:
        await stream.read_until("delta")
        await asyncio.wait_for(embedder.blocked.wait(), timeout=5)

    async def cancelled() -> bool:
        return embedder.cancelled

    await eventually(cancelled, until=lambda flag: flag)
    gate.set()
