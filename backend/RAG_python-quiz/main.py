from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import os

from app.config import get_settings
from app.services import pg_service
from app.routers.upload import router as upload_router
from app.routers.files_pg import router as files_router
from app.routers.query_stream import router as query_router
from app.routers.sse import router as sse_router
from app.routers.quiz import router as quiz_router
from app.routers.tts import router as tts_router
from app.routers.auth import router as auth_router
from app.routers.classes import router as classes_router
from app.routers.exam import router as exam_router

def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title="RAG FastAPI", version="0.1.0")

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers (/neo4j/* to be compatible with old Express base path)
    app.include_router(upload_router)
    app.include_router(files_router , prefix="/neo4j")
    app.include_router(query_router, prefix="/api")
    app.include_router(sse_router)
    app.include_router(quiz_router , prefix="/quiz")
    app.include_router(tts_router)
    app.include_router(auth_router)
    app.include_router(classes_router)
    app.include_router(exam_router)  # Multi-Agent 考試生成
    # Optional root (keep existing behavior for direct calls)
    app.include_router(query_router)

    # 靜態文件服務 - PDF 和圖片
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    os.makedirs(os.path.join(static_dir, "pdfs"), exist_ok=True)
    os.makedirs(os.path.join(static_dir, "images"), exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.on_event("startup")
    def on_startup():
        pg_service.setup_vector_index()
    return app


app = create_app()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=True)