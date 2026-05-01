import os
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.logger import get_logger
from app.routers.auth import router as auth_router
from app.routers.classes import router as classes_router
from app.routers.exam import router as exam_router
from app.routers.files_pg import router as files_router
from app.routers.query_stream import router as query_router
from app.routers.quiz import router as quiz_router
from app.routers.sse import router as sse_router
from app.routers.tts import router as tts_router
from app.routers.upload import router as upload_router
from fastapi.responses import JSONResponse
from app.services.exceptions import ServiceError
from app.services import pg_service
from app.utils.jwt_utils import verify_token


request_logger = get_logger("api.request")


def _default_static_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "static")


def _create_startup_handler():
    def on_startup():
        pg_service.setup_vector_index()

    return on_startup


def _request_user_from_authorization(authorization: str | None) -> dict[str, str]:
    anonymous = {"user_id": "anonymous", "email": "anonymous"}
    if not authorization:
        return anonymous

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return anonymous

    payload = verify_token(token)
    if not payload:
        return anonymous

    user_id = payload.get("sub")
    if not user_id:
        return anonymous

    return {
        "user_id": str(user_id),
        "email": str(payload.get("username") or "unknown"),
    }


def _request_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _log_api_request(
    request: Request,
    user: dict[str, str],
    started_at: float,
    *,
    status_code: int | str,
    level: str = "info",
    error: Exception | None = None,
) -> None:
    duration_ms = (time.perf_counter() - started_at) * 1000
    message = (
        "API request "
        f"user_id={user['user_id']} "
        f"email={user['email']} "
        f"method={request.method} "
        f"path={request.url.path} "
        f"status_code={status_code} "
        f"client_ip={_request_client_ip(request)} "
        f"duration_ms={duration_ms:.2f} "
        f"user_agent={request.headers.get('user-agent', 'unknown')}"
    )
    log_method = getattr(request_logger, level)
    if error is None:
        log_method(message)
    else:
        log_method(message, exc_info=True)


def _add_request_logging_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def log_api_request(request: Request, call_next):
        started_at = time.perf_counter()
        user = _request_user_from_authorization(request.headers.get("authorization"))
        try:
            response = await call_next(request)
        except Exception as error:
            _log_api_request(
                request,
                user,
                started_at,
                status_code="error",
                level="exception",
                error=error,
            )
            raise

        _log_api_request(request, user, started_at, status_code=response.status_code)
        return response


def create_app(*, settings=None, static_dir: str | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(title="RAG FastAPI", version="0.1.0")
    _add_request_logging_middleware(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(upload_router)
    app.include_router(files_router)
    app.include_router(query_router, prefix="/api")
    app.include_router(sse_router)
    app.include_router(quiz_router, prefix="/quiz")
    app.include_router(tts_router)
    app.include_router(auth_router)
    app.include_router(classes_router)
    app.include_router(exam_router)

    resolved_static_dir = static_dir or _default_static_dir()
    os.makedirs(os.path.join(resolved_static_dir, "pdfs"), exist_ok=True)
    os.makedirs(os.path.join(resolved_static_dir, "images"), exist_ok=True)
    app.mount("/static", StaticFiles(directory=resolved_static_dir), name="static")
    app.add_event_handler('startup', _create_startup_handler())
    return app


app = create_app()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=True)
