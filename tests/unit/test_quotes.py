from sourcehaven.qa.quotes import Sentence, citing_sentences, split_sentences


def test_sentences_slice_the_passage_exactly() -> None:
    text: str = 'Senior Engineer.\n• Led the migration! Wait… then "yes." Then (done.) end'
    sentences: list[Sentence] = split_sentences(text)
    assert [s.text for s in sentences] == [
        "Senior Engineer.",
        "• Led the migration!",
        "Wait…",
        'then "yes."',
        "Then (done.)",
        "end",
    ]
    assert all(text[s.start : s.end] == s.text for s in sentences)


def test_lines_without_full_stops_are_sentences_and_blank_pieces_are_dropped() -> None:
    assert [s.text for s in split_sentences("Skills\n\n  •  \nPython, FastAPI\n")] == [
        "Skills",
        "Python, FastAPI",
    ]


def test_label_after_the_full_stop_or_on_its_own_line_cites_the_preceding_sentence() -> None:
    answer: str = "Support answers in 3 days. [S1]\nThe warranty is 24 months.\n[S2]"
    assert citing_sentences(answer) == {
        "S1": ["Support answers in 3 days."],
        "S2": ["The warranty is 24 months."],
    }


def test_markdown_and_labels_are_removed_and_shared_sentences_count_for_each_label() -> None:
    answer: str = "## Fit\n- **Python:** 7 years of `FastAPI` work [S2][S3].\n- Mentoring [S2]."
    assert citing_sentences(answer) == {
        "S2": ["Python: 7 years of FastAPI work.", "Mentoring."],
        "S3": ["Python: 7 years of FastAPI work."],
    }


def test_label_without_words_has_no_citing_sentence() -> None:
    assert citing_sentences("Intro.\n[S1][S2]") == {"S1": ["Intro."], "S2": ["Intro."]}
    assert citing_sentences("[S1]") == {"S1": []}
