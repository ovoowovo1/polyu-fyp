from typing import Dict

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel

from app.routers.service_helpers import exception_is, run_service
from app.services import pg_service
from app.utils.jwt_utils import get_current_user


router = APIRouter(prefix="/classes", tags=["classes"])


class CreateClassRequest(BaseModel):
    name: str


class InviteRequest(BaseModel):
    email: str


@router.post("/", status_code=201)
async def create_class(
    request: CreateClassRequest = Body(...),
    current_user: Dict[str, str] = Depends(get_current_user),
):
    created = await run_service(
        pg_service.create_class_for_teacher,
        current_user["user_id"],
        request.name,
        error_rules=[
            (exception_is(PermissionError), 403, lambda error: {"error": str(error)}),
            (exception_is(RuntimeError), 400, lambda error: {"error": str(error)}),
        ],
        fallback_detail=lambda error: {
            "error": "Failed to create class",
            "details": str(error),
        },
    )
    return {"message": "Class created", "class": created}


@router.get("/mine")
async def list_my_classes(current_user: Dict[str, str] = Depends(get_current_user)):
    classes = await run_service(
        pg_service.list_classes_by_teacher,
        current_user["user_id"],
        error_rules=[
            (exception_is(PermissionError), 403, lambda error: {"error": str(error)}),
        ],
        fallback_detail=lambda error: {
            "error": "Failed to fetch classes",
            "details": str(error),
        },
    )
    return {"classes": classes, "total": len(classes)}


@router.get("/enrolled")
async def list_enrolled_classes(current_user: Dict[str, str] = Depends(get_current_user)):
    classes = await run_service(
        pg_service.list_classes_for_student,
        current_user["user_id"],
        error_rules=[
            (exception_is(PermissionError), 403, lambda error: {"error": str(error)}),
        ],
        fallback_detail=lambda error: {
            "error": "Failed to fetch enrolled classes",
            "details": str(error),
        },
    )
    return {"classes": classes, "total": len(classes)}


@router.post("/{class_id}/invite")
async def invite_student(
    class_id: str,
    request: InviteRequest = Body(...),
    current_user: Dict[str, str] = Depends(get_current_user),
):
    result = await run_service(
        pg_service.invite_student_to_class,
        current_user["user_id"],
        class_id,
        request.email,
        error_rules=[
            (exception_is(PermissionError), 403, lambda error: {"error": str(error)}),
            (exception_is(RuntimeError), 400, lambda error: {"error": str(error)}),
        ],
        fallback_detail=lambda error: {
            "error": "Failed to invite student",
            "details": str(error),
        },
    )
    return {"message": "Student invited", "enrollment": result}
