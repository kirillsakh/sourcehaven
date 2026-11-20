import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO, Final
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from sourcehaven.composition import ContainerOverrides
from sourcehaven.domain.models import OwnerScope
from sourcehaven.storage.db import owner_session
from sourcehaven.storage.models import Document, DocumentVersion, IngestionJob
from sourcehaven.storage.repositories.documents import get_document
from tests.support.app import ApiClientFactory
from tests.support.visitors import FIXTURE_DOCUMENTS, Visitor, VisitorFactory

pytestmark = pytest.mark.integration

NOT_FOUND_BODY: Final[dict[str, object]] = {"code": "not_found"}
UNKNOWN_ID: Final[str] = "0198f7a0-0000-7000-8000-000000000000"


def _stored_pdfs(visitor: Visitor) -> list[Path]:
    uploads: Path = visitor.container.settings.uploads_dir
    return [p for p in uploads.rglob("*.pdf") if ".incoming" not in p.parts]


def _incoming_files(visitor: Visitor) -> list[Path]:
    incoming: Path = visitor.container.settings.uploads_dir / ".incoming"
    return list(incoming.iterdir()) if incoming.exists() else []


async def test_upload_creates_queued_document(visitor: Visitor) -> None:
    response: httpx.Response = await visitor.upload("facts_small_en.pdf")
    assert response.status_code == 202
    body: dict[str, object] = response.json()
    assert body["state"] == "queued" and body["display_name"] == "facts_small_en.pdf"
    assert body["error_code"] is None and body["page_count"] is None
    assert body["progress"] == {"done": 0, "total": 0, "stage": None}


async def test_upload_writes_rows_and_file(visitor: Visitor) -> None:
    document_id: str = (await visitor.upload("facts_small_en.pdf")).json()["id"]
    owner: OwnerScope = await visitor.owner()
    async with owner_session(visitor.container.sessions, owner) as session:
        document: Document = (await session.execute(select(Document))).scalar_one()
        version: DocumentVersion = (await session.execute(select(DocumentVersion))).scalar_one()
        job: IngestionJob = (await session.execute(select(IngestionJob))).scalar_one()
    content: bytes = (FIXTURE_DOCUMENTS / "facts_small_en.pdf").read_bytes()
    assert str(document.id) == document_id and document.current_version_id is None
    assert document.content_sha256 == hashlib.sha256(content).digest()
    assert (version.state, version.version_no, version.byte_size) == ("queued", 1, len(content))
    assert version.file_key == f"{owner.owner_id}/{document.id}/{version.id}.pdf"
    assert (job.version_id, job.status) == (version.id, "queued")
    stored: list[Path] = _stored_pdfs(visitor)
    assert stored == [visitor.container.settings.uploads_dir / version.file_key]
    assert stored[0].read_bytes() == content
    assert _incoming_files(visitor) == []


async def test_document_can_be_read_back(visitor: Visitor) -> None:
    uploaded: dict[str, object] = (await visitor.upload("facts_small_en.pdf")).json()
    assert await visitor.document(str(uploaded["id"])) == uploaded


async def test_list_is_newest_first(visitor: Visitor) -> None:
    await visitor.upload("facts_small_en.pdf")
    await visitor.upload("multipage_en.pdf")
    names: list[str] = [
        d["display_name"] for d in (await visitor.client.get("/api/documents")).json()
    ]
    assert names == ["multipage_en.pdf", "facts_small_en.pdf"]


async def test_display_name_is_sanitised(visitor: Visitor) -> None:
    response: httpx.Response = await visitor.upload_bytes("../../etc/passwd.pdf", b"%PDF-1.7 x")
    assert response.json()["display_name"] == "passwd.pdf"


async def test_rejects_non_pdf_and_empty(visitor: Visitor) -> None:
    unsupported: httpx.Response = await visitor.upload_bytes("notes.pdf", b"hello")
    empty: httpx.Response = await visitor.upload_bytes("e.pdf", b"")
    assert (unsupported.status_code, unsupported.json()["code"]) == (415, "unsupported_type")
    assert (empty.status_code, empty.json()["code"]) == (422, "empty_file")
    assert _incoming_files(visitor) == [] and _stored_pdfs(visitor) == []


async def test_missing_file_field_is_an_invalid_request(visitor: Visitor) -> None:
    response: httpx.Response = await visitor.client.post(
        "/api/documents", files={"other": ("o.pdf", b"secret-content", "application/pdf")}
    )
    assert response.status_code == 422 and response.json()["code"] == "invalid_request"
    assert "secret-content" not in response.text


async def test_rejects_oversized_upload(make_visitor: VisitorFactory) -> None:
    visitor: Visitor = await make_visitor(settings_overrides={"max_upload_bytes": 1024})
    response: httpx.Response = await visitor.upload_bytes("big.pdf", b"%PDF-" + b"0" * 2048)
    assert response.status_code == 413 and response.json()["code"] == "too_large"
    assert _incoming_files(visitor) == [] and _stored_pdfs(visitor) == []


async def test_upload_at_exactly_the_limit_is_accepted(make_visitor: VisitorFactory) -> None:
    visitor: Visitor = await make_visitor(settings_overrides={"max_upload_bytes": 1024})
    response: httpx.Response = await visitor.upload_bytes("ok.pdf", b"%PDF-" + b"0" * 1019)
    assert response.status_code == 202


async def test_duplicate_upload_returns_the_existing_document(visitor: Visitor) -> None:
    first: httpx.Response = await visitor.upload("facts_small_en.pdf")
    second: httpx.Response = await visitor.upload_bytes(
        "renamed.pdf", (FIXTURE_DOCUMENTS / "facts_small_en.pdf").read_bytes()
    )
    assert (first.status_code, second.status_code) == (202, 200)
    assert second.json() == first.json()
    assert len(_stored_pdfs(visitor)) == 1 and _incoming_files(visitor) == []


async def test_concurrent_duplicate_uploads_create_one_document(visitor: Visitor) -> None:
    first, second = await asyncio.gather(
        visitor.upload("facts_small_en.pdf"), visitor.upload("facts_small_en.pdf")
    )
    assert {first.status_code, second.status_code} <= {200, 202}
    assert first.json()["id"] == second.json()["id"]
    assert len((await visitor.client.get("/api/documents")).json()) == 1
    assert len(_stored_pdfs(visitor)) == 1 and _incoming_files(visitor) == []


async def test_same_file_in_other_session_is_independent(
    two_visitors: tuple[Visitor, Visitor],
) -> None:
    x, y = two_visitors
    x_doc: dict[str, object] = (await x.upload("facts_small_en.pdf")).json()
    y_response: httpx.Response = await y.upload("facts_small_en.pdf")
    assert y_response.status_code == 202 and y_response.json()["id"] != x_doc["id"]


async def test_document_limit(make_visitor: VisitorFactory) -> None:
    visitor: Visitor = await make_visitor(settings_overrides={"max_documents_per_session": 1})
    await visitor.upload("facts_small_en.pdf")
    response: httpx.Response = await visitor.upload("multipage_en.pdf")
    assert response.status_code == 409 and response.json()["code"] == "session_document_limit"
    assert _incoming_files(visitor) == [] and len(_stored_pdfs(visitor)) == 1


async def test_reuploading_at_the_limit_returns_the_existing_document(
    make_visitor: VisitorFactory,
) -> None:
    visitor: Visitor = await make_visitor(settings_overrides={"max_documents_per_session": 1})
    await visitor.upload("facts_small_en.pdf")
    assert (await visitor.upload("facts_small_en.pdf")).status_code == 200


async def test_foreign_and_unknown_documents_are_the_same_404(
    two_visitors: tuple[Visitor, Visitor],
) -> None:
    x, y = two_visitors
    x_id: str = (await x.upload("facts_small_en.pdf")).json()["id"]
    foreign: httpx.Response = await y.client.get(f"/api/documents/{x_id}")
    unknown: httpx.Response = await y.client.get(f"/api/documents/{UNKNOWN_ID}")
    for response in (foreign, unknown):
        assert response.status_code == 404 and response.json() == NOT_FOUND_BODY
    assert (await y.client.get("/api/documents")).json() == []


async def test_documents_require_a_session(api_client: httpx.AsyncClient) -> None:
    assert (await api_client.get("/api/documents")).json() == {"code": "session_required"}
    upload: httpx.Response = await api_client.post(
        "/api/documents", files={"file": ("a.pdf", b"%PDF-1", "application/pdf")}
    )
    assert upload.status_code == 401


async def test_repository_get_document_is_owner_scoped(
    two_visitors: tuple[Visitor, Visitor],
) -> None:
    x, y = two_visitors
    x_id: str = (await x.upload("facts_small_en.pdf")).json()["id"]
    x_owner: OwnerScope = await x.owner()
    y_owner: OwnerScope = await y.owner()
    async with owner_session(x.container.sessions, x_owner) as session:
        assert await get_document(session, x_owner, UUID(x_id)) is not None
    async with owner_session(y.container.sessions, y_owner) as session:
        assert await get_document(session, y_owner, UUID(x_id)) is None


class BrokenFileStore:
    async def put(self, key: str, source: Path) -> None:
        raise OSError("disk full")

    def open(self, key: str) -> AbstractContextManager[BinaryIO]:
        raise NotImplementedError

    async def delete_prefix(self, prefix: str) -> None:
        return None


async def test_failed_store_leaves_no_rows_and_no_temp_file(make_visitor: VisitorFactory) -> None:
    visitor: Visitor = await make_visitor(
        overrides=ContainerOverrides(file_store=BrokenFileStore())
    )
    with pytest.raises(OSError, match="disk full"):
        await visitor.upload("facts_small_en.pdf")
    assert (await visitor.client.get("/api/documents")).json() == []
    assert _incoming_files(visitor) == []


async def test_declared_oversize_is_rejected_before_authentication_or_parsing(
    make_api_client: ApiClientFactory,
) -> None:
    async with make_api_client(settings_overrides={"max_upload_bytes": 1024}) as client:
        response: httpx.Response = await client.post(
            "/api/documents",
            content=b"x" * 40_000,
            headers={"content-type": "multipart/form-data; boundary=x"},
        )
        incoming: Path = client.container.settings.uploads_dir / ".incoming"
        assert response.status_code == 413 and response.json() == {"code": "too_large"}
        assert not incoming.exists()


async def test_chunked_oversize_body_is_aborted(make_visitor: VisitorFactory) -> None:
    visitor: Visitor = await make_visitor(settings_overrides={"max_upload_bytes": 1024})

    async def body() -> AsyncIterator[bytes]:
        yield (b'--x\r\nContent-Disposition: form-data; name="file"; filename="a.pdf"\r\n\r\n%PDF-')
        for _ in range(8):
            yield b"0" * 8192

    response: httpx.Response = await visitor.client.post(
        "/api/documents",
        content=body(),
        headers={"content-type": "multipart/form-data; boundary=x"},
    )
    assert "content-length" not in response.request.headers
    assert response.status_code == 413 and response.json() == {"code": "too_large"}
    # The handler creates `.incoming` first thing, so its absence shows the body never got that far.
    assert not (visitor.container.settings.uploads_dir / ".incoming").exists()
    assert _stored_pdfs(visitor) == []


async def test_concurrent_distinct_uploads_cannot_exceed_the_document_limit(
    make_visitor: VisitorFactory,
) -> None:
    visitor: Visitor = await make_visitor(settings_overrides={"max_documents_per_session": 1})
    responses: list[httpx.Response] = list(
        await asyncio.gather(
            visitor.upload("facts_small_en.pdf"), visitor.upload("multipage_en.pdf")
        )
    )
    assert sorted(r.status_code for r in responses) == [202, 409]
    assert [r.json()["code"] for r in responses if r.status_code == 409] == [
        "session_document_limit"
    ]
    assert len((await visitor.client.get("/api/documents")).json()) == 1
    assert len(_stored_pdfs(visitor)) == 1 and _incoming_files(visitor) == []
