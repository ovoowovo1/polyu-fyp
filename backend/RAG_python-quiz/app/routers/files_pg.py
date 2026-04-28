from typing import Optional

from fastapi import APIRouter

from app.routers.service_helpers import message_contains, run_service
from app.services import pg_service

router = APIRouter(prefix="", tags=["files"])

_MISSING_FILE_ZH = "".join(map(chr, [0x6A94, 0x6848, 0x4E0D, 0x5B58, 0x5728]))
_MISSING_CHUNK_ZH_1 = "".join(map(chr, [0x5340, 0x584A, 0x4E0D, 0x5B58, 0x5728]))
_MISSING_CHUNK_ZH_2 = "".join(map(chr, [0x7247, 0x6BB5, 0x4E0D, 0x5B58, 0x5728]))

_FILE_MISSING_SNIPPETS = ("not found", "file does not exist", "missing file", _MISSING_FILE_ZH)
_CHUNK_MISSING_SNIPPETS = (
    "chunk not found",
    "source details not found",
    "missing chunk",
    "chunk",
    "chunk does not exist",
    "missing source details",
    _MISSING_CHUNK_ZH_1,
    _MISSING_CHUNK_ZH_2,
)


def _is_missing_file(error: Exception) -> bool:
    return message_contains(*_FILE_MISSING_SNIPPETS)(error)


def _is_missing_chunk(error: Exception) -> bool:
    return message_contains(*_CHUNK_MISSING_SNIPPETS)(error)


@router.get("/files")
async def get_files(class_id: Optional[str] = None):
    files = await run_service(
        pg_service.get_files_list,
        class_id,
        fallback_detail=lambda error: {
            "error": "Failed to fetch files",
            "details": str(error),
        },
    )
    return {"message": "Files fetched", "files": files, "total": len(files)}


@router.delete("/files/{file_id}")
async def delete_file(file_id: str):
    result = await run_service(
        pg_service.delete_file,
        file_id,
        error_rules=[
            (_is_missing_file, 404, lambda error: {"error": "File not found", "details": str(error)}),
        ],
        fallback_detail=lambda error: {
            "error": "Failed to delete file",
            "details": str(error),
        },
    )
    return {
        "message": result["message"],
        "success": True,
        "deletedFile": result["deletedFile"],
    }


@router.get("/files/{file_id}")
async def get_file_details(file_id: str):
    details = await run_service(
        pg_service.get_specific_file,
        file_id,
        error_rules=[
            (_is_missing_file, 404, lambda error: {"error": "File not found", "details": str(error)}),
        ],
        fallback_detail=lambda error: {
            "error": "Failed to fetch file details",
            "details": str(error),
        },
    )
    return {
        "message": "File details fetched",
        "file": details["file"],
        "chunks": details["chunks"],
    }


@router.put("/files/{file_id}")
async def rename_file(file_id: str, new_name: str):
    result = await run_service(
        pg_service.rename_file,
        file_id,
        new_name,
        fallback_detail=lambda error: {
            "error": "Failed to rename file",
            "details": str(error),
        },
    )
    return {
        "message": result["message"],
        "success": True,
        "renamedFile": result["renamedFile"],
    }


@router.get("/chunks/{chunk_id}/source-details")
async def get_chunk_source_details(chunk_id: str):
    details = await run_service(
        pg_service.get_source_details_by_chunk_id,
        chunk_id,
        error_rules=[
            (_is_missing_chunk, 404, lambda error: {"error": "Chunk not found", "details": str(error)}),
        ],
        fallback_detail=lambda error: {
            "error": "Failed to fetch chunk source details",
            "details": str(error),
        },
    )
    return {"message": "Source details fetched", "details": details}
