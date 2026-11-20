import asyncio

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage

from sourcehaven.config import Settings
from sourcehaven.generation.chat import build_chat_model
from sourcehaven.generation.fake import ScriptedChatModel

PASSAGE_PROMPT: str = (
    '<passage label="S1" document="a.pdf" pages="1">\n'
    "Paris is the capital of France and sits on the Seine river in the north of the country.\n"
    "</passage>\n\n"
    '<passage label="S2" document="b.pdf" pages="3">\nOther text.\n</passage>\n\n'
    "Question: Capital?"
)


async def collect(model: BaseChatModel, messages: list[BaseMessage]) -> list[AIMessageChunk]:
    return [chunk async for chunk in model.astream(messages)]


async def test_scripted_model_streams_chunks_and_records_calls() -> None:
    model: ScriptedChatModel = ScriptedChatModel(script=["Hello ", "world [S1]"])
    chunks: list[str] = [str(c.content) async for c in model.astream([HumanMessage("hi")])]
    assert chunks == ["Hello ", "world [S1]"] and len(model.calls) == 1


async def test_calls_record_the_message_lists() -> None:
    model: ScriptedChatModel = ScriptedChatModel(script=["a"])
    message: HumanMessage = HumanMessage("hi")
    await collect(model, [message])
    assert model.calls == [[message]]


async def test_calls_are_not_kept_when_recording_is_off() -> None:
    model: ScriptedChatModel = ScriptedChatModel(script=["a"], record_calls=False)
    await collect(model, [HumanMessage("a visitor's question")])
    assert model.calls == []


def test_fake_provider_does_not_keep_prompts() -> None:
    model: BaseChatModel = build_chat_model(
        Settings(embedding_provider="hash", generation_provider="fake")
    )
    assert isinstance(model, ScriptedChatModel) and model.record_calls is False


async def test_default_answer_quotes_first_80_characters_of_s1_and_cites_it() -> None:
    model: ScriptedChatModel = ScriptedChatModel()
    chunks: list[AIMessageChunk] = await collect(model, [HumanMessage(PASSAGE_PROMPT)])
    text: str = "".join(str(c.content) for c in chunks)
    passage: str = (
        "Paris is the capital of France and sits on the Seine river in the north of the country."
    )
    assert text == f"Based on the sources: {passage[:80]} [S1]"
    assert len(chunks) > 3
    assert all(str(c.content).strip() for c in chunks)


async def test_default_answer_without_passages_says_nothing_was_found() -> None:
    model: ScriptedChatModel = ScriptedChatModel()
    chunks: list[AIMessageChunk] = await collect(model, [HumanMessage("Question: hi")])
    assert "".join(str(c.content) for c in chunks) == (
        "I could not find this in the selected documents."
    )


async def test_usage_metadata_is_on_the_final_chunk_only() -> None:
    model: ScriptedChatModel = ScriptedChatModel(script=["one ", "two ", "three"])
    chunks: list[AIMessageChunk] = await collect(model, [HumanMessage("a b")])
    assert [c.usage_metadata is not None for c in chunks] == [False, False, True]
    assert chunks[-1].usage_metadata == {
        "input_tokens": 2,
        "output_tokens": 3,
        "total_tokens": 5,
    }


async def test_fail_after_raises_once_that_many_chunks_were_streamed() -> None:
    model: ScriptedChatModel = ScriptedChatModel(script=["a ", "b ", "c"], fail_after=2)
    received: list[str] = []
    with pytest.raises(RuntimeError):
        async for chunk in model.astream([HumanMessage("hi")]):
            received.append(str(chunk.content))
    assert received == ["a ", "b "]


async def test_gate_blocks_after_the_first_chunk_until_set() -> None:
    gate: asyncio.Event = asyncio.Event()
    model: ScriptedChatModel = ScriptedChatModel(script=["a ", "b"], gate=gate)
    stream = model.astream([HumanMessage("hi")])
    first: AIMessageChunk = await anext(stream)
    assert first.content == "a "
    pending: asyncio.Task[AIMessageChunk] = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0.01)
    assert not pending.done()
    gate.set()
    assert (await pending).content == "b"


async def test_ainvoke_returns_the_whole_scripted_answer() -> None:
    model: ScriptedChatModel = ScriptedChatModel(script=["Hello ", "world"])
    result: AIMessage = await model.ainvoke([HumanMessage("hi")])
    assert result.content == "Hello world"


def test_invoke_returns_the_whole_scripted_answer() -> None:
    model: ScriptedChatModel = ScriptedChatModel(script=["Hello ", "world"])
    assert model.invoke([HumanMessage("hi")]).content == "Hello world"


def test_fake_provider_builds_the_scripted_model() -> None:
    assert isinstance(
        build_chat_model(Settings(embedding_provider="hash", generation_provider="fake")),
        ScriptedChatModel,
    )
