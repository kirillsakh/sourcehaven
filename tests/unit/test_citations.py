from dataclasses import replace
from uuid import uuid4

import pytest

from sourcehaven.domain.models import Evidence, PageSpan
from sourcehaven.generation.prompts import LabelledEvidence
from sourcehaven.qa.citations import CitationResult, validate_citations

ARABIC_INDIC_ONE: str = chr(0x0661)


def labelled(label: str) -> LabelledEvidence:
    return LabelledEvidence(
        label=label,
        evidence=Evidence(
            chunk_id=uuid4(),
            document_id=uuid4(),
            version_id=uuid4(),
            document_name="doc.pdf",
            text=f"text of {label}",
            span=PageSpan(start=1, end=1),
            similarity=0.5,
        ),
    )


def test_marks_cited_uncited_and_invalid() -> None:
    supplied: list[LabelledEvidence] = [labelled("S1"), labelled("S2"), labelled("S3")]
    result: CitationResult = validate_citations("A [S1] and B [S3][S7] again [S1]", supplied)
    assert [(c.label, c.cited) for c in result.sources] == [
        ("S1", True),
        ("S2", False),
        ("S3", True),
    ]
    assert result.invalid_labels == ["S7"]


def test_no_citations() -> None:
    result: CitationResult = validate_citations("No markers here.", [labelled("S1")])
    assert [c.cited for c in result.sources] == [False] and result.invalid_labels == []


def test_sources_keep_the_supplied_evidence() -> None:
    supplied: list[LabelledEvidence] = [labelled("S1")]
    result: CitationResult = validate_citations("[S1]", supplied)
    assert result.sources[0].evidence is supplied[0].evidence


def test_sources_are_ordered_by_label_number_not_lexically() -> None:
    supplied: list[LabelledEvidence] = [labelled(f"S{n}") for n in (10, 2, 11, 1, 3)]
    result: CitationResult = validate_citations("[S10] [S2]", supplied)
    assert [c.label for c in result.sources] == ["S1", "S2", "S3", "S10", "S11"]
    assert [c.cited for c in result.sources] == [False, True, False, True, False]


def test_invalid_labels_are_deduplicated_in_order_of_first_appearance() -> None:
    result: CitationResult = validate_citations("[S9] [S4] [S9] [S1] [S4] [S12]", [labelled("S1")])
    assert result.invalid_labels == ["S9", "S4", "S12"]
    assert [c.cited for c in result.sources] == [True]


def test_no_supplied_evidence_makes_every_label_invalid() -> None:
    result: CitationResult = validate_citations("Claim [S1].", [])
    assert result.sources == []
    assert result.invalid_labels == ["S1"]


def test_only_exact_uppercase_bracketed_labels_count() -> None:
    text: str = "[s1] [S 1] S1 (S1) [S1 ] [S-1] [S1,S2]"
    result: CitationResult = validate_citations(text, [labelled("S1"), labelled("S2")])
    assert [c.cited for c in result.sources] == [False, False]
    assert result.invalid_labels == []


def test_zero_padded_label_is_an_invalid_label_not_a_citation_of_the_unpadded_one() -> None:
    result: CitationResult = validate_citations("See [S01].", [labelled("S1")])
    assert [c.cited for c in result.sources] == [False]
    assert result.invalid_labels == ["S01"]


def test_non_ascii_digits_are_not_a_citation() -> None:
    result: CitationResult = validate_citations(f"[S{ARABIC_INDIC_ONE}]", [labelled("S1")])
    assert [c.cited for c in result.sources] == [False]
    assert result.invalid_labels == []


@pytest.mark.parametrize(
    "label", ["1", "S 1", "S-1", "S+1", "S1_0", "Sx", "S", "", "s1", f"S{ARABIC_INDIC_ONE}"]
)
def test_supplied_label_must_be_s_followed_by_ascii_digits(label: str) -> None:
    with pytest.raises(ValueError, match="label"):
        validate_citations("text", [labelled(label)])


def test_duplicate_supplied_labels_are_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        validate_citations("[S1]", [labelled("S1"), labelled("S1")])


def test_sources_quote_the_passage_start() -> None:
    item: LabelledEvidence = labelled("S1")
    long: LabelledEvidence = replace(item, evidence=replace(item.evidence, text="x" * 301))
    result: CitationResult = validate_citations("[S1]", [long])
    assert result.sources[0].quote == "x" * 300
