from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.logger import get_logger
from app.routers.service_helpers import error_detail, run_async_service, success_payload
from app.services.documents.document_service import ingest_document, ingest_website
from app.services.realtime.progress_bus import publish_progress
from app.utils.ingest_errors import DocumentIngestError, EmbeddingProviderError
from app.utils.jwt_utils import get_current_user

logger = get_logger(__name__)

router = APIRouter(prefix="", tags=["upload"])


def _build_success_result(filename: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "filename": filename,
        "status": "success",
        "message": payload.get("message") or f"Uploaded {filename}",
        **{
            key: payload[key]
            for key in ("fileId", "isNew", "chunksCount")
            if payload.get(key) is not None
        },
    }


def _build_failure_result(filename: str, error: Exception) -> dict[str, Any]:
    if isinstance(error, EmbeddingProviderError):
        error_payload = error.to_dict()
    elif isinstance(error, DocumentIngestError):
        error_payload = error.to_dict()
    else:
        error_payload = DocumentIngestError(
            code="INGEST_FAILED",
            message="Unexpected ingest failure.",
            details=str(error),
        ).to_dict()

    return {
        "filename": filename,
        "status": "failed",
        "message": error_payload["message"],
        "error": error_payload,
    }


def _summarize_results(results: list[dict[str, Any]]) -> dict[str, int]:
    succeeded = sum(1 for result in results if result["status"] == "success")
    failed = len(results) - succeeded
    return {"total": len(results), "succeeded": succeeded, "failed": failed}


def _batch_status(summary: dict[str, int]) -> str:
    return "success" if summary["failed"] == 0 else "failed" if summary["succeeded"] == 0 else "partial"


def _http_status_for_batch(batch_status: str) -> int:
    return {"success": 200, "partial": 207}.get(batch_status, 502)


def _progress_payload(
    *,
    event_type: str,
    done: int | None = None,
    total: int | None = None,
    current_file: str | None = None,
    last_file_status: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "type": event_type,
        "done": done,
        "total": total,
        "currentFile": current_file,
        "lastFileStatus": last_file_status,
    }
    if extra:
        payload.update(extra)
    return payload


def _upload_batch_payload(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _summarize_results(results)
    status = _batch_status(summary)
    return success_payload(
        f"Upload batch {status}",
        {
            "status": status,
            "summary": summary,
            "results": results,
        },
        include_root_fields=True,
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
        filename = upload_file.filename or f"file-{index}"
        try:
            data = await upload_file.read()
            payload = await ingest_document(
                filename=filename,
                content=data,
                size=upload_file.size or len(data),
                mimetype=upload_file.content_type or "application/octet-stream",
                class_id=class_id,
            )
            result = _build_success_result(filename, payload)
        except Exception as error:
            logger.warning("[Upload] File failed filename=%s error=%s", filename, error)
            result = _build_failure_result(filename, error)

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
        return JSONResponse(status_code=error.status_code, content=error.detail)

    return success_payload(
        "Link upload completed.",
        result,
        include_root_fields=False,
        result=result,
    )
