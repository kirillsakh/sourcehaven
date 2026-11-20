import re
from collections.abc import Sequence
from dataclasses import dataclass

from sourcehaven.domain.models import Citation
from sourcehaven.generation.prompts import LabelledEvidence

# Labels are matched exactly as written. `[s1]`, `[S 1]` and `[S1,S2]` are not citations, and
# `[S01]` is the label "S01", which differs from the supplied "S1" and so is reported as invalid.
_CITATION: re.Pattern[str] = re.compile(r"\[S([0-9]+)\]")
_SUPPLIED_LABEL: re.Pattern[str] = re.compile(r"S([0-9]+)")
QUOTE_SNAPSHOT_CHARACTERS: int = 300


def quote_snapshot(passage_text: str) -> str:
    """The excerpt of a passage stored and shown with its citation: its first 300 characters."""
    return passage_text[:QUOTE_SNAPSHOT_CHARACTERS]


@dataclass(frozen=True)
class CitationResult:
    """The outcome of checking an answer's citations against the supplied passages.

    Attributes:
        sources: Every supplied passage, ordered by label number, marked cited or not. `cited`
            means only that the label appears in the text, not that the passage supports the
            claim.
        invalid_labels: Labels cited in the text but never supplied, without duplicates, in
            order of first appearance.
    """

    sources: list[Citation]
    invalid_labels: list[str]


def _label_number(label: str) -> int:
    match: re.Match[str] | None = _SUPPLIED_LABEL.fullmatch(label)
    if match is None:
        raise ValueError(f"Supplied label {label!r} is not of the form S<number>")
    return int(match.group(1))


def _number_of(item: LabelledEvidence) -> int:
    return _label_number(item.label)


def validate_citations(text: str, supplied: Sequence[LabelledEvidence]) -> CitationResult:
    """Check which supplied passages an answer cites and which cited labels are unknown.

    Args:
        text: The generated answer.
        supplied: The passages the model was given, each with a label of the form `S<number>`.

    Returns:
        The supplied passages ordered numerically by label (so `S2` precedes `S10`) with their
        cited flag, and the labels that appear in `text` without a supplied passage.

    Raises:
        ValueError: If a supplied label is not `S` followed by ASCII digits, or two supplied
            passages share a label.
    """
    found: list[str] = [f"S{digits}" for digits in _CITATION.findall(text)]
    ordered: list[LabelledEvidence] = sorted(supplied, key=_number_of)
    known: set[str] = {item.label for item in ordered}
    if len(known) != len(ordered):
        raise ValueError("Duplicate supplied labels")
    cited: set[str] = set(found)
    sources: list[Citation] = [
        Citation(label=item.label, evidence=item.evidence, cited=item.label in cited)
        for item in ordered
    ]
    invalid_labels: list[str] = [label for label in dict.fromkeys(found) if label not in known]
    return CitationResult(sources=sources, invalid_labels=invalid_labels)
