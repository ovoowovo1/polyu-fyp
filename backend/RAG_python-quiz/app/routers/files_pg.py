from fastapi import APIRouter, Depends

from app.routers.service_helpers import error_detail, require_allowed, require_teacher, run_service
from app.services.pg.pg_access_control import can_access_chunk, can_access_class, can_access_document
from app.services.pg.pg_classes_service import is_user_teacher
from app.services.pg.pg_files_service import (
    delete_file as delete_file_record,
    get_files_list,
    get_source_details_by_chunk_id,
    get_specific_file,
    rename_file as rename_file_record,
)
from app.utils.jwt_utils import get_current_user

router = APIRouter(prefix="", tags=["files"])


@router.get("/files")
async def get_files(class_id: str | None = None, user: dict = Depends(get_current_user)):
    if class_id:
        require_allowed(can_access_class(user["user_id"], class_id))
    files = await run_service(
        get_files_list,
        class_id,
        user["user_id"],
        fallback_detail=lambda error: error_detail("Failed to fetch files", details=str(error)),
    )
    return {"message": "Files fetched", "files": files, "total": len(files)}


@router.delete("/files/{file_id}")
async def delete_file(file_id: str, user: dict = Depends(get_current_user)):
    require_teacher(user, "Only teachers can delete files", is_user_teacher)
    require_allowed(can_access_document(user["user_id"], file_id))
    result = await run_service(
        delete_file_record,
        file_id,
        user["user_id"],
        fallback_detail=lambda error: error_detail("Failed to delete file", details=str(error)),
    )
    return {
        "message": result["message"],
        "success": True,
        "deletedFile": result["deletedFile"],
    }


@router.get("/files/{file_id}")
async def get_file_details(file_id: str, user: dict = Depends(get_current_user)):
    require_allowed(can_access_document(user["user_id"], file_id))
    details = await run_service(
        get_specific_file,
        file_id,
        user["user_id"],
        fallback_detail=lambda error: error_detail("Failed to fetch file details", details=str(error)),
    )
    return {
        "message": "File details fetched",
        "file": details["file"],
        "chunks": details["chunks"],
    }


@router.put("/files/{file_id}")
async def rename_file(file_id: str, new_name: str, user: dict = Depends(get_current_user)):
    require_teacher(user, "Only teachers can rename files", is_user_teacher)
    require_allowed(can_access_document(user["user_id"], file_id))
    result = await run_service(
        rename_file_record,
        file_id,
        new_name,
        user["user_id"],
        fallback_detail=lambda error: error_detail("Failed to rename file", details=str(error)),
    )
    return {
        "message": result["message"],
        "success": True,
        "renamedFile": result["renamedFile"],
    }


@router.get("/chunks/{chunk_id}/source-details")
async def get_chunk_source_details(chunk_id: str, user: dict = Depends(get_current_user)):
    require_allowed(can_access_chunk(user["user_id"], chunk_id))
    details = await run_service(
        get_source_details_by_chunk_id,
        chunk_id,
        user["user_id"],
        fallback_detail=lambda error: error_detail("Failed to fetch chunk source details", details=str(error)),
    )
    return {"message": "Source details fetched", "details": details}
