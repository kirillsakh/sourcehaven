import pytest

from evals.normalize import normalize, word_coverage


def test_ligatures_case_and_whitespace() -> None:
    assert normalize("The  \ufb01rst\nRule") == "the first rule"


def test_line_end_hyphen_joins_and_other_hyphens_vanish() -> None:
    assert normalize("represen-\ntation") == normalize("representation")
    assert normalize("well-\nknown") == normalize("well-known") == "wellknown"


def test_soft_hyphen_dashes_and_quotes() -> None:
    assert normalize("co\u00adoperate") == "cooperate"
    assert normalize("\u201cA\u201d \u2013 \u2018b\u2019") == normalize("\"A\" - 'b'")


def test_soft_hyphen_at_a_line_end_joins_the_word() -> None:
    assert normalize("inter\u00ad\nnational") == normalize("international") == "international"
    assert normalize("inter\u00ad national") == "international"


def test_word_coverage_counts_words_as_a_multiset() -> None:
    assert word_coverage("the cat and the dog", "The cat \u2026 the dog") == 0.8
    assert word_coverage("24 months", "warranty of 24 months") == 1.0


def test_word_coverage_rejects_a_span_without_words() -> None:
    with pytest.raises(ValueError):
        word_coverage(" \u2026 ", "anything")


def test_dashes_join_words_with_or_without_surrounding_spaces() -> None:
    assert normalize("cats \u2014 dogs") == normalize("cats\u2014dogs") == "catsdogs"
    assert normalize("10 \u2212 5") == normalize("10-5")
    assert normalize("well-  \r\n  known") == "wellknown"


def test_word_coverage_partial_and_empty_quote() -> None:
    assert word_coverage("alpha beta", "alpha gamma") == 0.5
    assert word_coverage("alpha", "") == 0.0
