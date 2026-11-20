from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from sourcehaven.api.schemas import QuestionRequest


def _request(question: str, document_ids: list[UUID]) -> QuestionRequest:
    return QuestionRequest.model_validate(
        {
            "client_request_id": str(uuid4()),
            "kind": "question",
            "question": question,
            "document_ids": [str(document_id) for document_id in document_ids],
        }
    )


def test_question_is_stripped() -> None:
    assert _request("  warranty?\n", [uuid4()]).question == "warranty?"


@pytest.mark.parametrize("question", ["", "   ", "\n\t"])
def test_blank_question_is_rejected(question: str) -> None:
    with pytest.raises(ValidationError):
        _request(question, [uuid4()])


def test_at_least_one_document_is_required() -> None:
    with pytest.raises(ValidationError):
        _request("ok?", [])


def test_only_question_kind_is_accepted() -> None:
    with pytest.raises(ValidationError):
        QuestionRequest.model_validate(
            {
                "client_request_id": str(uuid4()),
                "kind": "summary",
                "question": "ok?",
                "document_ids": [str(uuid4())],
            }
        )
