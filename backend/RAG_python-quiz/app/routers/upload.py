from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.logger import get_logger
from app.api_helpers import upload_helpers
from app.api_helpers.service_helpers import error_detail, run_async_service
from app.services.cache import redis_cache, studio_cache
from app.services.core.exceptions import PermissionDeniedError
from app.services.documents.document_service import ingest_document, ingest_website
from app.services.pg.pg_access_control import require_class_teacher
from app.services.realtime.progress_bus import publish_progress
from app.utils.jwt_utils import get_current_user

logger = get_logger(__name__)

router = APIRouter(prefix="", tags=["upload"])


_http_status_for_batch = upload_helpers.http_status_for_batch
_progress_payload = upload_helpers.progress_payload
_upload_batch_payload = upload_helpers.upload_batch_payload

UPLOAD_FORBIDDEN_MESSAGE = "Only the teacher who owns this class can upload source documents."


def _require_upload_permission(user: dict, class_id: str | None) -> None:
    if not class_id:
        raise HTTPException(
            status_code=400,
            detail=error_detail("class_id is required for document uploads."),
        )

    try:
        require_class_teacher(user["user_id"], class_id)
    except PermissionDeniedError as error:
        raise HTTPException(
            status_code=403,
            detail=error_detail(UPLOAD_FORBIDDEN_MESSAGE, code="UPLOAD_FORBIDDEN"),
        ) from error


def _invalidate_uploaded_file_caches(file_ids) -> None:
    namespaces = [studio_cache.files_list_namespace(), studio_cache.rag_retrieval_namespace()]
    namespaces.extend(
        studio_cache.file_detail_namespace(file_id)
        for file_id in _unique_string_ids(file_ids)
    )
    redis_cache.invalidate_namespaces(*namespaces)


def _unique_string_ids(file_ids) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for file_id in file_ids:
        if not file_id:
            continue
        normalized = str(file_id)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _successful_file_ids(results: list[dict[str, Any]]) -> list[str]:
    return [
        str(result["fileId"])
        for result in results
        if result.get("status") == "success" and result.get("fileId")
    ]


async def _process_upload_file(
    upload_file: UploadFile,
    index: int,
    class_id: str | None,
    user_id: str,
) -> dict[str, Any]:
    return await upload_helpers.process_upload_file(
        upload_file=upload_file,
        index=index,
        class_id=class_id,
        user_id=user_id,
        ingest_document_func=ingest_document,
        logger=logger,
    )


@router.post("/upload-multiple")
async def upload_multiple(
    files: list[UploadFile] | None = File(default=None),
    clientId: str | None = Query(default=None),
    class_id: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    if not files:
        return JSONResponse(
            status_code=400,
            content=error_detail("Please provide at least one file."),
        )

    _require_upload_permission(user, class_id)

    results: list[dict[str, Any]] = []
    total_files = len(files)
    await publish_progress(
        clientId,
        _progress_payload(event_type="progress", done=0, total=total_files),
    )

    for index, upload_file in enumerate(files, start=1):
        result = await _process_upload_file(upload_file, index, class_id, user["user_id"])
        results.append(result)
        await publish_progress(
            clientId,
            _progress_payload(
                event_type="progress",
                done=index,
                total=total_files,
                current_file=result["filename"],
                last_file_status=result["status"],
            ),
        )

    payload = _upload_batch_payload(results)
    _invalidate_uploaded_file_caches(_successful_file_ids(payload["results"]))
    await publish_progress(
        clientId,
        _progress_payload(
            event_type="finished",
            extra={
                "message": payload["message"],
                "status": payload["status"],
                "summary": payload["summary"],
                "results": payload["results"],
                "data": payload["data"],
            },
        ),
    )
    return JSONResponse(
        status_code=_http_status_for_batch(payload["status"]),
        content=payload,
    )


class UploadLinkBody(BaseModel):
    url: str


@router.post("/upload-link")
async def upload_link(
    body: UploadLinkBody,
    clientId: str | None = Query(default=None),
    class_id: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    if not body.url or not body.url.strip():
        return JSONResponse(
            status_code=400,
            content=error_detail("url is required"),
        )

    _require_upload_permission(user, class_id)

    try:
        result = await run_async_service(
            ingest_website,
            url=body.url.strip(),
            client_id=clientId,
            class_id=class_id,
            user_id=user["user_id"],
            logger=logger,
            log_message="Upload link error: %s",
            fallback_detail=lambda error: error_detail(
                "Failed to upload link.",
                details=str(error),
            ),
        )
    except HTTPException as error:
        return upload_helpers.http_exception_response(error)

    _invalidate_uploaded_file_caches([result.get("fileId")])
    return upload_helpers.upload_link_payload(result)
