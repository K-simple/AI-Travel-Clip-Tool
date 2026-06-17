import os
from pathlib import Path

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

BACKEND_ROOT = Path(__file__).resolve().parent.parent
STORAGE_ROOT = (BACKEND_ROOT / "storage").resolve()

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
API_KEY = os.getenv("API_KEY", "").strip()


def resolve_storage_path(path: str) -> str:
    """Resolve path and ensure it lives under storage/. Raises ValueError if invalid."""
    if not path:
        raise ValueError("文件路径为空")

    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (BACKEND_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(STORAGE_ROOT)
    except ValueError as exc:
        raise ValueError("非法文件路径") from exc

    return str(candidate)


def ensure_storage_subpath(path: str) -> str:
    try:
        return resolve_storage_path(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def validate_upload_file(filename: str | None, size: int) -> str:
    if not filename:
        raise HTTPException(status_code=400, detail="未提供文件名")

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext or '未知'}")

    if size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大，最大允许 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
        )

    return ext


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not API_KEY:
            return await call_next(request)

        if request.url.path in ("/", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)

        if request.url.path.startswith("/storage/"):
            key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
            if key != API_KEY:
                return JSONResponse(status_code=401, content={"detail": "未授权访问存储资源"})
            return await call_next(request)

        if request.url.path.startswith("/api/"):
            key = request.headers.get("X-API-Key")
            if key != API_KEY:
                return JSONResponse(status_code=401, content={"detail": "缺少或无效的 API Key"})

        return await call_next(request)
