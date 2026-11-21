import hashlib
import json
from pathlib import Path

import pytest

from evals.corpus import CorpusDocument, Manifest
from evals.questions import (
    MAX_SPAN_CHARACTERS,
    GoldSpan,
    Question,
    QuestionFileError,
    file_sha256,
    load_questions,
)
from sourcehaven.domain.models import PageSpan


def _document(
    document_id: str,
    *,
    page_count: int = 50,
    page_range: PageSpan | None = None,
    selected_by_default: bool = True,
) -> CorpusDocument:
    return CorpusDocument(
        id=document_id,
        title=f"Title of {document_id}",
        author="An Author",
        url=f"https://example.org/{document_id}.pdf",
        sha256="0" * 64,
        size_bytes=1,
        page_count=page_count,
        licence="CC BY 4.0",
        licence_url="https://creativecommons.org/licenses/by/4.0/",
        layout="single-column",
        page_range=page_range,
        selected_by_default=selected_by_default,
    )


MANIFEST: Manifest = Manifest(
    version=1,
    documents=(
        _document("contract", page_range=PageSpan(start=10, end=20)),
        _document("report"),
        _document("report-2024", selected_by_default=False),
    ),
)
GOLD: dict[str, object] = {"document": "contract", "page": 12, "text": "The term is five years."}
ANSWERABLE: dict[str, object] = {
    "id": "q-1",
    "kind": "answerable",
    "text": "How long is the term?",
    "documents": [],
    "reference_answer": "The term is five years.",
    "gold": [GOLD],
}
UNANSWERABLE: dict[str, object] = {
    "id": "q-2",
    "kind": "unanswerable",
    "text": "What is the notice period?",
    "documents": [],
    "gold": [],
}
CONFLICT: dict[str, object] = {
    "id": "q-3",
    "kind": "conflict",
    "text": "How much energy was used?",
    "documents": ["report", "report-2024"],
    "reference_answer": "The editions disagree.",
    "gold": [
        {"document": "report", "page": 3, "text": "Use was 100 TWh."},
        {"document": "report-2024", "page": 4, "text": "Use was 90 TWh."},
    ],
}


def _toml_value(value: object) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    return json.dumps(value)


def write_questions(tmp_path: Path, *questions: dict[str, object]) -> Path:
    blocks: list[str] = []
    for question in questions:
        lines: list[str] = ["[[question]]"]
        for key, value in question.items():
            if key != "gold" and value is not None:
                lines.append(f"{key} = {_toml_value(value)}")
        gold: object = question.get("gold", [])
        assert isinstance(gold, list)
        for span in gold:
            lines.append("[[question.gold]]")
            lines.extend(f"{key} = {_toml_value(value)}" for key, value in span.items())
        blocks.append("\n".join(lines))
    path: Path = tmp_path / "questions.toml"
    path.write_text("# header\n\n" + "\n\n".join(blocks) + "\n", encoding="utf-8")
    return path


def test_loads_each_kind(tmp_path: Path) -> None:
    path: Path = write_questions(tmp_path, ANSWERABLE, UNANSWERABLE, CONFLICT)

    answerable, unanswerable, conflict = load_questions(path, MANIFEST)

    assert answerable == Question(
        id="q-1",
        kind="answerable",
        text="How long is the term?",
        documents=("contract", "report"),
        reference_answer="The term is five years.",
        gold=(GoldSpan(document="contract", page=12, text="The term is five years."),),
    )
    assert unanswerable.kind == "unanswerable"
    assert unanswerable.reference_answer is None
    assert unanswerable.gold == ()
    assert conflict.documents == ("report", "report-2024")
    assert [span.document for span in conflict.gold] == ["report", "report-2024"]


def test_empty_selection_means_documents_selected_by_default(tmp_path: Path) -> None:
    (question,) = load_questions(write_questions(tmp_path, ANSWERABLE), MANIFEST)

    assert question.documents == ("contract", "report")  # report-2024 is not selected by default


def test_omitted_documents_means_default_selection(tmp_path: Path) -> None:
    case: dict[str, object] = {k: v for k, v in UNANSWERABLE.items() if k != "documents"}

    (question,) = load_questions(write_questions(tmp_path, case), MANIFEST)

    assert question.documents == ("contract", "report")


def test_listed_documents_keep_their_order(tmp_path: Path) -> None:
    case: dict[str, object] = UNANSWERABLE | {"documents": ["report-2024", "contract"]}

    (question,) = load_questions(write_questions(tmp_path, case), MANIFEST)

    assert question.documents == ("report-2024", "contract")


def test_accepts_the_edges_of_the_page_range_and_the_span_limit(tmp_path: Path) -> None:
    gold: list[object] = [
        GOLD | {"page": 10},
        GOLD | {"page": 20, "text": "x" * MAX_SPAN_CHARACTERS},
        {"document": "report", "page": 50, "text": "Last page."},
    ]

    (question,) = load_questions(write_questions(tmp_path, ANSWERABLE | {"gold": gold}), MANIFEST)

    assert [span.page for span in question.gold] == [10, 20, 50]


def test_file_without_questions_is_valid(tmp_path: Path) -> None:
    path: Path = tmp_path / "questions.toml"
    path.write_text("# No questions yet.\n", encoding="utf-8")

    assert load_questions(path, MANIFEST) == ()


@pytest.mark.parametrize(
    ("case", "message"),
    [
        (ANSWERABLE | {"gold": []}, "q-1"),
        (ANSWERABLE | {"reference_answer": None}, "q-1"),
        (ANSWERABLE | {"reference_answer": "  "}, "q-1"),
        (UNANSWERABLE | {"gold": [GOLD]}, "q-2"),
        (UNANSWERABLE | {"reference_answer": "Unknown."}, "q-2"),
        (CONFLICT | {"documents": []}, "q-3"),
        (CONFLICT | {"gold": [GOLD]}, "q-3"),
        (CONFLICT | {"reference_answer": None}, "q-3"),
        (ANSWERABLE | {"documents": ["report"]}, "q-1"),
        (ANSWERABLE | {"documents": ["nope"]}, "q-1"),
        (ANSWERABLE | {"documents": ["report", "report"]}, "q-1"),
        (ANSWERABLE | {"gold": [GOLD | {"document": "nope"}]}, "q-1"),
        (ANSWERABLE | {"gold": [GOLD | {"page": 999}]}, "q-1"),
        (ANSWERABLE | {"gold": [GOLD | {"page": 9}]}, "q-1"),
        (ANSWERABLE | {"gold": [GOLD | {"page": 21}]}, "q-1"),
        (ANSWERABLE | {"gold": [GOLD | {"page": 0}]}, "q-1"),
        (ANSWERABLE | {"gold": [GOLD | {"page": "12"}]}, "q-1"),
        (ANSWERABLE | {"gold": [GOLD | {"text": "x" * (MAX_SPAN_CHARACTERS + 1)}]}, "q-1"),
        (ANSWERABLE | {"gold": [GOLD | {"text": ""}]}, "q-1"),
        (ANSWERABLE | {"gold": [GOLD | {"text": "   "}]}, "q-1"),
        (ANSWERABLE | {"gold": [GOLD | {"pages": 3}]}, "q-1"),
        (ANSWERABLE | {"kind": "other"}, "q-1"),
        (ANSWERABLE | {"text": " "}, "q-1"),
        (ANSWERABLE | {"documents": "report"}, "q-1"),
        (ANSWERABLE | {"referance_answer": "typo"}, "q-1"),
        (ANSWERABLE | {"id": "Bad Id"}, "Bad Id"),
    ],
)
def test_rejects_invalid_questions(tmp_path: Path, case: dict[str, object], message: str) -> None:
    with pytest.raises(QuestionFileError, match=message):
        load_questions(write_questions(tmp_path, case), MANIFEST)


def test_conflict_must_list_its_documents_even_when_gold_is_selected_by_default(
    tmp_path: Path,
) -> None:
    case: dict[str, object] = CONFLICT | {
        "documents": [],
        "gold": [GOLD, {"document": "report", "page": 3, "text": "Use was 100 TWh."}],
    }

    with pytest.raises(QuestionFileError, match="q-3: a conflict question must list"):
        load_questions(write_questions(tmp_path, case), MANIFEST)


def test_rejects_duplicate_ids(tmp_path: Path) -> None:
    with pytest.raises(QuestionFileError, match="q-1: duplicate id"):
        load_questions(write_questions(tmp_path, ANSWERABLE, ANSWERABLE), MANIFEST)


def test_rejects_an_empty_default_selection(tmp_path: Path) -> None:
    manifest: Manifest = Manifest(
        version=1, documents=(_document("report", selected_by_default=False),)
    )

    with pytest.raises(QuestionFileError, match="q-2"):
        load_questions(write_questions(tmp_path, UNANSWERABLE), manifest)


def test_rejects_unknown_top_level_keys(tmp_path: Path) -> None:
    path: Path = tmp_path / "questions.toml"
    path.write_text('[[questions]]\nid = "q-1"\n', encoding="utf-8")

    with pytest.raises(QuestionFileError, match="questions"):
        load_questions(path, MANIFEST)


def test_rejects_unreadable_files(tmp_path: Path) -> None:
    broken: Path = tmp_path / "broken.toml"
    broken.write_text("[[question", encoding="utf-8")

    with pytest.raises(QuestionFileError, match=r"broken\.toml"):
        load_questions(broken, MANIFEST)
    with pytest.raises(QuestionFileError, match=r"missing\.toml"):
        load_questions(tmp_path / "missing.toml", MANIFEST)


def test_reports_every_problem_at_once(tmp_path: Path) -> None:
    path: Path = write_questions(
        tmp_path, ANSWERABLE | {"gold": []}, UNANSWERABLE | {"gold": [GOLD]}, CONFLICT
    )

    with pytest.raises(QuestionFileError) as error:
        load_questions(path, MANIFEST)

    message: str = str(error.value)
    assert "q-1" in message
    assert "q-2" in message
    assert "q-3" not in message


def test_file_sha256_hashes_the_bytes(tmp_path: Path) -> None:
    path: Path = tmp_path / "questions.toml"
    path.write_bytes(b"abc")

    assert file_sha256(path) == hashlib.sha256(b"abc").hexdigest()
