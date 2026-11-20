from uuid import UUID

from fastapi.sse import ServerSentEvent

from sourcehaven.api.schemas import TurnSourceResponse
from sourcehaven.api.sse import encode_event, to_server_sent_event
from sourcehaven.domain.models import Citation, Evidence, PageSpan
from sourcehaven.qa.citations import CitationResult
from sourcehaven.qa.events import Delta, Done, Failed, Progress, SourcesFinal, TurnStarted

TURN_ID: UUID = UUID("01890000-0000-7000-8000-000000000001")
DOCUMENT_ID: UUID = UUID("01890000-0000-7000-8000-000000000002")
VERSION_ID: UUID = UUID("01890000-0000-7000-8000-000000000003")


def _evidence(text: str) -> Evidence:
    return Evidence(
        chunk_id=UUID("01890000-0000-7000-8000-000000000004"),
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        document_name="report.pdf",
        text=text,
        span=PageSpan(start=3, end=4),
        similarity=0.5,
    )


def test_sse_mapping_of_delta_and_error() -> None:
    assert encode_event(Delta("hi")) == ("delta", {"text": "hi"})
    name, payload = encode_event(Failed("failed", "provider_error", "msg", True))
    assert name == "error"
    assert payload == {
        "status": "failed",
        "code": "provider_error",
        "message": "msg",
        "retryable": True,
    }


def test_sse_mapping_of_turn_progress_and_done() -> None:
    assert encode_event(TurnStarted(TURN_ID)) == (
        "turn",
        {"turn_id": str(TURN_ID), "status": "generating"},
    )
    assert encode_event(Progress("retrieving")) == ("progress", {"stage": "retrieving"})
    assert encode_event(Done(12, 3)) == (
        "done",
        {"status": "complete", "usage": {"input_tokens": 12, "output_tokens": 3}},
    )
    assert encode_event(Done(None, None)) == (
        "done",
        {"status": "complete", "usage": {"input_tokens": None, "output_tokens": None}},
    )


def test_sse_mapping_of_sources_truncates_quotes() -> None:
    long_text: str = "x" * 301
    result: CitationResult = CitationResult(
        sources=[
            Citation(label="S1", evidence=_evidence("The warranty is 24 months."), cited=True),
            Citation(label="S2", evidence=_evidence(long_text), cited=False),
        ],
        invalid_labels=["S9"],
    )
    name, payload = encode_event(SourcesFinal(result))
    assert name == "sources"
    assert payload == {
        "sources": [
            {
                "label": "S1",
                "cited": True,
                "document_id": str(DOCUMENT_ID),
                "document_name": "report.pdf",
                "pages": {"start": 3, "end": 4},
                "quote": "The warranty is 24 months.",
            },
            {
                "label": "S2",
                "cited": False,
                "document_id": str(DOCUMENT_ID),
                "document_name": "report.pdf",
                "pages": {"start": 3, "end": 4},
                "quote": "x" * 300,
            },
        ],
        "invalid_citation_labels": ["S9"],
    }


def test_streamed_sources_have_the_stored_turn_shape() -> None:
    citation: Citation = Citation(label="S1", evidence=_evidence("A fact."), cited=True)
    _, payload = encode_event(SourcesFinal(CitationResult(sources=[citation], invalid_labels=[])))
    streamed: object = payload["sources"]
    assert isinstance(streamed, list) and streamed
    assert [TurnSourceResponse.model_validate(s).model_dump(mode="json") for s in streamed] == (
        streamed
    )


def test_server_sent_event_carries_name_and_payload() -> None:
    event: ServerSentEvent = to_server_sent_event(Delta("hi"))
    assert event.event == "delta"
    assert event.data == {"text": "hi"}
