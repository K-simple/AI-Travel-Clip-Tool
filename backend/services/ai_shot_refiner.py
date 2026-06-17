"""
DeepSeek V4 辅助镜头切分：修正 PySceneDetect 的误切/漏切。

旅游混剪常见情况：
- 同一场景快切（PySceneDetect 可能合并成一段）
- 闪白/叠化转场（PySceneDetect 可能误切）
"""

import os
import re
import tempfile
from typing import Any

from services.deepseek_client import chat_vision, deepseek_enabled, is_vision_unsupported_error
from services.processing_config import ENABLE_AI_SHOT_REFINE
from services.scene_detector import extract_frame
from services.template_scene_tuning import TemplateSceneTuning, get_template_tuning

_vision_api_available: bool | None = None


def _mark_vision_unavailable(exc: Exception) -> None:
    global _vision_api_available
    if _vision_api_available is False:
        return
    _vision_api_available = False
    print(
        "DeepSeek 视觉 API 不可用，已跳过 AI 镜头修正。"
        "（当前模型不支持 image_url；可在 backend/.env 设置 ENABLE_AI_SHOT_REFINE=0 "
        "或配置支持视觉的 DEEPSEEK_MODEL）"
        f" 原因: {exc}"
    )


def _parse_yes_no(text: str) -> bool | None:
    t = (text or "").strip().lower()
    if not t:
        return None
    if re.search(r"\b(yes|是|同一|相同|same)\b", t):
        return True
    if re.search(r"\b(no|否|不同|not same|different)\b", t):
        return False
    if "同一镜头" in t or "同一场景" in t or "相同画面" in t:
        return True
    if "不同镜头" in t or "不同场景" in t or "不同画面" in t:
        return False
    return None


def _parse_split_times(text: str, seg_start: float, seg_end: float) -> list[float]:
    """从模型回复中提取切分时间点（秒）。"""
    found: list[float] = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:s|秒)?", text):
        t = float(m.group(1))
        if seg_start + 0.2 < t < seg_end - 0.2:
            found.append(round(t, 3))
    return sorted(set(found))


def _same_shot(frame_a: str, frame_b: str) -> bool | None:
    if _vision_api_available is False:
        return None

    prompt = (
        "这是旅游混剪视频里相邻两帧。判断它们是否属于同一镜头/同一画面。"
        "若是同一场景的连续镜头（例如同一地点不同角度但算一个槽位），回答 yes。"
        "若是明显不同的画面/地点/主体，回答 no。"
        "只回答 yes 或 no。"
    )
    try:
        reply = chat_vision(prompt, [frame_a, frame_b], max_tokens=16)
        return _parse_yes_no(reply)
    except Exception as exc:
        if is_vision_unsupported_error(exc):
            _mark_vision_unavailable(exc)
        else:
            print(f"DeepSeek 边界判断失败: {exc}")
        return None


def _find_internal_splits(
    video_path: str,
    seg: dict[str, Any],
    tmp_dir: str,
    *,
    split_min_duration: float,
) -> list[float]:
    """对偏长片段，让 AI 判断内部是否还有切点。"""
    start = float(seg["start"])
    end = float(seg["end"])
    duration = end - start
    if duration < split_min_duration:
        return []

    # 均匀采样 4 帧供模型判断
    sample_times = [
        start + duration * ratio for ratio in (0.15, 0.38, 0.62, 0.85)
    ]
    frame_paths: list[str] = []
    for i, t in enumerate(sample_times):
        out = os.path.join(tmp_dir, f"split_{i}.jpg")
        extract_frame(video_path, t, out)
        frame_paths.append(out)

    prompt = (
        f"这是旅游混剪视频中的一个片段，时间 {start:.2f}s 到 {end:.2f}s，共 {duration:.2f} 秒。"
        "按时间顺序给出了 4 张截图。若其中包含多个不同画面/镜头，请给出切分时间点（秒，相对于整段视频），"
        "用逗号分隔，例如：12.5, 15.8。若只有一个画面，只回答 none。"
    )
    try:
        reply = chat_vision(prompt, frame_paths, max_tokens=64)
    except Exception as exc:
        if is_vision_unsupported_error(exc):
            _mark_vision_unavailable(exc)
        else:
            print(f"DeepSeek 内部分切失败: {exc}")
        return []

    if "none" in reply.lower() or "无" in reply:
        return []
    return _parse_split_times(reply, start, end)


def _merge_segments(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    start = float(a["start"])
    end = float(b["end"])
    merged = dict(a)
    merged.update(
        {
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 3),
            "thumbnail": b.get("thumbnail") or a.get("thumbnail", ""),
        }
    )
    return merged


def _split_segment(
    seg: dict[str, Any], split_times: list[float], *, min_part: float = 0.2
) -> list[dict[str, Any]]:
    if not split_times:
        return [seg]

    start = float(seg["start"])
    end = float(seg["end"])
    bounds = [start, *split_times, end]
    parts: list[dict[str, Any]] = []
    for i in range(len(bounds) - 1):
        s, e = bounds[i], bounds[i + 1]
        dur = e - s
        if dur < min_part:
            continue
        item = dict(seg)
        item.update(
            {
                "start": round(s, 3),
                "end": round(e, 3),
                "duration": round(dur, 3),
                "thumbnail": "",
            }
        )
        parts.append(item)
    return parts or [seg]


def refine_shots_with_ai(
    segments: list[dict[str, Any]],
    video_path: str,
    thumb_dir: str,
    *,
    tuning: TemplateSceneTuning | None = None,
) -> list[dict[str, Any]]:
    """
    用 DeepSeek V4 视觉能力修正镜头边界。
    未配置 API Key 或关闭开关时原样返回。
    """
    if not segments or not ENABLE_AI_SHOT_REFINE or not deepseek_enabled():
        return segments

    if _vision_api_available is False:
        return segments

    cfg = tuning or get_template_tuning()
    split_min = float(cfg.ai_split_min_duration)
    max_checks = int(cfg.ai_max_boundary_checks)
    merge_min_part = max(0.15, float(cfg.min_shot_duration) * 0.6)

    os.makedirs(thumb_dir, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="ai_shot_", dir=thumb_dir)

    try:
        # 1) 合并误切：相邻段边界两帧若同一画面则合并
        merged: list[dict[str, Any]] = [dict(segments[0])]
        checks = 0
        for i, seg in enumerate(segments[1:], start=1):
            if _vision_api_available is False:
                merged.extend(dict(s) for s in segments[i:])
                break

            if checks >= max_checks:
                merged.append(dict(seg))
                continue

            prev = merged[-1]
            t_a = max(float(prev["end"]) - 0.08, float(prev["start"]))
            t_b = min(float(seg["start"]) + 0.08, float(seg["end"]))
            path_a = os.path.join(tmp_dir, f"bound_{checks}_a.jpg")
            path_b = os.path.join(tmp_dir, f"bound_{checks}_b.jpg")
            extract_frame(video_path, t_a, path_a)
            extract_frame(video_path, t_b, path_b)

            same = _same_shot(path_a, path_b)
            checks += 1
            if same is True:
                merged[-1] = _merge_segments(prev, seg)
            else:
                merged.append(dict(seg))

        # 2) 拆分漏切：偏长片段内部再切
        expanded: list[dict[str, Any]] = []
        for seg in merged:
            if _vision_api_available is False:
                expanded = [dict(s) for s in merged]
                break

            splits = _find_internal_splits(
                video_path, seg, tmp_dir, split_min_duration=split_min
            )
            expanded.extend(_split_segment(seg, splits, min_part=merge_min_part))

        for i, seg in enumerate(expanded):
            seg["slot_id"] = i + 1
            seg["segment_id"] = f"seg_{i + 1}"

        print(
            f"AI 镜头修正 [{cfg.profile}]: {len(segments)} -> {len(expanded)} 段 "
            f"(边界检查 {min(checks, max_checks)} 次, split>{split_min}s)"
        )
        return expanded
    except Exception as exc:
        print(f"AI 镜头修正失败，保留原切分: {exc}")
        return segments
