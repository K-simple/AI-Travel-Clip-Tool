"""CapCut Mate（剪映小助手）REST API 客户端。"""

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Optional

CAPCUT_MATE_BASE_URL = os.getenv("CAPCUT_MATE_BASE_URL", "http://localhost:30000").rstrip("/")
CAPCUT_MATE_TIMEOUT_SEC = float(os.getenv("CAPCUT_MATE_TIMEOUT_SEC", "120"))
API_PREFIX = "/openapi/capcut-mate/v1"

_DRAFT_ID_RE = re.compile(r"draft_id=([^&]+)")


def capcut_mate_enabled() -> bool:
    return bool(CAPCUT_MATE_BASE_URL)


def extract_draft_id(draft_url: str) -> str:
    match = _DRAFT_ID_RE.search(draft_url or "")
    return match.group(1) if match else ""


def ping() -> bool:
    """检测 CapCut Mate 是否可访问。"""
    try:
        req = urllib.request.Request(f"{CAPCUT_MATE_BASE_URL}/docs", method="GET")
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception:
        return False


def require_capcut_mate() -> None:
    if not capcut_mate_enabled():
        raise RuntimeError("未配置 CAPCUT_MATE_BASE_URL")
    if not ping():
        raise RuntimeError(
            f"无法连接剪映小助手（{CAPCUT_MATE_BASE_URL}）。"
            "请先启动 CapCut Mate（默认端口 30000），并确认剪映 PC 版已安装。"
        )


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{CAPCUT_MATE_BASE_URL}{API_PREFIX}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=CAPCUT_MATE_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"剪映小助手 API 错误 {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"无法连接剪映小助手（{CAPCUT_MATE_BASE_URL}），请先启动 CapCut Mate 服务"
        ) from exc

    try:
        body_json = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"剪映小助手响应异常: {body[:200]}") from exc

    if not isinstance(body_json, dict):
        raise RuntimeError(f"剪映小助手响应异常: {body_json}")

    if body_json.get("detail"):
        detail = body_json["detail"]
        if isinstance(detail, list):
            detail = "; ".join(str(x) for x in detail)
        raise RuntimeError(str(detail))

    return body_json


def create_draft(width: int, height: int) -> dict[str, Any]:
    return _post("/create_draft", {"width": width, "height": height})


def add_videos(
    draft_url: str,
    video_infos: list[dict[str, Any]],
    *,
    scene_timelines: list[dict[str, int]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "draft_url": draft_url,
        "video_infos": json.dumps(video_infos, ensure_ascii=False),
    }
    if scene_timelines:
        payload["scene_timelines"] = scene_timelines
    resp = _post("/add_videos", payload)
    video_ids = resp.get("video_ids") or []
    if not video_ids:
        raise RuntimeError(
            "剪映小助手未成功写入视频轨道（video_ids 为空）。"
            "请检查 PUBLIC_MEDIA_BASE_URL 是否可被小助手访问，以及 /storage 是否需 api_key。"
        )
    return resp


def add_audios(draft_url: str, audio_infos: list[dict[str, Any]]) -> dict[str, Any]:
    return _post(
        "/add_audios",
        {
            "draft_url": draft_url,
            "audio_infos": json.dumps(audio_infos, ensure_ascii=False),
        },
    )


def add_captions(
    draft_url: str,
    captions: list[dict[str, Any]],
    *,
    text_color: str = "#ffffff",
    font_size: int = 18,
    alignment: int = 1,
    transform_y: int = -400,
) -> dict[str, Any]:
    return _post(
        "/add_captions",
        {
            "draft_url": draft_url,
            "captions": json.dumps(captions, ensure_ascii=False),
            "text_color": text_color,
            "font_size": font_size,
            "alignment": alignment,
            "transform_y": transform_y,
        },
    )


def save_draft(draft_url: str) -> dict[str, Any]:
    return _post("/save_draft", {"draft_url": draft_url})


def get_draft_files(draft_id: str) -> list[str]:
    if not draft_id:
        return []
    url = f"{CAPCUT_MATE_BASE_URL}{API_PREFIX}/get_draft?draft_id={draft_id}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=CAPCUT_MATE_TIMEOUT_SEC) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        files = body.get("files") if isinstance(body, dict) else []
        return list(files) if isinstance(files, list) else []
    except Exception:
        return []
