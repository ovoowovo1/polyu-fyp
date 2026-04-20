from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.logger import get_logger
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
        wrapped = DocumentIngestError(
            code="INGEST_FAILED",
            message="Unexpected ingest failure.",
            details=str(error),
        )
        error_payload = wrapped.to_dict()

    return {
        "filename": filename,
        "status": "failed",
        "message": error_payload["message"],
        "error": error_payload,
    }


def _summarize_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    succeeded = sum(1 for result in results if result["status"] == "success")
    failed = len(results) - succeeded
    return {
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed,
    }


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


@router.post("/upload-multiple")
async def upload_multiple(
    files: Optional[List[UploadFile]] = File(default=None),
    clientId: Optional[str] = Query(default=None),
    class_id: Optional[str] = Query(default=None),
):
    if not files:
        raise HTTPException(status_code=400, detail={"error": "Please provide at least one file."})

    results: List[Dict[str, Any]] = []
    total_files = len(files)
    await publish_progress(
        clientId,
        {
            "type": "progress",
            "done": 0,
            "total": total_files,
            "currentFile": None,
            "lastFileStatus": None,
        },
    )

    for index, upload_file in enumerate(files, start=1):
        try:
            data = await upload_file.read()
            payload = await ingest_document(
                filename=upload_file.filename or f"file-{index}",
                content=data,
                size=upload_file.size or len(data),
                mimetype=upload_file.content_type or "application/octet-stream",
                class_id=class_id,
            )
            result = _build_success_result(upload_file.filename or f"file-{index}", payload)
        except Exception as err:
            logger.warning("[Upload] File failed: %s - %s", upload_file.filename, err)
            result = _build_failure_result(upload_file.filename or f"file-{index}", err)

        results.append(result)
        await publish_progress(
            clientId,
            {
                "type": "progress",
                "done": index,
                "total": total_files,
                "currentFile": result["filename"],
                "lastFileStatus": result["status"],
            },
        )

    summary = _summarize_results(results)
    status = _batch_status(summary)
    payload = {
        "status": status,
        "summary": summary,
        "results": results,
    }
    await publish_progress(clientId, {"type": "finished", **payload})
    return JSONResponse(status_code=_http_status_for_batch(status), content=payload)


class UploadLinkBody(BaseModel):
    url: str


@router.post("/upload-link")
async def upload_link(
    body: UploadLinkBody,
    clientId: Optional[str] = Query(default=None),
    class_id: Optional[str] = Query(default=None),
):
    try:
        if not body or not body.url or not body.url.strip():
            raise HTTPException(status_code=400, detail={"error": "url is required"})

        url = body.url.strip()
        result = await ingest_website(url=url, client_id=clientId, class_id=class_id)
        return {"message": "Link upload completed.", "result": result}
    except HTTPException:
        raise
    except Exception as err:
        logger.error("Upload link error: %s", err, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "Failed to upload link.", "details": str(err)},
        )
