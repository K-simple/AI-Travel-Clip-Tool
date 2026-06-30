import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent
load_dotenv(BACKEND_ROOT / ".env", override=True)
os.chdir(BACKEND_ROOT)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from models.database import init_db
from utils.security import ApiKeyMiddleware

for sub in ("templates", "assets", "thumbnails", "exports", "temp"):
    os.makedirs(BACKEND_ROOT / "storage" / sub, exist_ok=True)

init_db()

app = FastAPI(title="AI Travel Cut Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ApiKeyMiddleware)

app.mount("/storage", StaticFiles(directory=str(BACKEND_ROOT / "storage")), name="storage")

from routers import (  # noqa: E402
    assets,
    auth,
    cloud,
    effects,
    export,
    marketplace,
    match,
    project,
    publish,
    subtitle,
    template,
    template_library,
)

app.include_router(template.router, prefix="/api/template", tags=["template"])
app.include_router(template_library.router, prefix="/api/template-library", tags=["template-library"])
app.include_router(assets.router, prefix="/api/assets", tags=["assets"])
app.include_router(match.router, prefix="/api/match", tags=["match"])
app.include_router(subtitle.router, prefix="/api/subtitle", tags=["subtitle"])
app.include_router(export.router, prefix="/api/export", tags=["export"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(project.router, prefix="/api/projects", tags=["projects"])
app.include_router(effects.router, prefix="/api/effects", tags=["effects"])
app.include_router(cloud.router, prefix="/api/cloud", tags=["cloud"])
app.include_router(marketplace.router, prefix="/api/marketplace", tags=["marketplace"])
app.include_router(publish.router, prefix="/api/publish", tags=["publish"])


@app.on_event("startup")
def _warm_subtitle_models() -> None:
    """后台预加载 OCR，避免首次识别冷启动过慢。"""
    if os.getenv("SUBTITLE_PRELOAD", "1").strip() in ("0", "false", "no"):
        return

    def _load() -> None:
        try:
            from services.subtitle_ocr import preload_ocr_reader

            preload_ocr_reader()
        except Exception as exc:
            print(f"字幕 OCR 预加载跳过: {exc}")

    import threading

    threading.Thread(target=_load, daemon=True).start()


@app.get("/")
def root():
    return {"message": "AI Travel Cut backend is running"}


@app.get("/health")
def health():
    from services.processing_config import (
        FRAME_EXTRACT_WORKERS,
        PROCESSING_PRESET,
        SEGMENT_CUT_WORKERS,
        SUBTITLE_BATCH_WORKERS,
        SUBTITLE_OCR_WORKERS,
        TASK_QUEUE_WORKERS,
    )
    from services.resource_profile import profile_summary
    from services.subtitle_gen import get_loaded_model_name

    return {
        "status": "ok",
        "preset": PROCESSING_PRESET,
        "hardware": profile_summary(),
        "workers": {
            "subtitle_ocr": SUBTITLE_OCR_WORKERS,
            "subtitle_batch": SUBTITLE_BATCH_WORKERS,
            "task_queue": TASK_QUEUE_WORKERS,
            "frame_extract": FRAME_EXTRACT_WORKERS,
            "segment_cut": SEGMENT_CUT_WORKERS,
        },
        "models": {
            "whisper_configured": os.getenv("WHISPER_MODEL", "medium"),
            "whisper_loaded": get_loaded_model_name() or None,
        },
        "capabilities": {
            "deepseek": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
            "capcut_mate": bool(os.getenv("CAPCUT_MATE_BASE_URL", "http://localhost:30000").strip()),
            "auth": bool(os.getenv("AUTH_SECRET", "").strip()),
            "douyin_publish": bool(
                os.getenv("DOUYIN_CLIENT_KEY", "").strip()
                and os.getenv("DOUYIN_CLIENT_SECRET", "").strip()
            ),
        },
    }
