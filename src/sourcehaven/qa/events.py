"""Events a turn produces while it is answered, in the order a client receives them."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sourcehaven.qa.citations import CitationResult


@dataclass(frozen=True)
class TurnStarted:
    """The turn row exists and is generating; always the first event."""

    turn_id: UUID


@dataclass(frozen=True)
class Progress:
    stage: Literal["retrieving"]


@dataclass(frozen=True)
class Delta:
    """Incremental answer text; provisional until `SourcesFinal` and `Done` arrive."""

    text: str


@dataclass(frozen=True)
class SourcesFinal:
    """Every passage given to the model with its validated citation flag."""

    result: CitationResult


@dataclass(frozen=True)
class Done:
    """The turn completed; token counts are those the provider reported, if any."""

    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class Failed:
    """The turn ended without a complete answer; its partial text is stored.

    Attributes:
        status: The stored turn status.
        code: Stable machine-readable reason.
        message: Text for the visitor; it never quotes the question, passages or the error.
        retryable: Whether asking again may succeed.
    """

    status: Literal["failed", "interrupted"]
    code: str
    message: str
    retryable: bool


type TurnEvent = TurnStarted | Progress | Delta | SourcesFinal | Done | Failed
