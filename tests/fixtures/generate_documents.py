"""Regenerate the synthetic PDF fixtures used by the parser, ingestion and retrieval tests.

Run with ``uv run python -m tests.fixtures.generate_documents``. Output is byte-for-byte
deterministic, so a regeneration that changes ``tests/fixtures/documents`` signals a real change.
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

FIXTURES_DIR: Path = Path(__file__).resolve().parent
DOCUMENTS_DIR: Path = FIXTURES_DIR / "documents"
# A standard PDF base font: nothing is embedded, which keeps the fixtures small and licence-free.
FONT_NAME: str = "Helvetica"
FONT_SIZE: int = 12
LINE_HEIGHT: int = 18
MARGIN: int = 72

# Each page is a tuple of text lines; an empty page renders no text at all.
type Page = tuple[str, ...]

# Pre-wrapped so every line fits the A4 text area at the chosen font size.
FILLER: Page = (
    "This paragraph is neutral filler text that gives the page",
    "enough body to be split into chunks without carrying",
    "any answerable fact.",
)

DOCUMENTS: dict[str, tuple[Page, ...]] = {
    "facts_small_en.pdf": (
        ("The Sourcehaven warranty period is 24 months.",),
        ("Support requests are answered within 3 business days.",),
    ),
    "multipage_en.pdf": tuple(
        (
            *FILLER,
            f"MARKER-PAGE-{number}",
            *(("The bridge was completed in 1931.",) if number == 4 else ()),
        )
        for number in range(1, 7)
    ),
    "visitor_x_en.pdf": (("Visitor X secret code: ALPHA-7731.",),),
    "visitor_y_en.pdf": (("Visitor Y secret code: BRAVO-4410.",),),
    "blank_pages.pdf": ((), ()),
}


def render_pdf(path: Path, pages: tuple[Page, ...]) -> None:
    """Write one deterministic PDF with the given pages of text lines.

    Args:
        path: Destination file, overwritten if present.
        pages: Pages in order, each a tuple of lines drawn top to bottom.
    """
    _, height = A4
    canvas: Canvas = Canvas(str(path), pagesize=A4, invariant=1, pageCompression=0)
    canvas.setTitle(path.stem)
    canvas.setAuthor("Sourcehaven fixtures")
    canvas.setSubject("Synthetic test document")
    canvas.setCreator("tests.fixtures.generate_documents")
    for lines in pages:
        for index, line in enumerate(lines):
            canvas.setFont(FONT_NAME, FONT_SIZE)
            canvas.drawString(MARGIN, height - MARGIN - index * LINE_HEIGHT, line)
        canvas.showPage()
    canvas.save()


def generate_documents() -> list[Path]:
    """Regenerate every fixture PDF in the documents directory.

    Returns:
        The paths written, in generation order.
    """
    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, pages in DOCUMENTS.items():
        path: Path = DOCUMENTS_DIR / name
        render_pdf(path, pages)
        written.append(path)
    return written


if __name__ == "__main__":
    for written_path in generate_documents():
        print(written_path.name)
