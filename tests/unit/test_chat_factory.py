import pytest
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from sourcehaven.config import Settings
from sourcehaven.generation.chat import build_chat_model


def test_openai_provider_builds_a_streaming_usage_model_without_retries() -> None:
    settings: Settings = Settings(
        embedding_provider="hash",
        generation_provider="openai",
        openai_api_key=SecretStr("sk-test"),
        openai_model="gpt-test",
        generation_temperature=0.3,
        max_output_tokens=123,
    )
    model: BaseChatModel = build_chat_model(settings)
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "gpt-test"
    assert model.temperature == 0.3
    assert model.max_tokens == 123
    assert model.stream_usage is True
    assert model.request_timeout == 120
    assert model.max_retries == 0


def test_unset_temperature_is_left_out_of_the_request() -> None:
    settings: Settings = Settings(
        embedding_provider="hash",
        generation_provider="openai",
        openai_api_key=SecretStr("sk-test"),
    )
    assert settings.generation_temperature is None
    model: BaseChatModel = build_chat_model(settings)
    assert isinstance(model, ChatOpenAI)
    assert "temperature" not in model._default_params


def test_openai_provider_requires_an_api_key() -> None:
    with pytest.raises(ValueError, match="openai_api_key"):
        build_chat_model(
            Settings(embedding_provider="hash", generation_provider="openai", openai_api_key=None)
        )
