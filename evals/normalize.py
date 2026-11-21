import re
import unicodedata
from collections import Counter

_SOFT_HYPHEN: str = "\u00ad"
_HYPHEN_LIKE: re.Pattern[str] = re.compile(r"[\u2010-\u2015\u2212]")
# A hyphen at the end of a printed line splits a word; it is removed together with the break.
_LINE_END_HYPHEN: re.Pattern[str] = re.compile(r"-\s*\n\s*")
_SINGLE_QUOTES: re.Pattern[str] = re.compile(r"[\u2018\u2019\u201a\u201b]")
_DOUBLE_QUOTES: re.Pattern[str] = re.compile(r"[\u201c\u201d\u201e\u201f]")
_WHITESPACE: re.Pattern[str] = re.compile(r"\s+")
_WORD: re.Pattern[str] = re.compile(r"\w+")


def normalize(text: str) -> str:
    """Fold text so that PDF extraction and typography differences compare equal.

    Applies NFKC, drops soft hyphens, joins words split at a line end, drops every other hyphen
    (so "well-known" and a "well-" / "known" line break agree), straightens quotes, collapses
    whitespace and casefolds.
    """
    folded: str = unicodedata.normalize("NFKC", text).replace(_SOFT_HYPHEN, "")
    folded = _HYPHEN_LIKE.sub("-", folded)
    folded = _LINE_END_HYPHEN.sub("", folded).replace("-", "")
    folded = _SINGLE_QUOTES.sub("'", folded)
    folded = _DOUBLE_QUOTES.sub('"', folded)
    return _WHITESPACE.sub(" ", folded).casefold().strip()


def word_coverage(span: str, quote: str) -> float:
    """Share of the span's words that the quote also contains, counted as a multiset.

    Args:
        span: Reference text whose words must be found.
        quote: Text searched for the span's words.

    Returns:
        Matched span words divided by all span words, between 0 and 1.

    Raises:
        ValueError: If the span contains no words.
    """
    span_words: Counter[str] = Counter(_WORD.findall(normalize(span)))
    total: int = span_words.total()
    if total == 0:
        raise ValueError("The span contains no words")
    quote_words: Counter[str] = Counter(_WORD.findall(normalize(quote)))
    return (span_words & quote_words).total() / total
