from dataclasses import dataclass
from typing import Literal
from uuid import UUID


@dataclass(frozen=True)
class OwnerScope:
    """The data owner every visitor-data query is restricted to.

    It is resolved only on the server from a validated session; clients never supply it.
    """

    owner_id: UUID


@dataclass(frozen=True)
class PageSpan:
    """An inclusive range of 1-based physical page numbers within a source document."""

    start: int
    end: int
    kind: Literal["page_span"] = "page_span"


@dataclass(frozen=True)
class ExtractedPage:
    """The text of one physical PDF page.

    Attributes:
        page: 1-based physical page number.
        text: Extracted text, possibly empty.
        has_text_layer: Whether the page yielded enough text to be treated as searchable.
    """

    page: int
    text: str
    has_text_layer: bool


@dataclass(frozen=True)
class ExtractedSource:
    """Per-page text of a parsed source document together with the parser that produced it."""

    pages: tuple[ExtractedPage, ...]
    page_count: int
    parser_name: str
    parser_version: str


@dataclass(frozen=True)
class ChunkDraft:
    """A retrievable passage cut from a source document, before it is persisted or embedded.

    Attributes:
        ordinal: 0-based position of the chunk within the document.
        text: Chunk text with surrounding whitespace removed.
        token_count: Tokens in `text` according to the counter used for chunking.
        span: Pages the chunk covers.
        char_start: Offset of `text` in the document text built from all pages that have a text
            layer, joined with a blank line.
        char_end: Exclusive end offset matching `char_start`.
    """

    ordinal: int
    text: str
    token_count: int
    span: PageSpan
    char_start: int
    char_end: int


@dataclass(frozen=True)
class Evidence:
    """A retrieved passage that may support an answer.

    Attributes:
        chunk_id: The chunk the passage comes from.
        document_id: The document that holds the chunk.
        version_id: The document version the chunk was cut from.
        document_name: The document's display name, for labelling the passage.
        text: Passage text.
        span: Pages the passage covers.
        similarity: Cosine similarity to the query, `1 - cosine distance`; higher is closer.
    """

    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    document_name: str
    text: str
    span: PageSpan
    similarity: float


@dataclass(frozen=True)
class Citation:
    """A passage supplied to the model, and whether the answer cited it.

    Attributes:
        label: The `S#` label the model saw for the passage.
        evidence: The supplied passage.
        cited: Whether the answer text contains the label. This does not mean the passage
            supports the claim next to it.
        quote: The excerpt stored and shown with the citation, at most 300 characters.
    """

    label: str
    evidence: Evidence
    cited: bool
    quote: str
