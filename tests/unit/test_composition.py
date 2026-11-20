from collections.abc import Callable

import pytest

from sourcehaven.composition import (
    select_prompt_token_counter,
    select_token_counter,
    select_verifier,
)
from sourcehaven.config import Settings
from sourcehaven.embeddings.hashing import WhitespaceTokenCounter
from sourcehaven.embeddings.protocol import TokenCounter
from sourcehaven.generation.prompts import estimate_tokens
from sourcehaven.sessions.verification import AllowAllVerifier, HumanVerifier


def test_hash_provider_counts_whitespace_tokens() -> None:
    settings: Settings = Settings(embedding_provider="hash")
    counter: TokenCounter = select_token_counter(settings)
    assert isinstance(counter, WhitespaceTokenCounter)


def test_tei_provider_requires_a_tokenizer_file() -> None:
    settings: Settings = Settings(embedding_provider="tei", embedding_model_revision="rev-1")
    with pytest.raises(ValueError, match="tokenizer_file"):
        select_token_counter(settings)


def test_disabled_verification_allows_everyone() -> None:
    verifier: HumanVerifier = select_verifier(
        Settings(embedding_provider="hash", human_verification="disabled")
    )
    assert isinstance(verifier, AllowAllVerifier)


def test_turnstile_verification_is_not_available_yet() -> None:
    with pytest.raises(NotImplementedError, match="turnstile"):
        select_verifier(Settings(embedding_provider="hash", human_verification="turnstile"))


def test_character_estimate_rounds_up_per_three_characters() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abc") == 1
    assert estimate_tokens("abcd") == 2


async def test_fake_provider_counts_prompt_tokens_by_estimate() -> None:
    def never_loaded(settings: Settings) -> Callable[[str], int]:
        raise AssertionError("the fake provider must not load a tokenizer")

    count: Callable[[str], int] = await select_prompt_token_counter(
        Settings(embedding_provider="hash", generation_provider="fake"), make_counter=never_loaded
    )
    assert count("abcdefg") == 3


async def test_openai_provider_uses_the_warmed_model_counter() -> None:
    warmed: list[str] = []

    def counter(text: str) -> int:
        warmed.append(text)
        return 42

    def make_counter(settings: Settings) -> Callable[[str], int]:
        return counter

    count: Callable[[str], int] = await select_prompt_token_counter(
        Settings(embedding_provider="hash", generation_provider="openai"), make_counter=make_counter
    )
    assert warmed  # loaded once while the container is built, off the event loop
    assert count("anything") == 42


async def test_openai_provider_falls_back_when_the_encoding_cannot_load(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def unavailable(text: str) -> int:
        raise OSError("network unreachable while downloading")

    def make_counter(settings: Settings) -> Callable[[str], int]:
        return unavailable

    count: Callable[[str], int] = await select_prompt_token_counter(
        Settings(
            embedding_provider="hash", generation_provider="openai", openai_model="gpt-6-luna"
        ),
        make_counter=make_counter,
    )
    assert count("abcdef") == 2
    assert "o200k_base" in caplog.text
    assert "network unreachable" not in caplog.text
