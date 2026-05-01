from typing import Optional

from fastapi import APIRouter

from app.routers.service_helpers import run_service
from app.services import pg_service

router = APIRouter(prefix="", tags=["files"])


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
        fallback_detail=lambda error: {
            "error": "Failed to fetch chunk source details",
            "details": str(error),
        },
    )
    return {"message": "Source details fetched", "details": details}
