import pytest

from sourcehaven.api.routes.documents import sanitize_display_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("/etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\me\\Report.pdf", "Report.pdf"),
        ("../../x.pdf", "x.pdf"),
        ("a\x00b\x1f\n.pdf", "ab.pdf"),
        ("cafe\u0301.pdf", "caf\u00e9.pdf"),
        ("", "document.pdf"),
        ("dir/", "document.pdf"),
        (None, "document.pdf"),
    ],
)
def test_sanitize_display_name(raw: str | None, expected: str) -> None:
    assert sanitize_display_name(raw) == expected


def test_display_name_is_truncated_to_200_characters() -> None:
    assert len(sanitize_display_name("x" * 500 + ".pdf")) == 200
