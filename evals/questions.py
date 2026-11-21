import hashlib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from evals.corpus import CorpusDocument, Manifest
from sourcehaven.domain.models import PageSpan

type QuestionKind = Literal["answerable", "unanswerable", "conflict"]

MAX_SPAN_CHARACTERS: Final[int] = 250

_ID_PATTERN: re.Pattern[str] = re.compile(r"[a-z0-9-]+")
_KINDS: tuple[QuestionKind, ...] = ("answerable", "unanswerable", "conflict")
_QUESTION_FIELDS: frozenset[str] = frozenset(
    {"id", "kind", "text", "documents", "reference_answer", "gold"}
)
_GOLD_FIELDS: frozenset[str] = frozenset({"document", "page", "text"})
_CHUNK_BYTES: int = 1 << 16


class QuestionFileError(Exception):
    """The question file is invalid or cannot be read."""


@dataclass(frozen=True)
class GoldSpan:
    """A passage a person copied from a page of a corpus document as evidence for an answer.

    Attributes:
        page: Physical, 1-based page number.
    """

    document: str
    page: int
    text: str


@dataclass(frozen=True)
class Question:
    """A benchmark question with its resolved document selection and gold evidence.

    Attributes:
        documents: Documents selected for the question; never empty.
        reference_answer: One-sentence answer, or None for unanswerable questions.
        gold: Evidence spans; empty exactly for unanswerable questions.
    """

    id: str
    kind: QuestionKind
    text: str
    documents: tuple[str, ...]
    reference_answer: str | None
    gold: tuple[GoldSpan, ...]


def load_questions(path: Path, manifest: Manifest) -> tuple[Question, ...]:
    """Read and validate the question file against the corpus manifest.

    A file without questions is valid. An empty or omitted `documents` list selects every
    document that is selected by default, in manifest order; a listed selection keeps its order.

    Args:
        path: Location of the TOML question file.
        manifest: The corpus that questions and gold spans refer to.

    Returns:
        The validated questions in file order.

    Raises:
        QuestionFileError: If the file cannot be parsed or any question is invalid; the message
            lists every problem found, not only the first.
    """
    try:
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise QuestionFileError(f"Cannot read the question file {path}: {error}") from error

    problems: list[str] = [
        f"unknown top-level key {key}" for key in sorted(set(raw) - {"question"})
    ]
    tables: object = raw.get("question", [])
    entries: list[object] = tables if isinstance(tables, list) else []
    if not isinstance(tables, list):
        problems.append("question must be an array of tables")

    questions: list[Question] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(entries):
        label: str = _label(index, entry)
        question: Question | None = _parse_question(entry, label, manifest, problems)
        if question is None:
            continue
        if question.id in seen_ids:
            problems.append(f"{label}: duplicate id")
        seen_ids.add(question.id)
        questions.append(question)

    if problems:
        raise QuestionFileError(f"Invalid question file {path}:\n" + "\n".join(problems))
    return tuple(questions)


def file_sha256(path: Path) -> str:
    """Hex SHA-256 digest of the file's bytes."""
    digest: Any = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_CHUNK_BYTES):
            digest.update(chunk)
    return str(digest.hexdigest())


def _parse_question(
    entry: object, label: str, manifest: Manifest, problems: list[str]
) -> Question | None:
    if not isinstance(entry, dict):
        problems.append(f"{label}: must be a table")
        return None
    count: int = len(problems)
    for unknown in sorted(set(entry) - _QUESTION_FIELDS):
        problems.append(f"{label}: unknown field {unknown}")

    question_id: object = entry.get("id")
    if not isinstance(question_id, str) or not _ID_PATTERN.fullmatch(question_id):
        problems.append(f"{label}: id must be a string matching [a-z0-9-]+")
    kind: object = entry.get("kind")
    if kind not in _KINDS:
        problems.append(f"{label}: kind must be one of {', '.join(_KINDS)}")
    text: object = entry.get("text")
    if not _non_empty_string(text):
        problems.append(f"{label}: text must be a non-empty string")
    reference_answer: object = entry.get("reference_answer")
    if reference_answer is not None and not _non_empty_string(reference_answer):
        problems.append(f"{label}: reference_answer must be a non-empty string when given")
    documents: tuple[str, ...] | None = _resolve_documents(
        entry.get("documents", []), label, manifest, problems
    )
    gold: tuple[GoldSpan, ...] | None = _parse_gold(
        entry.get("gold", []), label, manifest, problems
    )
    if kind == "conflict" and entry.get("documents") in (None, []):
        problems.append(f"{label}: a conflict question must list its documents")

    if kind in _KINDS and documents is not None and gold is not None:
        _check_kind(kind, documents, gold, reference_answer, label, problems)

    if len(problems) > count or documents is None or gold is None:
        return None
    assert isinstance(question_id, str)
    assert kind in _KINDS
    assert isinstance(text, str)
    return Question(
        id=question_id,
        kind=kind,
        text=text,
        documents=documents,
        reference_answer=reference_answer if isinstance(reference_answer, str) else None,
        gold=gold,
    )


def _resolve_documents(
    value: object, label: str, manifest: Manifest, problems: list[str]
) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        problems.append(f"{label}: documents must be a list of document ids")
        return None
    listed: list[str] = [item for item in value if isinstance(item, str)]
    if not listed:
        defaults: tuple[str, ...] = tuple(
            document.id for document in manifest.documents if document.selected_by_default
        )
        if not defaults:
            problems.append(f"{label}: no document is selected by default")
            return None
        return defaults
    known: set[str] = {document.id for document in manifest.documents}
    valid: bool = True
    for unknown in sorted(set(listed) - known):
        problems.append(f"{label}: documents lists {unknown}, which is not in the manifest")
        valid = False
    if len(set(listed)) != len(listed):
        problems.append(f"{label}: documents lists a document more than once")
        valid = False
    return tuple(listed) if valid else None


def _parse_gold(
    value: object, label: str, manifest: Manifest, problems: list[str]
) -> tuple[GoldSpan, ...] | None:
    if not isinstance(value, list):
        problems.append(f"{label}: gold must be an array of tables")
        return None
    spans: list[GoldSpan] = []
    valid: bool = True
    for index, item in enumerate(value, start=1):
        span: GoldSpan | None = _parse_span(item, f"{label}: gold #{index}", manifest, problems)
        if span is None:
            valid = False
        else:
            spans.append(span)
    return tuple(spans) if valid else None


def _parse_span(
    item: object, label: str, manifest: Manifest, problems: list[str]
) -> GoldSpan | None:
    if not isinstance(item, dict):
        problems.append(f"{label}: must be a table")
        return None
    count: int = len(problems)
    for unknown in sorted(set(item) - _GOLD_FIELDS):
        problems.append(f"{label}: unknown field {unknown}")

    document_id: object = item.get("document")
    document: CorpusDocument | None = None
    if isinstance(document_id, str):
        document = next((d for d in manifest.documents if d.id == document_id), None)
    if document is None:
        problems.append(f"{label}: document must be a document id from the manifest")
    page: object = item.get("page")
    if not isinstance(page, int) or isinstance(page, bool):
        problems.append(f"{label}: page must be an integer")
    elif document is not None:
        first: int
        last: int
        first, last = _page_bounds(document)
        if not first <= page <= last:
            problems.append(
                f"{label}: page {page} is outside pages {first}-{last} of {document.id}"
            )
    text: object = item.get("text")
    if not isinstance(text, str) or not text.strip():
        problems.append(f"{label}: text must be a non-empty string")
    elif len(text) > MAX_SPAN_CHARACTERS:
        problems.append(
            f"{label}: text has {len(text)} characters, more than {MAX_SPAN_CHARACTERS}"
        )

    if len(problems) > count:
        return None
    assert isinstance(document_id, str)
    assert isinstance(page, int)
    assert isinstance(text, str)
    return GoldSpan(document=document_id, page=page, text=text)


def _check_kind(
    kind: QuestionKind,
    documents: tuple[str, ...],
    gold: tuple[GoldSpan, ...],
    reference_answer: object,
    label: str,
    problems: list[str],
) -> None:
    outside: list[str] = sorted({span.document for span in gold} - set(documents))
    for document_id in outside:
        problems.append(f"{label}: gold is in {document_id}, which is not selected")
    if kind == "unanswerable":
        if gold:
            problems.append(f"{label}: an unanswerable question must have no gold")
        if reference_answer is not None:
            problems.append(f"{label}: an unanswerable question must have no reference_answer")
        return
    if reference_answer is None:
        problems.append(f"{label}: reference_answer is required for a {kind} question")
    if not gold:
        problems.append(f"{label}: a {kind} question needs at least one gold span")
    if kind == "conflict" and len({span.document for span in gold}) < 2:
        problems.append(f"{label}: a conflict question needs gold spans in two documents")


def _page_bounds(document: CorpusDocument) -> tuple[int, int]:
    span: PageSpan | None = document.page_range
    if span is not None:
        return span.start, span.end
    return 1, document.page_count


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _label(index: int, entry: object) -> str:
    identifier: object = entry.get("id") if isinstance(entry, dict) else None
    return str(identifier) if isinstance(identifier, str) else f"question #{index + 1}"
