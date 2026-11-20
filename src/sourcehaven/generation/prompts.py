import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from html import escape
from importlib.resources import files

import tiktoken
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from sourcehaven.config import Settings
from sourcehaven.domain.models import Evidence, PageSpan

# Matches an opening or closing passage tag in any case and with inner whitespace, so passage
# text cannot close its own block or open a fake one.
_PASSAGE_TAG: re.Pattern[str] = re.compile(r"<(\s*/?\s*passage)", flags=re.IGNORECASE)


@dataclass(frozen=True)
class PromptBudget:
    """Token budgets for the parts of an answer prompt.

    Only `evidence` is enforced when assembling messages; the question length is limited at the
    API boundary and the system and history parts are budgeted by their own producers.
    """

    system: int = 800
    history: int = 1500
    evidence: int = 3600
    question: int = 600


@dataclass(frozen=True)
class LabelledEvidence:
    """A passage together with the `S#` label the model sees for it."""

    label: str
    evidence: Evidence


def load_prompt(name: str) -> str:
    """Read the packaged prompt template `sourcehaven/prompts/<name>.txt`."""
    return files("sourcehaven.prompts").joinpath(f"{name}.txt").read_text("utf-8")


def prompt_encoding_name(settings: Settings) -> str:
    """Name the tiktoken encoding of the configured OpenAI model.

    It is the model's own encoding; when tiktoken does not know the model (as with
    `gpt-6-luna`), it is `o200k_base`, the encoding of current OpenAI chat models.
    """
    try:
        return tiktoken.encoding_name_for_model(settings.openai_model)
    except KeyError:
        return "o200k_base"


def make_token_counter(settings: Settings) -> Callable[[str], int]:
    """Return a function that counts tokens the way the configured OpenAI model does.

    The encoding is `tiktoken.encoding_for_model(settings.openai_model)`; when tiktoken does not
    know the model (as with `gpt-6-luna`), it is `o200k_base` (see `prompt_encoding_name`).
    tiktoken bundles no encoding data: the first use downloads and caches it
    (`TIKTOKEN_CACHE_DIR` relocates the cache), so the encoding loads lazily on the first count
    and tests must inject their own counter.
    """
    model: str = settings.openai_model

    @cache
    def encoding() -> tiktoken.Encoding:
        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            return tiktoken.get_encoding("o200k_base")

    def count_tokens(text: str) -> int:
        return len(encoding().encode(text, disallowed_special=()))

    return count_tokens


def estimate_tokens(text: str) -> int:
    """Estimate tokens conservatively, as one per three characters rounded up.

    Used when the model's tokenizer is unavailable (spec section 7.4); real encodings average
    more characters per token, so the estimate errs towards overcounting.
    """
    return math.ceil(len(text) / 3)


def _pages(span: PageSpan) -> str:
    return str(span.start) if span.start == span.end else f"{span.start}-{span.end}"


def _passage_block(label: str, evidence: Evidence) -> str:
    # Passage text and the document name are untrusted: neutralise anything that could end the
    # block or add attributes while keeping the text readable and quotable.
    text: str = _PASSAGE_TAG.sub(r"&lt;\1", evidence.text)
    document: str = escape(evidence.document_name, quote=True)
    pages: str = _pages(evidence.span)
    return f'<passage label="{label}" document="{document}" pages="{pages}">\n{text}\n</passage>'


def assemble_answer_messages(
    question: str,
    evidence: Sequence[Evidence],
    *,
    budget: PromptBudget,
    count_tokens: Callable[[str], int],
) -> tuple[list[BaseMessage], list[LabelledEvidence]]:
    """Build the system and human messages for an answer, labelling passages `S1…Sn`.

    Passages are taken in the given (similarity) order and added while the evidence budget
    holds; the first passage that would exceed it, and every later one, is left out so labels
    stay contiguous.

    Args:
        question: The visitor's question, already validated and trimmed.
        evidence: Candidate passages, best first.
        budget: Token budgets; only `evidence` limits what is included here.
        count_tokens: Token counter applied to each rendered passage block.

    Returns:
        The messages and the passages that were included with their labels.
    """
    blocks: list[str] = []
    labelled: list[LabelledEvidence] = []
    used: int = 0
    for candidate in evidence:
        label: str = f"S{len(labelled) + 1}"
        block: str = _passage_block(label, candidate)
        cost: int = count_tokens(block)
        if used + cost > budget.evidence:
            break
        used += cost
        blocks.append(block)
        labelled.append(LabelledEvidence(label=label, evidence=candidate))
    passages: str = "\n\n".join(blocks)
    human: str = f"{passages}\n\nQuestion: {question}" if blocks else f"Question: {question}"
    messages: list[BaseMessage] = [
        SystemMessage(load_prompt("answer_system")),
        HumanMessage(human),
    ]
    return messages, labelled
