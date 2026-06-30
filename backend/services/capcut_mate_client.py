"""CapCut Mate（剪映小助手）REST API 客户端。"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from utils.public_media import ensure_http_video_url, resolve_public_media_base


def normalize_capcut_base_url(url: str) -> str:
    """Windows 上 localhost 常解析为 IPv6 ::1，而 CapCut Mate 默认只监听 IPv4。"""
    normalized = (url or "").strip().rstrip("/")
    normalized = normalized.replace("://localhost", "://127.0.0.1")
    normalized = normalized.replace("://[::1]", "://127.0.0.1")
    return normalized


CAPCUT_MATE_BASE_URL = normalize_capcut_base_url(
    os.getenv("CAPCUT_MATE_BASE_URL", "http://127.0.0.1:30000")
)
CAPCUT_MATE_TIMEOUT_SEC = float(os.getenv("CAPCUT_MATE_TIMEOUT_SEC", "600"))
API_PREFIX = "/openapi/capcut-mate/v1"

_DRAFT_ID_RE = re.compile(r"draft_id=([^&]+)")


def capcut_mate_enabled() -> bool:
    return bool(CAPCUT_MATE_BASE_URL)


def extract_draft_id(draft_url: str) -> str:
    match = _DRAFT_ID_RE.search(draft_url or "")
    return match.group(1) if match else ""


def normalize_draft_url(draft_url: str) -> str:
    """将 CapCut Mate 返回的云端 draft_url 规范为本地小助手地址。"""
    draft_id = extract_draft_id(draft_url)
    if not draft_id:
        return draft_url or ""
    return f"{CAPCUT_MATE_BASE_URL}{API_PREFIX}/get_draft?draft_id={draft_id}"


def ping() -> bool:
    """检测 CapCut Mate 是否可访问。"""
    try:
        req = urllib.request.Request(f"{CAPCUT_MATE_BASE_URL}/openapi.json", method="GET")
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


def _capcut_timeout_for_clips(clip_count: int = 1) -> float:
    """按片段数量放宽超时，避免 add_videos 拉取多段素材时过早中断。"""
    clip_count = max(1, clip_count)
    return max(CAPCUT_MATE_TIMEOUT_SEC, 90 + clip_count * 25)


def _post(path: str, payload: dict[str, Any], *, timeout_sec: float | None = None) -> dict[str, Any]:
    url = f"{CAPCUT_MATE_BASE_URL}{API_PREFIX}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = timeout_sec if timeout_sec is not None else CAPCUT_MATE_TIMEOUT_SEC
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"剪映小助手 API 错误 {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if "timed out" in str(reason).lower():
            raise RuntimeError(
                f"剪映小助手请求超时（>{int(timeout)}s）。"
                "槽位较多时可增大 backend/.env 的 CAPCUT_MATE_TIMEOUT_SEC 后重启后端。"
            ) from exc
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

    code = body_json.get("code")
    if code is not None:
        try:
            code_int = int(code)
        except (TypeError, ValueError):
            code_int = -1
        if code_int != 0:
            message = body_json.get("message") or f"剪映小助手返回错误 code={code}"
            raise RuntimeError(str(message))

    return body_json


def create_draft(width: int, height: int) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            if attempt > 0:
                require_capcut_mate()
                time.sleep(1.5 * attempt)
            resp = _post("/create_draft", {"width": width, "height": height})
            draft_url = (resp.get("draft_url") or "").strip()
            if not draft_url:
                raise RuntimeError("剪映小助手未返回 draft_url")
            return resp
        except RuntimeError as exc:
            last_error = exc
            msg = str(exc)
            retryable = any(
                token in msg
                for token in (
                    "无法连接剪映小助手",
                    "请求超时",
                    "Connection refused",
                    "timed out",
                )
            )
            if not retryable or attempt >= 2:
                raise
    if last_error:
        raise last_error
    raise RuntimeError("剪映草稿创建失败")


ADD_VIDEOS_BATCH_SIZE = int(os.getenv("CAPCUT_ADD_VIDEOS_BATCH_SIZE", "9999"))


def add_videos(
    draft_url: str,
    video_infos: list[dict[str, Any]],
    *,
    scene_timelines: list[dict[str, int]] | None = None,
    on_batch: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    if not video_infos:
        raise RuntimeError("没有可写入剪映草稿的视频片段")

    batch_size = max(1, ADD_VIDEOS_BATCH_SIZE)
    all_video_ids: list[Any] = []
    last_resp: dict[str, Any] = {}
    total_batches = max(1, (len(video_infos) + batch_size - 1) // batch_size)
    done_batches = 0

    for start in range(0, len(video_infos), batch_size):
        batch_videos = video_infos[start : start + batch_size]
        batch_scenes = None
        if scene_timelines and len(scene_timelines) == len(video_infos):
            batch_scenes = scene_timelines[start : start + batch_size]

        media_base = resolve_public_media_base()
        sanitized_batch = []
        for item in batch_videos:
            entry = dict(item)
            entry["video_url"] = ensure_http_video_url(
                str(entry.get("video_url") or ""), media_base
            )
            sanitized_batch.append(entry)

        payload: dict[str, Any] = {
            "draft_url": draft_url,
            "video_infos": json.dumps(sanitized_batch, ensure_ascii=False),
        }
        if batch_scenes:
            payload["scene_timelines"] = batch_scenes

        timeout = _capcut_timeout_for_clips(len(batch_videos))
        resp = _post("/add_videos", payload, timeout_sec=timeout)
        draft_url = resp.get("draft_url") or draft_url
        video_ids = resp.get("video_ids") or []
        if not video_ids:
            raise RuntimeError(
                "剪映小助手未成功写入视频轨道（video_ids 为空）。"
                "请检查 PUBLIC_MEDIA_BASE_URL 是否可被小助手访问，以及 /storage 是否需 api_key。"
            )
        all_video_ids.extend(video_ids)
        last_resp = resp
        done_batches += 1
        if on_batch:
            on_batch(done_batches, total_batches)

    return {**last_resp, "draft_url": draft_url, "video_ids": all_video_ids}


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
    border_color: str | None = None,
    font_size: int = 18,
    alignment: int = 1,
    transform_y: int = -400,
    bold: bool = False,
    text_effect: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "draft_url": draft_url,
        "captions": json.dumps(captions, ensure_ascii=False),
        "text_color": text_color,
        "font_size": font_size,
        "alignment": alignment,
        "transform_y": transform_y,
    }
    if border_color:
        payload["border_color"] = border_color
    if bold:
        payload["bold"] = True
    if text_effect:
        payload["text_effect"] = text_effect
    return _post("/add_captions", payload)


def save_draft(draft_url: str, *, clip_count: int = 1) -> dict[str, Any]:
    return _post(
        "/save_draft",
        {"draft_url": draft_url},
        timeout_sec=_capcut_timeout_for_clips(clip_count),
    )


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
