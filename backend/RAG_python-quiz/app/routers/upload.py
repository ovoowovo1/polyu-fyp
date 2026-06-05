from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.logger import get_logger
from app.routers import upload_helpers
from app.routers.service_helpers import error_detail, run_async_service
from app.services.documents.document_service import ingest_document, ingest_website
from app.services.realtime.progress_bus import publish_progress
from app.utils.jwt_utils import get_current_user

logger = get_logger(__name__)

router = APIRouter(prefix="", tags=["upload"])

_build_success_result = upload_helpers.build_success_result
_build_failure_result = upload_helpers.build_failure_result
_summarize_results = upload_helpers.summarize_results
_batch_status = upload_helpers.batch_status
_http_status_for_batch = upload_helpers.http_status_for_batch
_progress_payload = upload_helpers.progress_payload
_upload_batch_payload = upload_helpers.upload_batch_payload


async def _process_upload_file(upload_file: UploadFile, index: int, class_id: str | None) -> dict[str, Any]:
    return await upload_helpers.process_upload_file(
        upload_file=upload_file,
        index=index,
        class_id=class_id,
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

    results: list[dict[str, Any]] = []
    total_files = len(files)
    await publish_progress(
        clientId,
        _progress_payload(event_type="progress", done=0, total=total_files),
    )

    for index, upload_file in enumerate(files, start=1):
        result = await _process_upload_file(upload_file, index, class_id)
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

    try:
        result = await run_async_service(
            ingest_website,
            url=body.url.strip(),
            client_id=clientId,
            class_id=class_id,
            logger=logger,
            log_message="Upload link error: %s",
            fallback_detail=lambda error: error_detail(
                "Failed to upload link.",
                details=str(error),
            ),
        )
    except HTTPException as error:
        return upload_helpers.http_exception_response(error)

    return upload_helpers.upload_link_payload(result)
