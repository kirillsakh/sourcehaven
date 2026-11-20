from bisect import bisect_left, bisect_right
from collections.abc import Sequence

from langchain_text_splitters import RecursiveCharacterTextSplitter

from sourcehaven.domain.models import ChunkDraft, ExtractedPage, PageSpan
from sourcehaven.embeddings.protocol import TokenCounter

_PAGE_JOINER: str = "\n\n"
_SEPARATORS: list[str] = ["\n\n", "\n", ". ", "! ", "? ", "… ", " "]


def chunk_pages(
    pages: Sequence[ExtractedPage],
    counter: TokenCounter,
    *,
    chunk_tokens: int,
    chunk_overlap: int,
) -> list[ChunkDraft]:
    """Split page text into token-bounded chunks that remember which pages they cover.

    Pages with a text layer are joined with a blank line into one document text, so a chunk may
    span a page boundary. Pages without a text layer contribute no text, and page numbers stay
    those of the physical pages. Every chunk is trimmed of surrounding whitespace and satisfies
    `document_text[char_start:char_end] == text` and `token_count == counter.count(text)`, where
    `document_text` is the pages joined as described.

    The splitter prefers paragraph, line and sentence boundaries, then spaces. A run of text
    without any of those separators that is longer than `chunk_tokens` is cut at the longest
    prefix that fits (backing up to the last whitespace if there is one); such cuts carry no
    overlap, and no text is dropped.

    LangChain's `add_start_index` is not used: it searches from an offset that subtracts the
    overlap measured in tokens from a position measured in characters, and any text search
    cannot tell apart the periodic or repeated passages that overlapping chunks share. Offsets are
    therefore exact by construction: `_OffsetSplitter` repeats the recursive split-and-merge of
    `RecursiveCharacterTextSplitter` while carrying each piece's position in the document, and
    produces the same chunk texts as `split_text`.

    Args:
        pages: Extracted pages in physical order.
        counter: Token counter whose output is monotonic in prefix length.
        chunk_tokens: Maximum tokens per chunk.
        chunk_overlap: Tokens shared by consecutive chunks, at most `chunk_tokens`.

    Returns:
        Chunks with consecutive ordinals starting at 0; empty if no page has text.

    Raises:
        ValueError: If the limits are invalid or the counter reports more than `chunk_tokens`
            tokens for a single character.
    """
    splitter: _OffsetSplitter = _OffsetSplitter(
        chunk_size=chunk_tokens,
        chunk_overlap=chunk_overlap,
        length_function=counter.count,
        separators=_SEPARATORS,
        keep_separator="end",
    )
    text_pages: list[ExtractedPage] = [page for page in pages if page.has_text_layer]
    page_starts: list[int] = []
    page_ends: list[int] = []
    cursor: int = 0
    for page in text_pages:
        if page_starts:
            cursor += len(_PAGE_JOINER)
        page_starts.append(cursor)
        cursor += len(page.text)
        page_ends.append(cursor)
    document: str = _PAGE_JOINER.join(page.text for page in text_pages)

    drafts: list[ChunkDraft] = []
    for raw_start, raw_chunk in splitter.split_with_offsets(document):
        for char_start, piece in _fit(raw_start, raw_chunk, counter, chunk_tokens):
            char_end: int = char_start + len(piece)
            first: int = bisect_right(page_ends, char_start)
            last: int = bisect_left(page_starts, char_end) - 1
            drafts.append(
                ChunkDraft(
                    ordinal=len(drafts),
                    text=piece,
                    token_count=counter.count(piece),
                    span=PageSpan(start=text_pages[first].page, end=text_pages[last].page),
                    char_start=char_start,
                    char_end=char_end,
                )
            )
    return drafts


type _Piece = tuple[int, str]


class _OffsetSplitter(RecursiveCharacterTextSplitter):
    """`RecursiveCharacterTextSplitter` that also reports where each chunk starts.

    Mirrors the base class's recursive split (`_split_text`) and merge (`_merge_splits`) for
    `keep_separator="end"` and literal separators, so chunk texts match `split_text`. Chunks that
    the base class emits whole because no finer separator is left are not trimmed here, and
    merged chunks are trimmed with their offsets adjusted.
    """

    def split_with_offsets(self, text: str) -> list[_Piece]:
        """Split text into chunks.

        Returns:
            Pairs of the chunk's offset in `text` and the chunk text.
        """
        return self._split_offsets(text, 0, self._separators)

    def _split_offsets(self, text: str, base: int, separators: list[str]) -> list[_Piece]:
        separator: str = separators[-1]
        finer: list[str] = []
        for index, candidate in enumerate(separators):
            if candidate in text:
                separator = candidate
                finer = separators[index + 1 :]
                break

        chunks: list[_Piece] = []
        mergeable: list[_Piece] = []
        for piece in _split_keeping_separator_at_end(text, base, separator):
            if self._length_function(piece[1]) < self._chunk_size:
                mergeable.append(piece)
                continue
            chunks.extend(self._merge_pieces(mergeable))
            mergeable = []
            if finer:
                chunks.extend(self._split_offsets(piece[1], piece[0], finer))
            else:
                chunks.append(piece)
        chunks.extend(self._merge_pieces(mergeable))
        return chunks

    def _merge_pieces(self, pieces: list[_Piece]) -> list[_Piece]:
        merged: list[_Piece] = []
        current: list[_Piece] = []
        total: int = 0
        for piece in pieces:
            length: int = self._length_function(piece[1])
            if total + length > self._chunk_size and current:
                _append_trimmed(merged, current)
                while total > self._chunk_overlap or (
                    total + length > self._chunk_size and total > 0
                ):
                    total -= self._length_function(current[0][1])
                    current = current[1:]
            current.append(piece)
            total += length
        _append_trimmed(merged, current)
        return merged


def _split_keeping_separator_at_end(text: str, base: int, separator: str) -> list[_Piece]:
    parts: list[str] = text.split(separator)
    pieces: list[_Piece] = []
    offset: int = base
    for index, part in enumerate(parts):
        piece: str = part + separator if index < len(parts) - 1 else part
        if piece:
            pieces.append((offset, piece))
        offset += len(piece)
    return pieces


def _append_trimmed(chunks: list[_Piece], pieces: list[_Piece]) -> None:
    if not pieces:
        return
    joined: str = "".join(text for _, text in pieces)
    trimmed: str = joined.strip()
    if trimmed:
        chunks.append((pieces[0][0] + len(joined) - len(joined.lstrip()), trimmed))


def _fit(start: int, chunk: str, counter: TokenCounter, limit: int) -> list[_Piece]:
    """Trim a chunk and cut it into pieces of at most `limit` tokens.

    Returns:
        Pairs of the document offset of each non-blank trimmed piece and the piece.
    """
    pieces: list[_Piece] = []
    position: int = 0
    while position < len(chunk):
        remaining: str = chunk[position:]
        length: int = len(remaining)
        if counter.count(remaining.strip()) > limit:
            length = _longest_fitting_prefix(remaining, counter, limit)
        piece: str = remaining[:length]
        stripped: str = piece.strip()
        if stripped:
            pieces.append((start + position + len(piece) - len(piece.lstrip()), stripped))
        position += length
    return pieces


def _longest_fitting_prefix(text: str, counter: TokenCounter, limit: int) -> int:
    if counter.count(text[:1]) > limit:
        raise ValueError("A single character exceeds the chunk token limit")
    low: int = 1
    high: int = len(text)
    while low < high:
        middle: int = (low + high + 1) // 2
        if counter.count(text[:middle].strip()) <= limit:
            low = middle
        else:
            high = middle - 1
    if low < len(text):
        boundary: int = text.rfind(" ", 1, low + 1)
        if boundary != -1:
            return boundary + 1
    return low
