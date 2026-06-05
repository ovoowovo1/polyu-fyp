from __future__ import annotations

from typing import Any, Callable, Awaitable

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.routers.service_helpers import success_payload
from app.utils.ingest_errors import DocumentIngestError, EmbeddingProviderError


def build_success_result(filename: str, payload: dict[str, Any]) -> dict[str, Any]:
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


def build_failure_result(filename: str, error: Exception) -> dict[str, Any]:
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


def summarize_results(results: list[dict[str, Any]]) -> dict[str, int]:
    succeeded = sum(1 for result in results if result["status"] == "success")
    failed = len(results) - succeeded
    return {"total": len(results), "succeeded": succeeded, "failed": failed}


def batch_status(summary: dict[str, int]) -> str:
    return "success" if summary["failed"] == 0 else "failed" if summary["succeeded"] == 0 else "partial"


def http_status_for_batch(status: str) -> int:
    return {"success": 200, "partial": 207}.get(status, 502)


def progress_payload(
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


def upload_batch_payload(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize_results(results)
    status = batch_status(summary)
    return success_payload(
        f"Upload batch {status}",
        {
            "status": status,
            "summary": summary,
            "results": results,
        },
        include_root_fields=True,
    )


async def process_upload_file(
    *,
    upload_file,
    index: int,
    class_id: str | None,
    ingest_document_func: Callable[..., Awaitable[dict[str, Any]]],
    logger,
) -> dict[str, Any]:
    filename = upload_file.filename or f"file-{index}"
    try:
        data = await upload_file.read()
        payload = await ingest_document_func(
            filename=filename,
            content=data,
            size=upload_file.size or len(data),
            mimetype=upload_file.content_type or "application/octet-stream",
            class_id=class_id,
        )
        return build_success_result(filename, payload)
    except Exception as error:
        logger.warning("[Upload] File failed filename=%s error=%s", filename, error)
        return build_failure_result(filename, error)


def http_exception_response(error: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content=error.detail)


def upload_link_payload(result: dict[str, Any]) -> dict[str, Any]:
    return success_payload(
        "Link upload completed.",
        result,
        include_root_fields=False,
        result=result,
    )
