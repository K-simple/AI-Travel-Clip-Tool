"""流式保存上传文件，边接收边写入目标路径。"""

import os

from fastapi import HTTPException, UploadFile

from utils.security import MAX_UPLOAD_BYTES, validate_upload_file

CHUNK_SIZE = 16 * 1024 * 1024


async def save_upload_stream(file: UploadFile, dest_path: str) -> int:
    validate_upload_file(file.filename, 1)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    total = 0
    try:
        with open(dest_path, "wb", buffering=CHUNK_SIZE) as out:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件过大，最大允许 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
                    )
                out.write(chunk)
    except HTTPException:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise
    except Exception as exc:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        print(f"上传落盘失败: {dest_path} -> {exc}")
        raise HTTPException(status_code=500, detail="文件保存失败") from exc

    if total <= 0:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise HTTPException(status_code=400, detail="上传文件为空")

    validate_upload_file(file.filename, total)
    return total
