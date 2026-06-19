import copy
import os
import subprocess
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from services.subtitle_gen import get_loaded_model_name, normalize_chinese_subtitle, transcribe
from services.vocal_separator import VOCALS_WAV, ensure_vocal_and_bgm_tracks, resolve_vocal_source_path
from utils.security import resolve_storage_path


def _run_ffmpeg(cmd: List[str]) -> None:
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or "ffmpeg 执行失败")


def extract_audio_segment(source_path: str, start: float, end: float, output_path: str) -> None:
    """从模板音频/视频中截取一段，供 Whisper 识别。"""
    resolved = resolve_storage_path(source_path)
    duration = max(0.15, float(end) - float(start))
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(max(0.0, start)),
        "-t",
        str(duration),
        "-i",
        resolved,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-af",
        "highpass=f=80,lowpass=f=8000,loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:a",
        "pcm_s16le",
        output_path,
    ]
    _run_ffmpeg(cmd)

    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError("人声片段截取失败")


def resolve_whisper_source_path(template_file_path: str) -> str:
    """优先使用 16k 人声轨，其次分离人声 wav，最后回退原视频。"""
    if not template_file_path:
        return ""
    template_dir = os.path.dirname(resolve_storage_path(template_file_path))
    whisper_path = os.path.join(template_dir, "template_subtitle_audio.wav")
    vocals_path = os.path.join(template_dir, VOCALS_WAV)

    if whisper_path and os.path.isfile(whisper_path) and os.path.getsize(whisper_path) > 0:
        return whisper_path
    if vocals_path and os.path.isfile(vocals_path) and os.path.getsize(vocals_path) > 0:
        return vocals_path
    return template_file_path


def get_whisper_source_path(template) -> str:
    file_path = getattr(template, "file_path", "") or ""
    return resolve_vocal_source_path(file_path) or resolve_whisper_source_path(file_path)


def slot_dict_source_range(slot: dict) -> tuple[float, float]:
    """槽位在模板源视频/人声上的起止时间。"""
    if slot.get("clip_start") is not None:
        start = float(slot["clip_start"])
        if slot.get("clip_end") is not None:
            end = float(slot["clip_end"])
        elif slot.get("clip_duration") is not None:
            end = start + float(slot["clip_duration"])
        else:
            end = start + float(slot.get("duration") or slot.get("slot_duration") or 0.1)
        return start, max(start + 0.1, end)

    start = float(slot.get("start", slot.get("start_time", slot.get("slot_start", 0))))
    if "end" in slot:
        end = float(slot["end"])
    elif "end_time" in slot:
        end = float(slot["end_time"])
    else:
        end = start + float(slot.get("duration") or slot.get("slot_duration") or 0.1)
    return start, max(start + 0.1, end)


def _normalize_segment_dict(seg: dict[str, Any]) -> Optional[dict[str, Any]]:
    start = float(seg.get("start", 0))
    end = float(seg.get("end", start))
    text = normalize_chinese_subtitle(str(seg.get("text", "")).strip())
    if not text or end <= start:
        return None
    item = {
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(end - start, 3),
        "text": text,
    }
    if isinstance(seg.get("words"), list) and seg["words"]:
        item["words"] = copy.deepcopy(seg["words"])
    if seg.get("style") is not None:
        item["style"] = copy.deepcopy(seg["style"])
    return item


def _words_in_slot_range(
    words: List[dict[str, Any]],
    slot_start: float,
    slot_end: float,
) -> List[str]:
    picked: List[str] = []
    pad = 0.04
    for word in words:
        token = normalize_chinese_subtitle(str(word.get("word", "")).strip())
        if not token:
            continue
        ws = float(word.get("start", 0))
        we = float(word.get("end", ws))
        center = (ws + we) / 2.0
        if center < slot_start - pad or center > slot_end + pad:
            continue
        picked.append(token)
    return picked


def segments_need_rebuild(segments_json: List[Dict[str, Any]], media_duration: float = 0.0) -> bool:
    """检测整段字幕是否异常（例如只有一条覆盖全片）。"""
    if not segments_json:
        return True
    if len(segments_json) == 1 and media_duration > 8:
        seg = segments_json[0]
        seg_start = float(seg.get("start", 0))
        seg_end = float(seg.get("end", seg_start))
        if seg_end - seg_start >= media_duration * 0.65:
            return True
    if media_duration > 8 and len(segments_json) < max(3, int(media_duration / 6)):
        avg = media_duration / max(len(segments_json), 1)
        if avg > 8:
            return True
    if segments_json and not any(isinstance(seg, dict) and seg.get("words") for seg in segments_json):
        return True
    return False


def extract_subtitles_for_slot_range(
    segments_json: List[Dict[str, Any]],
    slot_start: float,
    slot_end: float,
) -> List[Dict[str, Any]]:
    """
    按槽位时间精确切字幕。
    优先用词级时间戳，避免「一条长字幕命中所有槽位」。
    """
    if not segments_json or slot_end <= slot_start:
        return []

    slot_duration = max(0.1, slot_end - slot_start)
    merged_words: List[str] = []

    for raw in segments_json:
        if not isinstance(raw, dict):
            continue
        words = raw.get("words")
        if isinstance(words, list) and words:
            merged_words.extend(_words_in_slot_range(words, slot_start, slot_end))

    if merged_words:
        text = normalize_chinese_subtitle("".join(merged_words))
        if text:
            return [
                {
                    "start": round(slot_start, 3),
                    "end": round(slot_end, 3),
                    "duration": round(slot_duration, 3),
                    "text": text,
                }
            ]

    result: List[Dict[str, Any]] = []
    for raw in segments_json:
        if not isinstance(raw, dict):
            continue
        seg_start = float(raw.get("start", 0))
        seg_end = float(raw.get("end", seg_start))
        if seg_end <= seg_start:
            continue

        overlap_start = max(slot_start, seg_start)
        overlap_end = min(slot_end, seg_end)
        overlap = overlap_end - overlap_start
        if overlap <= 0:
            continue

        seg_duration = seg_end - seg_start
        center = (seg_start + seg_end) / 2.0
        center_in_slot = slot_start <= center <= slot_end
        overlap_ratio_seg = overlap / seg_duration
        overlap_ratio_slot = overlap / slot_duration

        if not center_in_slot and overlap_ratio_seg < 0.55 and overlap_ratio_slot < 0.45:
            continue

        text = normalize_chinese_subtitle(str(raw.get("text", "")).strip())
        if not text:
            continue

        if seg_duration > slot_duration * 1.35 and overlap_ratio_seg < 0.95:
            chars = list(text)
            ratio_start = max(0.0, (overlap_start - seg_start) / seg_duration)
            ratio_end = min(1.0, (overlap_end - seg_start) / seg_duration)
            i0 = int(len(chars) * ratio_start)
            i1 = max(i0 + 1, int(len(chars) * ratio_end))
            text = normalize_chinese_subtitle("".join(chars[i0:i1]))

        if not text:
            continue

        result.append(
            {
                "start": round(overlap_start, 3),
                "end": round(overlap_end, 3),
                "duration": round(overlap_end - overlap_start, 3),
                "text": text,
            }
        )

    return result


# 兼容旧引用
subtitles_for_slot_range = extract_subtitles_for_slot_range


def ensure_template_segments_json(
    template,
    db: Session,
    *,
    force: bool = False,
) -> List[Dict[str, Any]]:
    """整段人声识别并缓存词级时间戳，供各槽位精确切分。"""
    existing = getattr(template, "segments_json", None) or []
    media_duration = float(getattr(template, "duration", 0) or 0)
    if existing and not force and not segments_need_rebuild(existing, media_duration):
        return existing

    if existing and not force and not segments_need_rebuild(existing, media_duration):
        return existing

    video_path = getattr(template, "file_path", "") or ""
    template_dir = os.path.dirname(resolve_storage_path(video_path)) if video_path else ""
    if video_path and template_dir:
        try:
            ensure_vocal_and_bgm_tracks(video_path, template_dir, force=force)
        except Exception as exc:
            print(f"人声分离失败，将使用混合音轨识别: {exc}")

    source_path = resolve_vocal_source_path(video_path) or resolve_whisper_source_path(video_path)
    if not source_path:
        return existing

    print(f"整段字幕识别中（模型 {get_loaded_model_name() or 'loading'}）...")
    raw_segments = transcribe(source_path, clip_mode=False, with_words=True)
    normalized: List[Dict[str, Any]] = []
    for seg in raw_segments:
        item = _normalize_segment_dict(seg)
        if item:
            normalized.append(item)

    if normalized:
        template.segments_json = normalized
        flag_modified(template, "segments_json")
        db.commit()
        db.refresh(template)
        return normalized

    return existing


def recognize_slot_from_source(
    source_path: str,
    slot_start: float,
    slot_end: float,
    segments_json: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """识别槽位字幕：先按时间切整段结果，切不到再对该槽位音频单独识别。"""
    if segments_json:
        sliced = extract_subtitles_for_slot_range(segments_json, slot_start, slot_end)
        if sliced:
            return sliced

    if not source_path:
        raise RuntimeError("模板缺少音频源")

    temp_path = os.path.join("storage", "temp", f"slot_asr_{uuid.uuid4().hex}.wav")
    try:
        extract_audio_segment(source_path, slot_start, slot_end, temp_path)
        raw_segments = transcribe(temp_path, clip_mode=True)

        segments: List[Dict[str, Any]] = []
        for seg in raw_segments:
            start = round(float(seg["start"]) + float(slot_start), 3)
            end = round(float(seg["end"]) + float(slot_start), 3)
            text = normalize_chinese_subtitle(str(seg.get("text", "")).strip())
            if not text or end <= start:
                continue
            segments.append(
                {
                    "start": start,
                    "end": end,
                    "duration": round(end - start, 3),
                    "text": text,
                }
            )
        return segments
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def recognize_slot_from_template(template, slot_start: float, slot_end: float) -> List[Dict[str, Any]]:
    source = get_whisper_source_path(template)
    segments_json = getattr(template, "segments_json", None) or []
    return recognize_slot_from_source(source, slot_start, slot_end, segments_json=segments_json)
