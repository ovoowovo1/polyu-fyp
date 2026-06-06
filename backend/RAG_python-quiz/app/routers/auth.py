from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config import get_settings
from app.logger import get_logger
from app.api_helpers.service_helpers import error_detail, run_service, success_payload
from app.services.auth.refresh_tokens import REFRESH_TOKEN_EXPIRES_DAYS
from app.services.auth.service import auth_service
from app.utils.jwt_utils import verify_token

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)
auth_login = auth_service.login
auth_register = auth_service.register
auth_refresh_session = auth_service.refresh_session
auth_logout = auth_service.logout
REFRESH_TOKEN_COOKIE = "refresh_token"
REFRESH_TOKEN_COOKIE_PATH = "/auth"
REFRESH_TOKEN_COOKIE_MAX_AGE = REFRESH_TOKEN_EXPIRES_DAYS * 24 * 60 * 60
CLIENT_PLATFORM_HEADER = "x-client-platform"
MOBILE_CLIENT_PLATFORMS = {"expo", "expo-native", "mobile", "native"}


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
    refresh_token: str | None = None


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


def _should_include_refresh_token(request: Request) -> bool:
    return request.headers.get(CLIENT_PLATFORM_HEADER, "").strip().lower() in MOBILE_CLIENT_PLATFORMS


def _public_token_payload(result: dict, *, include_refresh_token: bool = False) -> dict:
    payload = dict(result)
    if not include_refresh_token:
        payload.pop("refresh_token", None)
    return payload


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        max_age=REFRESH_TOKEN_COOKIE_MAX_AGE,
        path=REFRESH_TOKEN_COOKIE_PATH,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE,
        path=REFRESH_TOKEN_COOKIE_PATH,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
    )


def _refresh_token_from_request(body, cookie_value: str | None) -> str:
    if cookie_value:
        return cookie_value
    return body.refresh_token if body and body.refresh_token else ""


@router.post("/login")
async def login(response: Response, client_request: Request, request: LoginRequest = Body(...)):
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
    _set_refresh_cookie(response, result["refresh_token"])
    public_result = _public_token_payload(
        result,
        include_refresh_token=_should_include_refresh_token(client_request),
    )
    return success_payload(
        "Login successful",
        public_result,
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
async def refresh(
    response: Response,
    client_request: Request,
    request: RefreshRequest | None = Body(default=None),
    refresh_cookie: str | None = Cookie(default=None, alias=REFRESH_TOKEN_COOKIE),
):
    refresh_token = _refresh_token_from_request(request, refresh_cookie)
    result = await run_service(
        auth_refresh_session,
        refresh_token,
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
    _set_refresh_cookie(response, result["refresh_token"])
    public_result = _public_token_payload(
        result,
        include_refresh_token=_should_include_refresh_token(client_request),
    )
    return success_payload("Token refreshed", public_result, include_root_fields=True)


@router.post("/logout")
async def logout(
    response: Response,
    request: LogoutRequest | None = Body(default=None),
    refresh_cookie: str | None = Cookie(default=None, alias=REFRESH_TOKEN_COOKIE),
):
    refresh_token = _refresh_token_from_request(request, refresh_cookie)
    result = await run_service(
        auth_logout,
        refresh_token,
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
    _clear_refresh_cookie(response)
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
