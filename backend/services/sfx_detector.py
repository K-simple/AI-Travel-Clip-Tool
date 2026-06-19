"""音效点位检测与 BGM 节拍分析（librosa）。"""

import json
import os
import subprocess
from typing import Any

import numpy as np

from services.processing_config import (
    ENABLE_SFX_DETECTION,
    SFX_BEAT_TOLERANCE_SEC,
    SFX_MIN_ENERGY,
    SFX_MIN_INTERVAL_SEC,
)

_SFX_TYPE_RULES = (
    ({"whoosh", "swoosh"}, lambda c, e, d: c > 2800 and d < 0.45),
    ({"ding", "click"}, lambda c, e, d: c > 1800 and e > 0.06 and d < 0.35),
    ({"impact", "thump"}, lambda c, e, d: c < 1200 and e > 0.05),
    ({"swoosh"}, lambda c, e, d: c > 2200),
)


def _load_audio(audio_path: str) -> tuple[np.ndarray, int]:
    try:
        import librosa

        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        return y, sr
    except ImportError:
        pass

    # FFmpeg 回退：导出 mono wav 后用 numpy 读取
    import wave

    temp_wav = audio_path + ".mono.tmp.wav"
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-ac", "1", "-ar", "22050", "-f", "wav", temp_wav,
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=False)
    if not os.path.isfile(temp_wav):
        raise RuntimeError("无法读取音频，请安装 librosa 或确保 ffmpeg 可用")

    with wave.open(temp_wav, "rb") as wf:
        sr = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        y = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    try:
        os.remove(temp_wav)
    except OSError:
        pass
    return y, sr


def _estimate_sfx_duration(y: np.ndarray, sr: int, center_time: float) -> float:
    idx = int(center_time * sr)
    window = 882  # ~40ms
    half = len(y) // 2
    start = max(0, idx - half)
    end = min(len(y), idx + half)
    segment = y[start:end]
    if len(segment) < window:
        return 0.15

    energy = np.array([
        float(np.sqrt(np.mean(segment[i : i + window] ** 2)))
        for i in range(0, len(segment) - window, window // 2)
    ])
    if len(energy) == 0:
        return 0.15

    peak = float(energy.max())
    if peak <= 1e-6:
        return 0.15

    threshold = peak * 0.35
    active = energy >= threshold
    active_count = int(np.sum(active))
    return round(min(0.6, max(0.08, active_count * (window / 2) / sr)), 3)


def _classify_sfx(centroid: float, energy: float, duration: float) -> str:
    for labels, rule in _SFX_TYPE_RULES:
        if rule(centroid, energy, duration):
            return next(iter(labels))
    return "sfx"


def _simple_onsets(y: np.ndarray, sr: int) -> np.ndarray:
    """无 librosa 时的简易 onset。"""
    hop = 512
    frame_len = 2048
    energies = []
    for i in range(0, len(y) - frame_len, hop):
        chunk = y[i : i + frame_len]
        energies.append(float(np.sqrt(np.mean(chunk ** 2))))
    if not energies:
        return np.array([])

    e = np.array(energies)
    diff = np.diff(e, prepend=e[0])
    threshold = float(np.percentile(diff, 92))
    peaks = np.where(diff >= threshold)[0]
    times = peaks * hop / sr
    return times


def detect_beats_from_audio(audio_path: str) -> list[float]:
    if not audio_path or not os.path.isfile(audio_path):
        return []

    y, sr = _load_audio(audio_path)
    try:
        import librosa

        _tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        return [round(float(t), 3) for t in beat_times if t >= 0]
    except ImportError:
        duration = len(y) / sr
        bpm = 118.0
        interval = 60.0 / bpm
        markers = []
        t = 0.0
        while t < duration:
            markers.append(round(t, 3))
            t += interval
        return markers


def detect_sfx_markers(
    audio_path: str,
    duration: float | None = None,
    *,
    beat_times: list[float] | None = None,
) -> list[dict[str, Any]]:
    """检测非节拍的短促音效点位。"""
    if not ENABLE_SFX_DETECTION or not audio_path or not os.path.isfile(audio_path):
        return []

    y, sr = _load_audio(audio_path)
    if duration is None:
        duration = len(y) / sr

    beats = beat_times if beat_times is not None else detect_beats_from_audio(audio_path)

    try:
        import librosa

        onset_frames = librosa.onset.onset_detect(y=y, sr=sr, backtrack=True, delta=0.06)
        onset_times = librosa.frames_to_time(onset_frames, sr=sr)
    except ImportError:
        onset_times = _simple_onsets(y, sr)

    markers: list[dict[str, Any]] = []
    beat_tol = SFX_BEAT_TOLERANCE_SEC

    for ot in onset_times:
        t = float(ot)
        if t < 0 or t > duration:
            continue

        near_beat = any(abs(t - bt) < beat_tol for bt in beats)
        if near_beat:
            continue

        idx = int(t * sr)
        w0 = max(0, idx - int(sr * 0.05))
        w1 = min(len(y), idx + int(sr * 0.25))
        window = y[w0:w1]
        if len(window) < 64:
            continue

        energy = float(np.sqrt(np.mean(window ** 2)))
        if energy < SFX_MIN_ENERGY:
            continue

        try:
            import librosa

            centroid = float(librosa.feature.spectral_centroid(y=window, sr=sr).mean())
        except ImportError:
            centroid = 1500.0

        dur = _estimate_sfx_duration(y, sr, t)
        sfx_type = _classify_sfx(centroid, energy, dur)

        markers.append({
            "time": round(t, 3),
            "duration": dur,
            "type": sfx_type,
            "confidence": round(min(0.95, 0.45 + energy * 4), 2),
            "energy": round(energy, 3),
            "volume": 0.85,
        })

    markers.sort(key=lambda m: m["time"])

    deduped: list[dict[str, Any]] = []
    for m in markers:
        if deduped and m["time"] - deduped[-1]["time"] < SFX_MIN_INTERVAL_SEC:
            if m["energy"] > deduped[-1]["energy"]:
                deduped[-1] = m
        else:
            deduped.append(m)

    print(f"音效检测完成: {len(deduped)} 个点位")
    return deduped


def extract_sfx_clips(
    audio_path: str,
    sfx_markers: list[dict[str, Any]],
    output_dir: str,
) -> list[dict[str, Any]]:
    """为每个音效点位裁剪独立音频片段，写入 clip_path。"""
    if not sfx_markers or not audio_path or not os.path.isfile(audio_path):
        return sfx_markers

    os.makedirs(output_dir, exist_ok=True)
    enriched: list[dict[str, Any]] = []

    for index, marker in enumerate(sfx_markers):
        item = dict(marker)
        t = float(item["time"])
        dur = float(item.get("duration") or 0.2)
        pad = min(0.04, dur * 0.25)
        start = max(0.0, t - pad)
        clip_dur = min(0.8, dur + pad * 2)

        out_name = f"sfx_{index:03d}_{item.get('type', 'sfx')}.m4a"
        out_path = os.path.join(output_dir, out_name).replace("\\", "/")

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-t", str(clip_dur),
            "-i", audio_path,
            "-vn", "-ac", "1", "-ar", "44100",
            "-c:a", "aac", "-b:a", "128k",
            out_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0 and os.path.isfile(out_path):
            item["clip_path"] = out_path
            item["clip_start"] = round(start, 3)
            item["clip_duration"] = round(clip_dur, 3)

        enriched.append(item)

    return enriched


def analyze_template_audio(
    audio_path: str,
    duration: float,
    template_dir: str,
) -> dict[str, Any]:
    """节拍 + 音效检测 + 音效片段裁剪。"""
    if not ENABLE_SFX_DETECTION or not audio_path or not os.path.isfile(audio_path):
        return {"beat_markers": [], "sfx_markers": []}

    beat_markers = detect_beats_from_audio(audio_path)
    sfx_markers = detect_sfx_markers(audio_path, duration, beat_times=beat_markers)

    sfx_dir = os.path.join(template_dir, "sfx_clips")
    sfx_markers = extract_sfx_clips(audio_path, sfx_markers, sfx_dir)

    manifest_path = os.path.join(template_dir, "sfx_manifest.json").replace("\\", "/")
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"beat_markers": beat_markers, "sfx_markers": sfx_markers}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

    return {"beat_markers": beat_markers, "sfx_markers": sfx_markers}
