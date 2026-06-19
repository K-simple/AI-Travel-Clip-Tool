"""将 CapCut Mate 生成的草稿安装到剪映 PC 草稿目录。"""

import os
import shutil
import subprocess
from typing import Optional

from services.capcut_mate_client import extract_draft_id, normalize_draft_url


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def resolve_capcut_mate_draft_dir() -> str:
    explicit = os.getenv("CAPCUT_MATE_DRAFT_DIR", "").strip()
    if explicit:
        return os.path.abspath(explicit)
    return os.path.join(_project_root(), "capcut-mate", "output", "draft")


def detect_jianying_draft_root() -> Optional[str]:
    explicit = os.getenv("JIANYING_DRAFT_PATH", "").strip()
    if explicit:
        norm = os.path.abspath(explicit)
        return norm if os.path.isdir(norm) else None

    home = os.path.expanduser("~")
    candidate = os.path.join(
        home,
        "AppData",
        "Local",
        "JianyingPro",
        "User Data",
        "Projects",
        "com.lveditor.draft",
    )
    if os.path.isdir(candidate):
        return candidate
    return None


def _trigger_jianying_scan(target_dir: str) -> None:
    """通过 robocopy 触发剪映扫描草稿目录（与 CapCut Mate 一致）。"""
    if os.name != "nt" or not target_dir or not os.path.isdir(target_dir):
        return
    tmp_dir = f"{target_dir}.tmp"
    cmd = [
        "robocopy",
        target_dir,
        tmp_dir,
        "/E",
        "/COPY:DAT",
        "/R:1",
        "/W:1",
        "/NP",
        "/NJH",
        "/NJS",
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=False, encoding="gbk")
    except Exception:
        return
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)


def install_capcut_draft_to_jianying(draft_url: str) -> dict:
    """
    把 CapCut Mate output/draft/{id} 复制到剪映草稿目录，供剪映 PC 识别。
    """
    normalized_url = normalize_draft_url(draft_url)
    draft_id = extract_draft_id(normalized_url)
    if not draft_id:
        raise RuntimeError("无效的剪映草稿链接（缺少 draft_id）")

    source_dir = os.path.join(resolve_capcut_mate_draft_dir(), draft_id)
    if not os.path.isdir(source_dir):
        raise RuntimeError(
            f"本地草稿不存在（{draft_id}）。请确认 CapCut Mate 已启动且导出成功。"
        )

    jianying_root = detect_jianying_draft_root()
    if not jianying_root:
        raise RuntimeError(
            "未找到剪映草稿目录。请安装剪映 PC 版，或在 backend/.env 设置 "
            "JIANYING_DRAFT_PATH（例如 "
            "C:/Users/你的用户名/AppData/Local/JianyingPro/User Data/Projects/com.lveditor.draft）"
        )

    target_dir = os.path.join(jianying_root, draft_id)
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir, ignore_errors=True)
    shutil.copytree(source_dir, target_dir)
    _trigger_jianying_scan(jianying_root)

    return {
        "success": True,
        "draft_id": draft_id,
        "draft_url": normalized_url,
        "installed_path": target_dir.replace("\\", "/"),
        "jianying_draft_root": jianying_root.replace("\\", "/"),
        "message": "草稿已安装到剪映目录，请打开剪映 PC 版在草稿列表中查看",
    }
