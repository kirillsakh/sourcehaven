from typing import Literal

IngestionErrorCode = Literal[
    "encrypted",
    "damaged",
    "too_many_pages",
    "empty",
    "embedding_unavailable",
    "internal",
]


class IngestionError(Exception):
    """A document could not be ingested.

    Attributes:
        code: Stable machine-readable reason, safe to show to the visitor.
        retryable: Whether trying again later without changing the document may succeed.
    """

    def __init__(self, code: IngestionErrorCode, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code: IngestionErrorCode = code
        self.retryable: bool = retryable
