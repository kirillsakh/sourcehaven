import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from evals.corpus import (
    CorpusDocument,
    CorpusError,
    Manifest,
    document_path,
    extract_document,
    fetch_corpus,
    load_manifest,
    verify_file,
)
from sourcehaven.domain.models import PageSpan
from sourcehaven.ingestion.pdf import PdfAdapter
from tests.support.fixtures import fixture

_PDF_BYTES: bytes = fixture("multipage_en.pdf").read_bytes()
_PDF_SHA256: str = hashlib.sha256(_PDF_BYTES).hexdigest()


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    return json.dumps(value)


def _document_table(fields: dict[str, object]) -> str:
    lines: list[str] = ["[[document]]"]
    lines.extend(f"{key} = {_toml_value(value)}" for key, value in fields.items())
    return "\n".join(lines)


def _document_fields(document_id: str) -> dict[str, object]:
    return {
        "id": document_id,
        "title": f"Title of {document_id}",
        "author": "An Author",
        "url": f"https://example.org/{document_id}.pdf",
        "sha256": _PDF_SHA256,
        "size_bytes": len(_PDF_BYTES),
        "page_count": 300,
        "licence": "CC BY 4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "layout": "single-column",
    }


def write_manifest(tmp_path: Path, **book_overrides: object) -> Path:
    contract: dict[str, object] = _document_fields("contract")
    book: dict[str, object] = {**_document_fields("book"), **book_overrides}
    tables: list[str] = [_document_table(contract), _document_table(book)]
    path: Path = tmp_path / "manifest.toml"
    path.write_text("version = 1\n\n" + "\n\n".join(tables) + "\n", encoding="utf-8")
    return path


def make_document(
    document_id: str = "contract",
    *,
    size_bytes: int = len(_PDF_BYTES),
    page_range: PageSpan | None = None,
) -> CorpusDocument:
    return CorpusDocument(
        id=document_id,
        title=f"Title of {document_id}",
        author="An Author",
        url=f"https://example.org/{document_id}.pdf",
        sha256=_PDF_SHA256,
        size_bytes=size_bytes,
        page_count=300,
        licence="CC BY 4.0",
        licence_url="https://creativecommons.org/licenses/by/4.0/",
        layout="single-column",
        page_range=page_range,
        selected_by_default=True,
    )


def make_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_loads_documents_with_optional_range(tmp_path: Path) -> None:
    manifest: Manifest = load_manifest(
        write_manifest(tmp_path, pages=[17, 100], selected_by_default=False)
    )

    book: CorpusDocument = manifest.document("book")
    contract: CorpusDocument = manifest.document("contract")

    assert manifest.version == 1
    assert [doc.id for doc in manifest.documents] == ["contract", "book"]
    assert book.page_range == PageSpan(start=17, end=100) and not book.selected_by_default
    assert contract.page_range is None and contract.selected_by_default


def test_unknown_document_raises_key_error(tmp_path: Path) -> None:
    manifest: Manifest = load_manifest(write_manifest(tmp_path))

    with pytest.raises(KeyError):
        manifest.document("missing")


@pytest.mark.parametrize(
    "bad",
    [
        {"sha256": "abc"},
        {"sha256": "A" * 64},
        {"pages": [5, 2]},
        {"pages": [1, 999]},
        {"pages": [0, 3]},
        {"id": "contract"},
        {"id": "Bad_Id"},
        {"size_bytes": 0},
        {"page_count": 0},
    ],
)
def test_rejects_invalid_manifests(tmp_path: Path, bad: dict[str, object]) -> None:
    with pytest.raises(CorpusError):
        load_manifest(write_manifest(tmp_path, **bad))


def test_rejects_a_non_positive_version(tmp_path: Path) -> None:
    path: Path = write_manifest(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace("version = 1", "version = 0"))

    with pytest.raises(CorpusError, match="version"):
        load_manifest(path)


def test_reports_every_problem_at_once(tmp_path: Path) -> None:
    with pytest.raises(CorpusError) as error:
        load_manifest(write_manifest(tmp_path, sha256="abc", pages=[5, 2]))

    assert "sha256" in str(error.value) and "pages" in str(error.value)


def test_rejects_a_missing_field(tmp_path: Path) -> None:
    path: Path = tmp_path / "manifest.toml"
    path.write_text('version = 1\n\n[[document]]\nid = "a"\n', encoding="utf-8")

    with pytest.raises(CorpusError, match="title"):
        load_manifest(path)


def test_document_path_is_the_id_with_a_pdf_suffix(tmp_path: Path) -> None:
    assert document_path(tmp_path, make_document("book")) == tmp_path / "book.pdf"


def test_verify_file_checks_size_and_hash(tmp_path: Path) -> None:
    document: CorpusDocument = make_document()
    target: Path = document_path(tmp_path, document)

    assert not verify_file(target, document)
    target.write_bytes(_PDF_BYTES)
    assert verify_file(target, document)
    target.write_bytes(_PDF_BYTES[:-1] + b"x")
    assert not verify_file(target, document)


async def test_fetch_downloads_verifies_and_skips_verified_files(tmp_path: Path) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, content=_PDF_BYTES)

    document: CorpusDocument = make_document()
    manifest: Manifest = Manifest(version=1, documents=(document,))
    async with make_client(handler) as client:
        paths: list[Path] = await fetch_corpus(manifest, tmp_path, client)
        assert verify_file(paths[0], document) and len(requests) == 1

        await fetch_corpus(manifest, tmp_path, client)
        assert len(requests) == 1


async def test_fetch_creates_the_files_directory_and_follows_redirects(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("contract.pdf"):
            return httpx.Response(302, headers={"location": "https://example.org/real.pdf"})
        return httpx.Response(200, content=_PDF_BYTES)

    document: CorpusDocument = make_document()
    files_dir: Path = tmp_path / "nested" / "files"
    async with make_client(handler) as client:
        paths: list[Path] = await fetch_corpus(Manifest(1, (document,)), files_dir, client)

    assert verify_file(paths[0], document)
    assert sorted(path.name for path in files_dir.iterdir()) == ["contract.pdf"]


async def test_fetch_replaces_a_partial_file(tmp_path: Path) -> None:
    document: CorpusDocument = make_document()
    document_path(tmp_path, document).write_bytes(b"%PDF-1.7 trunc")

    async with make_client(lambda request: httpx.Response(200, content=_PDF_BYTES)) as client:
        await fetch_corpus(Manifest(1, (document,)), tmp_path, client)

    assert verify_file(document_path(tmp_path, document), document)


async def test_fetch_refuses_a_changed_upstream_file(tmp_path: Path) -> None:
    document: CorpusDocument = make_document()
    changed: bytes = _PDF_BYTES[:-1] + b"x"

    async with make_client(lambda request: httpx.Response(200, content=changed)) as client:
        with pytest.raises(CorpusError, match="contract") as error:
            await fetch_corpus(Manifest(1, (document,)), tmp_path, client)

    assert _PDF_SHA256 in str(error.value) and hashlib.sha256(changed).hexdigest() in str(
        error.value
    )
    assert not document_path(tmp_path, document).exists()
    assert list(tmp_path.iterdir()) == []


async def test_fetch_refuses_a_wrong_size(tmp_path: Path) -> None:
    document: CorpusDocument = make_document(size_bytes=len(_PDF_BYTES) + 1)

    async with make_client(lambda request: httpx.Response(200, content=_PDF_BYTES)) as client:
        with pytest.raises(CorpusError, match="contract"):
            await fetch_corpus(Manifest(1, (document,)), tmp_path, client)

    assert list(tmp_path.iterdir()) == []


async def test_fetch_reports_http_errors_by_document_id(tmp_path: Path) -> None:
    document: CorpusDocument = make_document()

    async with make_client(lambda request: httpx.Response(404)) as client:
        with pytest.raises(CorpusError, match="contract"):
            await fetch_corpus(Manifest(1, (document,)), tmp_path, client)

    assert list(tmp_path.iterdir()) == []


def test_extract_keeps_only_the_excerpt_with_physical_numbers() -> None:
    document: CorpusDocument = make_document(page_range=PageSpan(start=3, end=5))

    source = extract_document(document, fixture("multipage_en.pdf"), PdfAdapter(), max_pages=300)

    assert [page.page for page in source.pages] == [3, 4, 5]
    assert source.page_count == 6 and source.parser_name == "pypdf"


def test_extract_keeps_every_page_without_a_range() -> None:
    document: CorpusDocument = make_document()

    source = extract_document(document, fixture("multipage_en.pdf"), PdfAdapter(), max_pages=300)

    assert [page.page for page in source.pages] == [1, 2, 3, 4, 5, 6]
