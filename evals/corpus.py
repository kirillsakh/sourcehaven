import hashlib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from sourcehaven.domain.models import ExtractedPage, ExtractedSource, PageSpan
from sourcehaven.ingestion.pdf import SourceAdapter

_ID_PATTERN: re.Pattern[str] = re.compile(r"[a-z0-9-]+")
_SHA256_PATTERN: re.Pattern[str] = re.compile(r"[0-9a-f]{64}")
_STRING_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "author",
    "url",
    "sha256",
    "licence",
    "licence_url",
    "layout",
)
_POSITIVE_INT_FIELDS: tuple[str, ...] = ("size_bytes", "page_count")
_OPTIONAL_FIELDS: tuple[str, ...] = ("pages", "selected_by_default")
_CHUNK_BYTES: int = 1 << 16


class CorpusError(Exception):
    """The corpus manifest is invalid or a corpus file cannot be fetched or verified."""


@dataclass(frozen=True)
class CorpusDocument:
    """One pinned public-domain or openly licensed source document of the benchmark corpus.

    Attributes:
        page_range: Inclusive physical pages that form the benchmark excerpt, or None for the
            whole document.
        selected_by_default: Whether the default benchmark run includes this document.
    """

    id: str
    title: str
    author: str
    url: str
    sha256: str
    size_bytes: int
    page_count: int
    licence: str
    licence_url: str
    layout: str
    page_range: PageSpan | None
    selected_by_default: bool


@dataclass(frozen=True)
class Manifest:
    version: int
    documents: tuple[CorpusDocument, ...]

    def document(self, document_id: str) -> CorpusDocument:
        for document in self.documents:
            if document.id == document_id:
                return document
        raise KeyError(document_id)


def load_manifest(path: Path) -> Manifest:
    """Read and validate the corpus manifest.

    Args:
        path: Location of the TOML manifest.

    Returns:
        The validated manifest, documents in file order.

    Raises:
        CorpusError: If the file cannot be parsed or any field is invalid; the message lists
            every problem found, not only the first.
    """
    try:
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise CorpusError(f"Cannot read the corpus manifest {path}: {error}") from error

    problems: list[str] = []
    version: object = raw.get("version")
    if _positive_int(version) is None:
        problems.append("version must be a positive integer")
    tables: object = raw.get("document", [])
    entries: list[object] = tables if isinstance(tables, list) else []
    if not isinstance(tables, list):
        problems.append("document must be an array of tables")

    documents: list[CorpusDocument] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(entries):
        label: str = _label(index, entry)
        document: CorpusDocument | None = _parse_document(entry, label, problems)
        if document is None:
            continue
        if document.id in seen_ids:
            problems.append(f"{label}: duplicate id")
        seen_ids.add(document.id)
        documents.append(document)

    checked_version: int | None = _positive_int(version)
    if problems or checked_version is None:
        raise CorpusError(f"Invalid corpus manifest {path}:\n" + "\n".join(problems))
    return Manifest(version=checked_version, documents=tuple(documents))


def document_path(files_dir: Path, document: CorpusDocument) -> Path:
    return files_dir / f"{document.id}.pdf"


def file_sha256(path: Path) -> str:
    """Hex SHA-256 digest of the file's bytes."""
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def verify_file(path: Path, document: CorpusDocument) -> bool:
    """Whether the file exists and matches the pinned size and SHA-256 of the document."""
    try:
        return path.stat().st_size == document.size_bytes and file_sha256(path) == document.sha256
    except OSError:
        return False


async def fetch_corpus(
    manifest: Manifest, files_dir: Path, client: httpx.AsyncClient
) -> list[Path]:
    """Download every document that is missing or fails verification.

    Files that already match the manifest are not requested again. A download is written to a
    temporary file and renamed only once its size and SHA-256 match, so an interrupted or
    changed upstream file never appears under the final name.

    Args:
        manifest: The documents to make available.
        files_dir: Directory for the PDFs; created when missing.
        client: HTTP client used for downloads.

    Returns:
        The verified file of each document, in manifest order.

    Raises:
        CorpusError: If a download fails or does not match the pinned size and hash.
    """
    files_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for document in manifest.documents:
        target: Path = document_path(files_dir, document)
        if not verify_file(target, document):
            await _download(document, target, client)
        paths.append(target)
    return paths


def extract_document(
    document: CorpusDocument, path: Path, adapter: SourceAdapter, *, max_pages: int
) -> ExtractedSource:
    """Extract the benchmark excerpt of a document with its physical page numbers.

    The adapter parses the whole original file, so page numbers stay physical; pages outside
    the document's page range are then dropped.

    Args:
        document: The corpus entry; its page range selects the excerpt (all pages when None).
        path: The verified PDF of the document.
        adapter: Parser for the file.
        max_pages: Page limit passed to the adapter, applied to the whole file.

    Returns:
        The excerpt pages with the page count and parser of the whole file.

    Raises:
        IngestionError: If the adapter cannot parse the file.
    """
    extracted: ExtractedSource = adapter.extract(path, max_pages=max_pages)
    span: PageSpan | None = document.page_range
    pages: tuple[ExtractedPage, ...] = extracted.pages
    if span is not None:
        pages = tuple(page for page in pages if span.start <= page.page <= span.end)
    return ExtractedSource(
        pages=pages,
        page_count=extracted.page_count,
        parser_name=extracted.parser_name,
        parser_version=extracted.parser_version,
    )


async def _download(document: CorpusDocument, target: Path, client: httpx.AsyncClient) -> None:
    part: Path = target.with_name(f".{document.id}.part")
    digest: hashlib._Hash = hashlib.sha256()
    written: int = 0
    try:
        async with client.stream("GET", document.url, follow_redirects=True) as response:
            response.raise_for_status()
            with part.open("wb") as file:
                async for chunk in response.aiter_bytes(_CHUNK_BYTES):
                    written += len(chunk)
                    if written > document.size_bytes:
                        break
                    digest.update(chunk)
                    file.write(chunk)
        actual: str = digest.hexdigest()
        if written != document.size_bytes or actual != document.sha256:
            raise CorpusError(
                f"{document.id}: downloaded file does not match the manifest "
                f"(expected sha256 {document.sha256} and {document.size_bytes} bytes, got sha256 "
                f"{actual} and {'more than ' if written > document.size_bytes else ''}"
                f"{written} bytes). If the upstream file changed, update the manifest "
                "deliberately and bump its version."
            )
        part.replace(target)
    except httpx.HTTPError as error:
        part.unlink(missing_ok=True)
        raise CorpusError(f"{document.id}: cannot download {document.url}: {error}") from error
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def _parse_document(entry: object, label: str, problems: list[str]) -> CorpusDocument | None:
    if not isinstance(entry, dict):
        problems.append(f"{label}: must be a table")
        return None
    count: int = len(problems)
    allowed: set[str] = {*_STRING_FIELDS, *_POSITIVE_INT_FIELDS, *_OPTIONAL_FIELDS}
    for unknown in sorted(set(entry) - allowed):
        problems.append(f"{label}: unknown field {unknown}")

    strings: dict[str, str] = {}
    for name in _STRING_FIELDS:
        value: object = entry.get(name)
        if isinstance(value, str) and value.strip():
            strings[name] = value
        else:
            problems.append(f"{label}: {name} must be a non-empty string")
    numbers: dict[str, int] = {}
    for name in _POSITIVE_INT_FIELDS:
        number: int | None = _positive_int(entry.get(name))
        if number is not None:
            numbers[name] = number
        else:
            problems.append(f"{label}: {name} must be a positive integer")

    document_id: str = strings.get("id", "")
    if document_id and not _ID_PATTERN.fullmatch(document_id):
        problems.append(f"{label}: id must match [a-z0-9-]+")
    sha256: str = strings.get("sha256", "")
    if sha256 and not _SHA256_PATTERN.fullmatch(sha256):
        problems.append(f"{label}: sha256 must be 64 lowercase hex characters")

    selected: object = entry.get("selected_by_default", True)
    if not isinstance(selected, bool):
        problems.append(f"{label}: selected_by_default must be true or false")
    page_range: PageSpan | None = _parse_pages(entry.get("pages"), numbers.get("page_count"))
    if entry.get("pages") is not None and page_range is None:
        problems.append(f"{label}: pages must be [first, last] within 1..page_count, first <= last")

    if len(problems) > count:
        return None
    return CorpusDocument(
        id=strings["id"],
        title=strings["title"],
        author=strings["author"],
        url=strings["url"],
        sha256=strings["sha256"],
        size_bytes=numbers["size_bytes"],
        page_count=numbers["page_count"],
        licence=strings["licence"],
        licence_url=strings["licence_url"],
        layout=strings["layout"],
        page_range=page_range,
        selected_by_default=bool(selected),
    )


def _parse_pages(value: object, page_count: int | None) -> PageSpan | None:
    if not isinstance(value, list) or len(value) != 2 or page_count is None:
        return None
    first: int | None = _positive_int(value[0])
    last: int | None = _positive_int(value[1])
    if first is None or last is None or first > last or last > page_count:
        return None
    return PageSpan(start=first, end=last)


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _label(index: int, entry: object) -> str:
    identifier: object = entry.get("id") if isinstance(entry, dict) else None
    return f"document {identifier}" if isinstance(identifier, str) else f"document #{index + 1}"
