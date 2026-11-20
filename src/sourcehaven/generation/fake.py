import asyncio
import re
from collections.abc import AsyncIterator, Iterator, Sequence

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

NO_EVIDENCE_ANSWER: str = "I could not find this in the selected documents."
QUOTE_CHARACTERS: int = 80
_S1_PASSAGE: re.Pattern[str] = re.compile(
    r'<passage label="S1"[^>]*>\n(.*?)\n</passage>', flags=re.DOTALL
)
_WORD_WITH_TRAILING_SPACE: re.Pattern[str] = re.compile(r"\S+\s*")


def _text_of(message: BaseMessage) -> str:
    return message.content if isinstance(message.content, str) else str(message.content)


def _split_into_chunks(text: str) -> list[str]:
    """Split text into whitespace-delimited chunks that concatenate back to the original."""
    return _WORD_WITH_TRAILING_SPACE.findall(text)


class ScriptedChatModel(BaseChatModel):
    """A deterministic offline chat model that streams a scripted or derived answer.

    Without a `script` it answers from the passages in the last message that holds an `S1`
    passage block (the format produced by `assemble_answer_messages`), or says nothing was
    found. Its token usage counts whitespace-delimited words.

    Attributes:
        script: Chunks to stream exactly as given instead of the derived answer.
        gate: When set, streaming pauses after the first chunk until the event is set.
        fail_after: When set, raises `RuntimeError` once that many chunks were streamed and
            more remain; a value at or above the chunk count has no effect.
        record_calls: Whether to keep each call's messages in `calls`. The fake provider of a
            running stack disables it so visitors' prompts do not accumulate in memory.
        finish_reason: When set, reported on the final chunk as the provider's finish reason
            (for example "length" when the output limit cut the answer off).
        calls: The message list of every call, in order, if `record_calls` is set.

    The gate applies to async streaming only.
    """

    script: Sequence[str] | None = None
    gate: asyncio.Event | None = None
    fail_after: int | None = None
    record_calls: bool = True
    finish_reason: str | None = None
    calls: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "sourcehaven-scripted"

    def _planned_chunks(self, messages: list[BaseMessage]) -> list[str]:
        if self.script is not None:
            return list(self.script)
        for message in reversed(messages):
            match: re.Match[str] | None = _S1_PASSAGE.search(_text_of(message))
            if match is not None:
                answer: str = f"Based on the sources: {match.group(1)[:QUOTE_CHARACTERS]} [S1]"
                return _split_into_chunks(answer)
        return _split_into_chunks(NO_EVIDENCE_ANSWER)

    @staticmethod
    def _usage(messages: list[BaseMessage], chunks: list[str]) -> UsageMetadata:
        input_tokens: int = sum(len(_text_of(message).split()) for message in messages)
        output_tokens: int = len(chunks)
        return UsageMetadata(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

    def _chunk_message(
        self, messages: list[BaseMessage], chunks: list[str], index: int
    ) -> ChatGenerationChunk:
        if index < len(chunks) - 1:
            return ChatGenerationChunk(message=AIMessageChunk(content=chunks[index]))
        # Marking the chunk "last" stops langchain-core from appending an extra empty chunk.
        return ChatGenerationChunk(
            message=AIMessageChunk(
                content=chunks[index],
                usage_metadata=self._usage(messages, chunks),
                chunk_position="last",
            ),
            generation_info=(
                None if self.finish_reason is None else {"finish_reason": self.finish_reason}
            ),
        )

    def _record(self, messages: list[BaseMessage]) -> None:
        if self.record_calls:
            self.calls.append(list(messages))

    def _check_failure(self, streamed: int) -> None:
        if self.fail_after is not None and streamed >= self.fail_after:
            raise RuntimeError(f"scripted failure after {streamed} chunks")

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> Iterator[ChatGenerationChunk]:
        self._record(messages)
        chunks: list[str] = self._planned_chunks(messages)
        for index in range(len(chunks)):
            self._check_failure(index)
            yield self._chunk_message(messages, chunks, index)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> AsyncIterator[ChatGenerationChunk]:
        self._record(messages)
        chunks: list[str] = self._planned_chunks(messages)
        for index in range(len(chunks)):
            self._check_failure(index)
            generation: ChatGenerationChunk = self._chunk_message(messages, chunks, index)
            yield generation
            if index == 0 and self.gate is not None:
                await self.gate.wait()

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        pieces: list[ChatGenerationChunk] = list(self._stream(messages, stop, run_manager))
        return _join(pieces)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: object,
    ) -> ChatResult:
        pieces: list[ChatGenerationChunk] = [
            piece async for piece in self._astream(messages, stop, run_manager)
        ]
        return _join(pieces)


def _join(pieces: list[ChatGenerationChunk]) -> ChatResult:
    usage: UsageMetadata | None = None
    for piece in pieces:
        if isinstance(piece.message, AIMessageChunk) and piece.message.usage_metadata:
            usage = piece.message.usage_metadata
    message: AIMessage = AIMessage(
        content="".join(str(piece.message.content) for piece in pieces), usage_metadata=usage
    )
    return ChatResult(generations=[ChatGeneration(message=message)])
