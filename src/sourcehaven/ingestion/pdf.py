import logging
from pathlib import Path
from typing import Protocol

import pypdf
from pypdf.errors import DependencyError

from sourcehaven.domain.models import ExtractedPage, ExtractedSource
from sourcehaven.ingestion.errors import IngestionError

_MIN_TEXT_LAYER_CHARACTERS: int = 20

# pypdf warnings quote fragments of the untrusted document; logs must never contain its content.
logging.getLogger("pypdf").addHandler(logging.NullHandler())
logging.getLogger("pypdf").propagate = False


class SourceAdapter(Protocol):
    def extract(self, path: Path, *, max_pages: int) -> ExtractedSource:
        """Parse the file into per-page text.

        Raises:
            IngestionError: If the file cannot be turned into pages.
        """
        ...


class PdfAdapter:
    """Extracts per-page text from PDF files with pypdf."""

    def extract(self, path: Path, *, max_pages: int) -> ExtractedSource:
        """Parse a PDF into per-page text.

        Any encrypted PDF is rejected, including one that opens with an empty password: it is
        simpler and more conservative than deciding which protections are acceptable. Document
        text and file names are deliberately kept out of errors and logs.

        Args:
            path: Location of the PDF file.
            max_pages: Maximum number of pages to accept.

        Returns:
            The pages in order, each flagged with whether it has a usable text layer.

        Raises:
            IngestionError: With code `encrypted`, `damaged` or `too_many_pages`.
        """
        reader: pypdf.PdfReader = _open(path)
        try:
            if reader.is_encrypted:
                raise IngestionError("encrypted")
            page_count: int = len(reader.pages)
            if page_count > max_pages:
                raise IngestionError("too_many_pages")
            pages: tuple[ExtractedPage, ...] = tuple(
                _extract_page(number, page) for number, page in enumerate(reader.pages, start=1)
            )
        except IngestionError, MemoryError:
            raise
        except Exception as error:  # untrusted input: any parser failure means a damaged file
            raise IngestionError("damaged") from error
        return ExtractedSource(
            pages=pages,
            page_count=page_count,
            parser_name="pypdf",
            parser_version=pypdf.__version__,
        )


def _open(path: Path) -> pypdf.PdfReader:
    try:
        return pypdf.PdfReader(path)
    except DependencyError as error:
        # Opening an AES-encrypted file needs a crypto library that is deliberately not installed.
        raise IngestionError("encrypted") from error
    except MemoryError:
        raise
    except Exception as error:  # untrusted input: any parser failure means a damaged file
        raise IngestionError("damaged") from error


def _extract_page(number: int, page: pypdf.PageObject) -> ExtractedPage:
    text: str = page.extract_text()
    significant: int = sum(1 for character in text if not character.isspace())
    return ExtractedPage(
        page=number, text=text, has_text_layer=significant >= _MIN_TEXT_LAYER_CHARACTERS
    )
