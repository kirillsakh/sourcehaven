import contextlib
import logging
from pathlib import Path

import pypdf
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.errors import DependencyError

from sourcehaven.domain.models import ExtractedSource
from sourcehaven.ingestion.errors import IngestionError
from sourcehaven.ingestion.pdf import PdfAdapter
from tests.support.fixtures import fixture


def test_extracts_facts_on_correct_pages() -> None:
    source: ExtractedSource = PdfAdapter().extract(fixture("facts_small_en.pdf"), max_pages=300)
    assert source.page_count == 2
    assert [page.page for page in source.pages] == [1, 2]
    assert "warranty period is 24 months" in source.pages[0].text
    assert "3 business days" in source.pages[1].text
    assert all(page.has_text_layer for page in source.pages)


def test_extracts_visitor_markers() -> None:
    x: str = PdfAdapter().extract(fixture("visitor_x_en.pdf"), max_pages=300).pages[0].text
    y: str = PdfAdapter().extract(fixture("visitor_y_en.pdf"), max_pages=300).pages[0].text
    assert "Visitor X secret code: ALPHA-7731." in x
    assert "Visitor Y secret code: BRAVO-4410." in y


def test_page_limit() -> None:
    with pytest.raises(IngestionError) as exc:
        PdfAdapter().extract(fixture("multipage_en.pdf"), max_pages=5)
    assert exc.value.code == "too_many_pages"
    assert exc.value.retryable is False


def test_page_count_at_the_limit_is_accepted() -> None:
    source: ExtractedSource = PdfAdapter().extract(fixture("multipage_en.pdf"), max_pages=6)
    assert source.page_count == 6
    assert "MARKER-PAGE-4" in source.pages[3].text


def test_blank_pages_have_no_text_layer() -> None:
    source: ExtractedSource = PdfAdapter().extract(fixture("blank_pages.pdf"), max_pages=300)
    assert [p.has_text_layer for p in source.pages] == [False, False]


def test_damaged_pdf(tmp_path: Path) -> None:
    broken: Path = tmp_path / "broken.pdf"
    broken.write_bytes(fixture("facts_small_en.pdf").read_bytes()[:200])
    with pytest.raises(IngestionError) as exc:
        PdfAdapter().extract(broken, max_pages=300)
    assert exc.value.code == "damaged"
    assert exc.value.retryable is False


def test_non_pdf_bytes_are_damaged(tmp_path: Path) -> None:
    junk: Path = tmp_path / "junk.pdf"
    junk.write_bytes(b"this is not a pdf at all")
    with pytest.raises(IngestionError) as exc:
        PdfAdapter().extract(junk, max_pages=300)
    assert exc.value.code == "damaged"


def test_encrypted_pdf_even_with_empty_user_password(tmp_path: Path) -> None:
    writer: PdfWriter = PdfWriter(clone_from=PdfReader(fixture("facts_small_en.pdf")))
    writer.encrypt(user_password="", owner_password="owner-secret")
    locked: Path = tmp_path / "locked.pdf"
    with locked.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(IngestionError) as exc:
        PdfAdapter().extract(locked, max_pages=300)
    assert exc.value.code == "encrypted"
    assert exc.value.retryable is False


def test_password_protected_pdf(tmp_path: Path) -> None:
    writer: PdfWriter = PdfWriter(clone_from=PdfReader(fixture("facts_small_en.pdf")))
    writer.encrypt(user_password="user-secret")
    locked: Path = tmp_path / "locked.pdf"
    with locked.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(IngestionError) as exc:
        PdfAdapter().extract(locked, max_pages=300)
    assert exc.value.code == "encrypted"


def test_reports_parser_identity() -> None:
    source: ExtractedSource = PdfAdapter().extract(fixture("facts_small_en.pdf"), max_pages=300)
    assert source.parser_name == "pypdf"
    assert source.parser_version == pypdf.__version__


def test_aes256_password_protected_pdf(tmp_path: Path) -> None:
    writer: PdfWriter = PdfWriter(clone_from=PdfReader(fixture("facts_small_en.pdf")))
    writer.encrypt(user_password="user-secret", algorithm="AES-256")
    locked: Path = tmp_path / "locked.pdf"
    with locked.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(IngestionError) as exc:
        PdfAdapter().extract(locked, max_pages=300)
    assert exc.value.code == "encrypted"


def test_missing_crypto_backend_while_opening_means_encrypted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production has no crypto library, so opening an AES-encrypted PDF raises DependencyError."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise DependencyError("cryptography>=3.1 is required for AES algorithm")

    monkeypatch.setattr(pypdf.PdfReader, "__init__", refuse)
    with pytest.raises(IngestionError) as exc:
        PdfAdapter().extract(fixture("facts_small_en.pdf"), max_pages=300)
    assert exc.value.code == "encrypted"


def test_unexpected_extraction_failure_is_damaged(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> str:
        raise ValueError("exotic content stream")

    monkeypatch.setattr(pypdf.PageObject, "extract_text", explode)
    with pytest.raises(IngestionError) as exc:
        PdfAdapter().extract(fixture("facts_small_en.pdf"), max_pages=300)
    assert exc.value.code == "damaged"


def test_dependency_error_during_extraction_is_damaged(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: object, **kwargs: object) -> str:
        raise DependencyError("missing filter dependency")

    monkeypatch.setattr(pypdf.PageObject, "extract_text", explode)
    with pytest.raises(IngestionError) as exc:
        PdfAdapter().extract(fixture("facts_small_en.pdf"), max_pages=300)
    assert exc.value.code == "damaged"


class _RecordCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_pypdf_logs_never_reach_the_root_logger(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Uses its own root handler: pytest also attaches caplog to non-propagating loggers."""
    data: bytearray = bytearray(fixture("facts_small_en.pdf").read_bytes())
    marker: int = data.index(b"endobj")
    data[marker - 40 : marker] = b"\xb7" * 40
    mutated: Path = tmp_path / "mutated.pdf"
    mutated.write_bytes(bytes(data))
    collector: _RecordCollector = _RecordCollector()
    root: logging.Logger = logging.getLogger()
    root.addHandler(collector)
    try:
        with caplog.at_level(logging.DEBUG), contextlib.suppress(IngestionError):
            PdfAdapter().extract(mutated, max_pages=300)
    finally:
        root.removeHandler(collector)
    assert [r for r in collector.records if r.name.startswith("pypdf")] == []
