from typing import Dict

from fastapi import APIRouter, HTTPException, Body, Depends
from pydantic import BaseModel
import asyncio

from app.utils.jwt_utils import get_current_user
from app.services import pg_service


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
    """建立班級（僅教師可用）。"""
    user_id = current_user["user_id"]
    try:
        created = await asyncio.to_thread(
            pg_service.create_class_for_teacher, user_id, request.name
        )
        return {"message": "班級建立成功", "class": created}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail={"error": str(e)})
    except RuntimeError as e:
        # 一般的驗證/資料錯誤
        raise HTTPException(status_code=400, detail={"error": str(e)})
    except Exception as e:
        # 其他未知錯誤
        raise HTTPException(status_code=500, detail={"error": "Failed to create class", "details": str(e)})


@router.get("/mine")
async def list_my_classes(current_user: Dict[str, str] = Depends(get_current_user)):
    """取得當前教師的班級列表。"""
    user_id = current_user["user_id"]
    try:
        classes = await asyncio.to_thread(pg_service.list_classes_by_teacher, user_id)
        return {"classes": classes, "total": len(classes)}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail={"error": str(e)})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "Failed to fetch classes", "details": str(e)})


@router.get("/enrolled")
async def list_enrolled_classes(current_user: Dict[str, str] = Depends(get_current_user)):
    """取得當前學生所屬之班級列表。"""
    user_id = current_user["user_id"]
    try:
        classes = await asyncio.to_thread(pg_service.list_classes_for_student, user_id)
        return {"classes": classes, "total": len(classes)}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail={"error": str(e)})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "Failed to fetch enrolled classes", "details": str(e)})

@router.post("/{class_id}/invite")
async def invite_student(
    class_id: str,
    request: InviteRequest = Body(...),
    current_user: Dict[str, str] = Depends(get_current_user),
):
    """將學生（透過 email）加入目前教師所屬的指定班級。"""
    user_id = current_user["user_id"]
    try:
        result = await asyncio.to_thread(
            pg_service.invite_student_to_class, user_id, class_id, request.email
        )
        return {"message": "學生已加入班級", "enrollment": result}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail={"error": str(e)})
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail={"error": str(e)})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "Failed to invite student", "details": str(e)})


