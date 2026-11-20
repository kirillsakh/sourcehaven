from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from sourcehaven.config import Settings
from sourcehaven.generation.fake import ScriptedChatModel

OPENAI_REQUEST_TIMEOUT_SECONDS: int = 120


def build_chat_model(settings: Settings) -> BaseChatModel:
    """Build the chat model selected by `settings.generation_provider`.

    Construction never contacts the network.

    The `ChatOpenAI` parameter names were checked against langchain-openai 1.8.3 (the installed
    `langchain_openai/chat_models/base.py`): `api_key` and `timeout` are aliases of the
    `openai_api_key` and `request_timeout` fields, `stream_usage=True` makes streamed responses
    carry `usage_metadata` on the last chunk, and the output limit is the `max_tokens` field
    whose constructor alias is `max_completion_tokens` (the name the request payload sends; the
    type checker only accepts the alias). A `None` temperature is left out of the request
    payload, so models that only accept their default temperature still work. Retries are disabled
    (`max_retries=0`) because the caller retries itself, and only before the first token. An unset
    `reasoning_effort` is left out of the request, like the temperature.

    Raises:
        ValueError: If the OpenAI provider is selected without an API key.
    """
    if settings.generation_provider == "fake":
        return ScriptedChatModel(record_calls=False)
    if settings.openai_api_key is None:
        raise ValueError("openai_api_key is required when generation_provider is openai")
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=settings.generation_temperature,
        max_completion_tokens=settings.max_output_tokens,
        reasoning_effort=settings.openai_reasoning_effort,
        stream_usage=True,
        timeout=OPENAI_REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )
