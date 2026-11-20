"""Wire format of the turn event stream (spec section 11.2)."""

from fastapi.sse import ServerSentEvent

from sourcehaven.api.schemas import PageRange, TurnSourceResponse
from sourcehaven.domain.models import Citation
from sourcehaven.qa.events import (
    Delta,
    Done,
    Failed,
    Progress,
    SourcesFinal,
    TurnEvent,
    TurnStarted,
)


def _source(citation: Citation) -> dict[str, object]:
    """Serialise a source exactly as `GET /api/conversations/{id}` returns it later."""
    return TurnSourceResponse(
        label=citation.label,
        cited=citation.cited,
        document_id=citation.evidence.document_id,
        document_name=citation.evidence.document_name,
        pages=PageRange(start=citation.evidence.span.start, end=citation.evidence.span.end),
        quote=citation.quote,
    ).model_dump(mode="json")


def encode_event(event: TurnEvent) -> tuple[str, dict[str, object]]:
    """Return the SSE event name and JSON payload for a turn event."""
    match event:
        case TurnStarted(turn_id=turn_id):
            return "turn", {"turn_id": str(turn_id), "status": "generating"}
        case Progress(stage=stage):
            return "progress", {"stage": stage}
        case Delta(text=text):
            return "delta", {"text": text}
        case SourcesFinal(result=result):
            return "sources", {
                "sources": [_source(citation) for citation in result.sources],
                "invalid_citation_labels": list(result.invalid_labels),
            }
        case Done(input_tokens=input_tokens, output_tokens=output_tokens):
            return "done", {
                "status": "complete",
                "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            }
        case Failed(status=status, code=code, message=message, retryable=retryable):
            return "error", {
                "status": status,
                "code": code,
                "message": message,
                "retryable": retryable,
            }


def to_server_sent_event(event: TurnEvent) -> ServerSentEvent:
    name, payload = encode_event(event)
    return ServerSentEvent(event=name, data=payload)
