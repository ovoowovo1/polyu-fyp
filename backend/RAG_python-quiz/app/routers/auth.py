from fastapi import APIRouter, HTTPException, Body, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import asyncio

from app.services.pg_auth_service import login as auth_login, register as auth_register
from app.logger import get_logger
from app.utils.jwt_utils import verify_token

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()


class LoginRequest(BaseModel):
    email: str
    password: str
    role: str = None


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = "student"  # 'student' 或 'teacher'


@router.post("/login")
async def login(request: LoginRequest = Body(...)):
    """
    用戶登入接口
    
    返回 JWT token，前端需要將此 token 存儲並在後續請求中使用
    """
    logger.info(f"Login attempt for email: {request.email}")
    try:
        # 支援前端傳入 role，若提供則後端會驗證該帳號的 role 是否與請求一致
        result = await asyncio.to_thread(auth_login, request.email, request.password, request.role)
        logger.info(f"Login successful for email: {request.email}")
        return result
    except ValueError as e:
        logger.warning(f"Login failed for email: {request.email}: {str(e)}")
        raise HTTPException(status_code=401, detail={"error": str(e)})
    except Exception as e:
        logger.error(f"Login failed for email: {request.email}, error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "Login failed", "details": str(e)})


@router.post("/register")
async def register(request: RegisterRequest = Body(...)):
    """
    用戶註冊接口
    """
    logger.info(f"Registration attempt for email: {request.email} (role: {request.role})")
    try:
        result = await asyncio.to_thread(auth_register, request.email, request.password, request.full_name, request.role)
        logger.info(f"Registration successful for email: {request.email}")
        return result
    except ValueError as e:
        logger.warning(f"Registration failed for email: {request.email}: {str(e)}")
        raise HTTPException(status_code=400, detail={"error": str(e)})
    except Exception as e:
        logger.error(f"Registration failed for email: {request.email}, error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail={"error": "Register failed", "details": str(e)})


@router.get("/verify")
async def verify_token_endpoint(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    驗證 token 是否有效
    
    前端可以在需要時調用此接口來檢查 token 是否仍然有效
    """
    token = credentials.credentials
    payload = verify_token(token)
    if payload:
        return {"valid": True, "user_id": payload.get("sub"), "email": payload.get("username")}
    else:
        raise HTTPException(status_code=401, detail={"error": "Invalid or expired token"})
