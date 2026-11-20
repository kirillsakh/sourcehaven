import asyncio
import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final
from uuid import UUID, uuid4, uuid7

from fastapi import APIRouter, Depends, Response, UploadFile
from sqlalchemy.exc import IntegrityError

from sourcehaven.api.deps import current_owner, get_container
from sourcehaven.api.errors import ApiError
from sourcehaven.api.schemas import DocumentResponse, Progress
from sourcehaven.composition import AppContainer
from sourcehaven.config import Settings
from sourcehaven.domain.models import OwnerScope
from sourcehaven.storage.db import owner_session
from sourcehaven.storage.repositories.documents import (
    DocumentView,
    NewDocument,
    add_queued_document,
    count_documents,
    find_by_content_hash,
    get_document_view,
    list_document_views,
    lock_owner_uploads,
)

router: APIRouter = APIRouter(tags=["documents"])

CHUNK_BYTES: Final[int] = 64 * 1024
PDF_SIGNATURE: Final[bytes] = b"%PDF-"
MAX_DISPLAY_NAME_CHARACTERS: Final[int] = 200
DEFAULT_DISPLAY_NAME: Final[str] = "document.pdf"
INCOMING_DIRECTORY: Final[str] = ".incoming"


def sanitize_display_name(client_filename: str | None) -> str:
    """Turn a client-supplied filename into a safe display name.

    Keeps only the basename, drops control characters, NFC-normalises and truncates. The result
    is for display; it is never used as a path.
    """
    if client_filename is None:
        return DEFAULT_DISPLAY_NAME
    basename: str = client_filename.replace("\\", "/").rsplit("/", 1)[-1]
    printable: str = "".join(c for c in basename if unicodedata.category(c) != "Cc")
    normalized: str = unicodedata.normalize("NFC", printable)[:MAX_DISPLAY_NAME_CHARACTERS]
    return normalized.strip() or DEFAULT_DISPLAY_NAME


def _response(view: DocumentView) -> DocumentResponse:
    progress: Progress | None = None
    if view.progress_done is not None and view.progress_total is not None:
        progress = Progress(
            done=view.progress_done, total=view.progress_total, stage=view.progress_stage
        )
    return DocumentResponse(
        id=view.id,
        display_name=view.display_name,
        state=view.state,
        error_code=view.error_code,
        page_count=view.page_count,
        progress=progress,
        created_at=view.created_at,
    )


@dataclass(frozen=True)
class ReceivedUpload:
    size: int
    sha256: bytes


async def _receive(upload: UploadFile, destination: Path, max_bytes: int) -> ReceivedUpload:
    """Copy the upload to `destination` in chunks while hashing and validating it.

    Raises:
        ApiError: 413 beyond `max_bytes`, 422 for an empty file, 415 for a non-PDF.
    """
    digest: hashlib._Hash = hashlib.sha256()
    size: int = 0
    with destination.open("wb") as output:
        while chunk := await upload.read(CHUNK_BYTES):
            if size == 0 and not chunk.startswith(PDF_SIGNATURE):
                raise ApiError(415, "unsupported_type")
            size += len(chunk)
            if size > max_bytes:
                raise ApiError(413, "too_large")
            digest.update(chunk)
            await asyncio.to_thread(output.write, chunk)
    if size == 0:
        raise ApiError(422, "empty_file")
    return ReceivedUpload(size=size, sha256=digest.digest())


@dataclass(frozen=True)
class StoredUpload:
    view: DocumentView
    created: bool


async def _existing_document(
    container: AppContainer, owner: OwnerScope, sha256: bytes
) -> DocumentView | None:
    async with owner_session(container.sessions, owner) as session:
        existing_id: UUID | None = await find_by_content_hash(session, owner, sha256)
        if existing_id is None:
            return None
        return await get_document_view(session, owner, existing_id)


async def _store_upload(
    container: AppContainer, owner: OwnerScope, name: str, temp_file: Path, received: ReceivedUpload
) -> StoredUpload:
    """Register the upload, or return the owner's document that already has this content.

    The duplicate check, the document-count check and the inserts share one transaction that is
    serialised per owner, so concurrent uploads cannot exceed the document limit.

    Raises:
        ApiError: 409 if the owner already holds the maximum number of documents.
    """
    document_id: UUID = uuid7()
    version_id: UUID = uuid7()
    new: NewDocument = NewDocument(
        owner=owner,
        display_name=name,
        content_sha256=received.sha256,
        byte_size=received.size,
        document_id=document_id,
        version_id=version_id,
        file_key=f"{owner.owner_id}/{document_id}/{version_id}.pdf",
        now=container.clock(),
    )
    try:
        async with owner_session(container.sessions, owner) as session:
            await lock_owner_uploads(session, owner)
            existing_id: UUID | None = await find_by_content_hash(session, owner, received.sha256)
            if existing_id is not None:
                existing: DocumentView | None = await get_document_view(session, owner, existing_id)
                assert existing is not None
                return StoredUpload(existing, created=False)
            document_count: int = await count_documents(session, owner)
            if document_count >= container.settings.max_documents_per_session:
                raise ApiError(409, "session_document_limit")
            await add_queued_document(session, new)
            await container.file_store.put(new.file_key, temp_file)
            created: DocumentView | None = await get_document_view(session, owner, document_id)
            assert created is not None
        return StoredUpload(created, created=True)
    except ApiError:
        raise
    except IntegrityError:
        # The advisory lock makes this unreachable today; the unique key remains the safety net.
        await container.file_store.delete_prefix(f"{owner.owner_id}/{document_id}/")
        winner: DocumentView | None = await _existing_document(container, owner, received.sha256)
        if winner is None:
            raise
        return StoredUpload(winner, created=False)
    except Exception:
        await container.file_store.delete_prefix(f"{owner.owner_id}/{document_id}/")
        raise


@router.post("", status_code=202, responses={200: {"description": "Already uploaded"}})
async def upload_document(
    response: Response,
    file: UploadFile,
    container: Annotated[AppContainer, Depends(get_container)],
    owner: Annotated[OwnerScope, Depends(current_owner)],
) -> DocumentResponse:
    """Accept one PDF and queue it for ingestion.

    Uploading content the owner already has returns the existing document with 200. The request
    body is capped before this handler runs (see `UploadSizeLimitMiddleware`); the file itself is
    counted again while it is copied.
    """
    settings: Settings = container.settings
    incoming: Path = settings.uploads_dir / INCOMING_DIRECTORY
    await asyncio.to_thread(incoming.mkdir, parents=True, exist_ok=True)
    temp_file: Path = incoming / f"{uuid4().hex}.part"
    try:
        received: ReceivedUpload = await _receive(file, temp_file, settings.max_upload_bytes)
        stored: StoredUpload = await _store_upload(
            container, owner, sanitize_display_name(file.filename), temp_file, received
        )
        if not stored.created:
            response.status_code = 200
        return _response(stored.view)
    finally:
        await asyncio.to_thread(temp_file.unlink, missing_ok=True)


@router.get("")
async def list_documents(
    container: Annotated[AppContainer, Depends(get_container)],
    owner: Annotated[OwnerScope, Depends(current_owner)],
) -> list[DocumentResponse]:
    async with owner_session(container.sessions, owner) as session:
        return [_response(view) for view in await list_document_views(session, owner)]


@router.get("/{document_id}", responses={404: {"description": "Unknown document"}})
async def read_document(
    document_id: UUID,
    container: Annotated[AppContainer, Depends(get_container)],
    owner: Annotated[OwnerScope, Depends(current_owner)],
) -> DocumentResponse:
    async with owner_session(container.sessions, owner) as session:
        view: DocumentView | None = await get_document_view(session, owner, document_id)
    if view is None:
        raise ApiError(404, "not_found")
    return _response(view)
