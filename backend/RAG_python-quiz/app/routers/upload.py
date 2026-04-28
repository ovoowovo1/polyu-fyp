from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.logger import get_logger
from app.routers.service_helpers import error_detail, run_async_service, success_payload
from app.services.document_service import ingest_document, ingest_website
from app.services.progress_bus import publish_progress
from app.utils.ingest_errors import DocumentIngestError, EmbeddingProviderError

logger = get_logger(__name__)

router = APIRouter(prefix="", tags=["upload"])


def _build_success_result(filename: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    result = {
        "filename": filename,
        "status": "success",
        "message": payload.get("message") or f"Uploaded {filename}",
    }
    if payload.get("fileId") is not None:
        result["fileId"] = payload["fileId"]
    if payload.get("isNew") is not None:
        result["isNew"] = payload["isNew"]
    if payload.get("chunksCount") is not None:
        result["chunksCount"] = payload["chunksCount"]
    return result


def _build_failure_result(filename: str, error: Exception) -> Dict[str, Any]:
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


def _summarize_results(results: List[Dict[str, Any]]) -> Dict[str, int]:
    succeeded = sum(1 for result in results if result["status"] == "success")
    failed = len(results) - succeeded
    return {"total": len(results), "succeeded": succeeded, "failed": failed}


def _batch_status(summary: Dict[str, int]) -> str:
    if summary["failed"] == 0:
        return "success"
    if summary["succeeded"] == 0:
        return "failed"
    return "partial"


def _http_status_for_batch(batch_status: str) -> int:
    if batch_status == "success":
        return 200
    if batch_status == "partial":
        return 207
    return 502


def _progress_payload(
    *,
    event_type: str,
    done: int | None = None,
    total: int | None = None,
    current_file: str | None = None,
    last_file_status: str | None = None,
    extra: Optional[dict[str, Any]] = None,
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


def _upload_batch_payload(results: List[Dict[str, Any]]) -> dict[str, Any]:
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
    files: Optional[List[UploadFile]] = File(default=None),
    clientId: Optional[str] = Query(default=None),
    class_id: Optional[str] = Query(default=None),
):
    if not files:
        return JSONResponse(
            status_code=400,
            content=error_detail("Please provide at least one file."),
        )

    results: List[Dict[str, Any]] = []
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
    clientId: Optional[str] = Query(default=None),
    class_id: Optional[str] = Query(default=None),
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
