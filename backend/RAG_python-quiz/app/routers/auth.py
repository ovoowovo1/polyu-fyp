from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.logger import get_logger
from app.routers.service_helpers import error_detail, run_service, success_payload
from app.services.pg.pg_auth_service import (
    login as auth_login,
    logout as auth_logout,
    refresh_session as auth_refresh_session,
    register as auth_register,
)
from app.utils.jwt_utils import verify_token

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    email: str
    password: str
    role: str | None = None


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = "student"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


@router.post("/login")
async def login(request: LoginRequest = Body(...)):
    logger.info("Login attempt for email=%s", request.email)
    result = await run_service(
        auth_login,
        request.email,
        request.password,
        request.role,
        error_rules=[
            (
                lambda error: isinstance(error, ValueError),
                401,
                lambda error: error_detail(str(error)),
            )
        ],
        logger=logger,
        log_message="Login failed: %s",
        fallback_detail=lambda error: error_detail("Login failed", details=str(error)),
    )
    logger.info("Login successful for email=%s", request.email)
    return success_payload(
        "Login successful",
        result,
        include_root_fields=True,
    )


@router.post("/register")
async def register(request: RegisterRequest = Body(...)):
    logger.info("Registration attempt for email=%s role=%s", request.email, request.role)
    result = await run_service(
        auth_register,
        request.email,
        request.password,
        request.full_name,
        request.role,
        error_rules=[
            (
                lambda error: isinstance(error, ValueError),
                400,
                lambda error: error_detail(str(error)),
            )
        ],
        logger=logger,
        log_message="Registration failed: %s",
        fallback_detail=lambda error: error_detail("Register failed", details=str(error)),
    )
    logger.info("Registration successful for email=%s", request.email)
    return success_payload(
        result.get("message", "Register successful") if isinstance(result, dict) else "Register successful",
        result,
        include_root_fields=True,
    )


@router.post("/refresh")
async def refresh(request: RefreshRequest = Body(...)):
    result = await run_service(
        auth_refresh_session,
        request.refresh_token,
        error_rules=[
            (
                lambda error: isinstance(error, ValueError),
                401,
                lambda error: error_detail(str(error)),
            )
        ],
        logger=logger,
        log_message="Refresh token failed: %s",
        fallback_detail=lambda error: error_detail("Refresh failed", details=str(error)),
    )
    return success_payload("Token refreshed", result, include_root_fields=True)


@router.post("/logout")
async def logout(request: LogoutRequest = Body(...)):
    result = await run_service(
        auth_logout,
        request.refresh_token,
        error_rules=[
            (
                lambda error: isinstance(error, ValueError),
                401,
                lambda error: error_detail(str(error)),
            )
        ],
        logger=logger,
        log_message="Logout failed: %s",
        fallback_detail=lambda error: error_detail("Logout failed", details=str(error)),
    )
    return success_payload(
        result.get("message", "Logout successful") if isinstance(result, dict) else "Logout successful",
        result,
        include_root_fields=True,
    )


@router.get("/verify")
async def verify_token_endpoint(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=401,
            detail=error_detail("Authorization header missing"),
        )

    payload = verify_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail=error_detail("Invalid or expired token"),
        )

    result = {
        "valid": True,
        "user_id": payload.get("sub"),
        "email": payload.get("username"),
    }
    return success_payload("Token verified", result, include_root_fields=True)
