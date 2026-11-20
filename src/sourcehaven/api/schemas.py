from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class SessionCreateRequest(BaseModel):
    verification_token: str | None = None


class SessionLimits(BaseModel):
    max_documents: int
    max_pages_per_document: int
    max_upload_bytes: int
    max_question_chars: int


class SessionResponse(BaseModel):
    idle_expires_at: datetime
    absolute_expires_at: datetime
    limits: SessionLimits


class Progress(BaseModel):
    done: int
    total: int
    stage: str | None


class DocumentResponse(BaseModel):
    id: UUID
    display_name: str
    state: str
    error_code: str | None
    page_count: int | None
    progress: Progress | None
    created_at: datetime


class QuestionRequest(BaseModel):
    """A question about some of the owner's documents.

    The question is stripped and must not be empty. Its maximum length and the maximum number
    of documents come from settings, so the route enforces them.
    """

    client_request_id: UUID
    kind: Literal["question"]
    question: str
    document_ids: list[UUID] = Field(min_length=1)

    @field_validator("question")
    @classmethod
    def strip_question(cls, question: str) -> str:
        stripped: str = question.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped


class ConversationCreated(BaseModel):
    id: UUID


class PageRange(BaseModel):
    start: int
    end: int


class TurnSourceResponse(BaseModel):
    label: str
    cited: bool
    document_id: UUID | None
    document_name: str
    pages: PageRange
    quote: str


class TurnResponse(BaseModel):
    id: UUID
    status: str
    question: str | None
    text: str
    sources: list[TurnSourceResponse]
    created_at: datetime


class ConversationResponse(BaseModel):
    id: UUID
    turns: list[TurnResponse]
