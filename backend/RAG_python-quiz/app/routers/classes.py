from fastapi import APIRouter, Body, Depends, Response
from pydantic import BaseModel

from app.api_helpers.service_helpers import error_detail, exception_is, run_service
from app.services.cache import redis_cache
from app.services.cache import studio_cache
from app.services.pg import pg_classes_service as pg_service
from app.utils.jwt_utils import get_current_user


router = APIRouter(prefix="/classes", tags=["classes"])


class CreateClassRequest(BaseModel):
    name: str


class InviteRequest(BaseModel):
    email: str


@router.post("/", status_code=201)
async def create_class(
    request: CreateClassRequest = Body(...),
    current_user: dict[str, str] = Depends(get_current_user),
):
    created = await run_service(
        pg_service.create_class_for_teacher,
        current_user["user_id"],
        request.name,
        error_rules=[
            (exception_is(PermissionError), 403, lambda error: error_detail(str(error))),
            (exception_is(RuntimeError), 400, lambda error: error_detail(str(error))),
        ],
        fallback_detail=lambda error: error_detail("Failed to create class", details=str(error)),
    )
    await redis_cache.invalidate_namespaces(studio_cache.classes_user_namespace(current_user["user_id"]))
    return {"message": "Class created", "class": created}


@router.get("/mine")
async def list_my_classes(response: Response, current_user: dict[str, str] = Depends(get_current_user)):
    user_id = current_user["user_id"]

    async def load():
        classes = await run_service(
            pg_service.list_classes_by_teacher,
            user_id,
            error_rules=[
                (exception_is(PermissionError), 403, lambda error: error_detail(str(error))),
            ],
            fallback_detail=lambda error: error_detail("Failed to fetch classes", details=str(error)),
        )
        return {"classes": classes, "total": len(classes)}

    if not redis_cache.is_enabled() or not studio_cache.can_use_cache(pg_service.is_user_teacher, user_id):
        result = await redis_cache.load_without_cache("classes:mine", load, reason="disabled_or_role_check")
        redis_cache.set_response_cache_headers(response, result)
        return result.value

    result = await redis_cache.get_or_set_json_with_status(
        "classes:mine",
        {"user_id": user_id},
        load,
        version_namespaces=[studio_cache.classes_user_namespace(user_id)],
    )
    redis_cache.set_response_cache_headers(response, result)
    return result.value


@router.get("/enrolled")
async def list_enrolled_classes(response: Response, current_user: dict[str, str] = Depends(get_current_user)):
    user_id = current_user["user_id"]

    async def load():
        classes = await run_service(
            pg_service.list_classes_for_student,
            user_id,
            error_rules=[
                (exception_is(PermissionError), 403, lambda error: error_detail(str(error))),
            ],
            fallback_detail=lambda error: error_detail("Failed to fetch enrolled classes", details=str(error)),
        )
        return {"classes": classes, "total": len(classes)}

    if not redis_cache.is_enabled() or not studio_cache.can_use_cache(pg_service.is_user_student, user_id):
        result = await redis_cache.load_without_cache("classes:enrolled", load, reason="disabled_or_role_check")
        redis_cache.set_response_cache_headers(response, result)
        return result.value

    result = await redis_cache.get_or_set_json_with_status(
        "classes:enrolled",
        {"user_id": user_id},
        load,
        version_namespaces=[studio_cache.classes_user_namespace(user_id)],
    )
    redis_cache.set_response_cache_headers(response, result)
    return result.value


@router.post("/{class_id}/invite")
async def invite_student(
    class_id: str,
    request: InviteRequest = Body(...),
    current_user: dict[str, str] = Depends(get_current_user),
):
    result = await run_service(
        pg_service.invite_student_to_class,
        current_user["user_id"],
        class_id,
        request.email,
        error_rules=[
            (exception_is(PermissionError), 403, lambda error: error_detail(str(error))),
            (exception_is(RuntimeError), 400, lambda error: error_detail(str(error))),
        ],
        fallback_detail=lambda error: error_detail("Failed to invite student", details=str(error)),
    )
    student_id = result.get("student_id") or (result.get("student") or {}).get("id")
    await redis_cache.invalidate_namespaces(
        studio_cache.classes_user_namespace(current_user["user_id"]),
        studio_cache.classes_user_namespace(str(student_id)) if student_id else "",
    )
    return {"message": "Student invited", "enrollment": result}
