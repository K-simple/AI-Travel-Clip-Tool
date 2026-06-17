"""存储抽象：本地 / S3 兼容（Phase D）。默认本地 storage/。"""

import os

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "")


def public_url(relative: str) -> str:
    rel = relative.replace("\\", "/")
    if not rel.startswith("/storage/"):
        if rel.startswith("storage/"):
            rel = "/" + rel
        else:
            rel = f"/storage/{rel.lstrip('/')}"
    return rel


def get_storage_backend() -> str:
    return STORAGE_BACKEND
