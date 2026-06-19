"""模板成片级视觉理解：多帧采样 + DeepSeek 生成主题/风格/叙事摘要。"""

import json
import os
import re
from typing import Any

from services.deepseek_client import chat_vision, deepseek_enabled
from services.processing_config import ENABLE_TEMPLATE_VISION, TEMPLATE_VISION_MAX_FRAMES
from services.scene_detector import extract_frame

_TEMPLATE_OVERVIEW_PROMPT = (
    "你是旅游短视频模板分析师。以下按时间顺序给出模板成片的多张截图。"
    "请理解整条模板的核心主题、视觉风格、剪辑节奏，以及用户应如何拍摄素材来替换。"
    '输出严格 JSON（不要 markdown）：{"summary":"20字内模板主题","style":"如清新纪实/电影感/卡点快剪",'
    '"pacing":"慢节奏/中等/快剪","mood":"情绪如轻松/治愈/热血","narrative":"30字内叙事结构",'
    '"replace_guide":"40字内给用户的上传建议"}'
)


def _parse_overview_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}

    if "```" in raw:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if m:
            raw = m.group(1).strip()

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    result: dict[str, Any] = {}
    for key in ("summary", "style", "pacing", "mood", "narrative", "replace_guide"):
        m = re.search(rf'"{key}"\s*:\s*"([^"]+)"', raw)
        if m:
            result[key] = m.group(1).strip()
    return result


def _pick_sample_frames(
    video_path: str,
    thumb_dir: str,
    duration: float,
    slots: list[dict[str, Any]],
    *,
    max_frames: int,
) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()

    for slot in slots or []:
        thumb = str(slot.get("thumbnail") or "").strip()
        if thumb and os.path.isfile(thumb) and thumb not in seen:
            paths.append(thumb)
            seen.add(thumb)
            if len(paths) >= max_frames:
                return paths

    if not video_path or duration <= 0 or not os.path.isfile(video_path):
        return paths

    os.makedirs(thumb_dir, exist_ok=True)
    count = min(max_frames, max(3, int(duration / 5)))
    for i in range(count):
        t = duration * (i + 0.5) / count
        out = os.path.join(thumb_dir, f"vision_sample_{i:02d}.jpg").replace("\\", "/")
        if not os.path.isfile(out):
            try:
                extract_frame(video_path, t, out)
            except Exception:
                continue
        if os.path.isfile(out) and out not in seen:
            paths.append(out)
            seen.add(out)

    return paths[:max_frames]


def analyze_template_overview(
    video_path: str,
    thumb_dir: str,
    duration: float,
    slots: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    理解整条模板成片的视觉主题与替换建议。
    返回 {"summary", "style", "pacing", "mood", "narrative", "replace_guide"}。
    """
    if not ENABLE_TEMPLATE_VISION or not deepseek_enabled():
        return {}

    frames = _pick_sample_frames(
        video_path,
        thumb_dir,
        duration,
        slots,
        max_frames=max(3, TEMPLATE_VISION_MAX_FRAMES),
    )
    if not frames:
        return {}

    slot_hint = f"模板共 {len(slots or [])} 个镜头槽位，时长约 {duration:.1f} 秒。"
    try:
        reply = chat_vision(
            _TEMPLATE_OVERVIEW_PROMPT + slot_hint,
            frames,
            max_tokens=320,
            temperature=0.2,
        )
        parsed = _parse_overview_json(reply)
        if not parsed.get("summary"):
            return {}
        return {
            "summary": str(parsed.get("summary", "")).strip()[:48],
            "style": str(parsed.get("style", "")).strip()[:24],
            "pacing": str(parsed.get("pacing", "")).strip()[:16],
            "mood": str(parsed.get("mood", "")).strip()[:16],
            "narrative": str(parsed.get("narrative", "")).strip()[:64],
            "replace_guide": str(parsed.get("replace_guide", "")).strip()[:80],
        }
    except Exception as exc:
        print(f"模板视觉理解失败: {exc}")
        return {}
