from pathlib import Path

_DOCUMENTS: Path = Path(__file__).resolve().parent.parent / "fixtures" / "documents"


def fixture(name: str) -> Path:
    """Return the path of a committed document fixture, independent of the working directory."""
    return _DOCUMENTS / name
