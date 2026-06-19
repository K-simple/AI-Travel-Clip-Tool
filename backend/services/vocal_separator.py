"""从模板音频中分离人声与伴奏，供字幕 ASR 使用。"""

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Optional

from services.video_exporter import file_ok, run_cmd
from utils.security import resolve_storage_path

VOCALS_WAV = "template_vocals.wav"
BGM_WAV = "template_bgm.wav"
MIXED_WAV = "template_mixed_stereo.wav"

VOCAL_SEPARATION = os.getenv("VOCAL_SEPARATION", "demucs").strip().lower()


def _template_dir_from_video(video_path: str) -> str:
    resolved = resolve_storage_path(video_path)
    return os.path.dirname(resolved)


def _extract_stereo_wav(video_path: str, output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        resolve_storage_path(video_path),
        "-vn",
        "-ac",
        "2",
        "-ar",
        "44100",
        "-c:a",
        "pcm_s16le",
        output_path,
    ]
    run_cmd(cmd)
    if not file_ok(output_path):
        raise RuntimeError("立体声音频提取失败")
    return output_path


def _resample_for_whisper(source_wav: str, output_path: str) -> str:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        source_wav,
        "-ac",
        "1",
        "-ar",
        "16000",
        "-af",
        "highpass=f=120,lowpass=f=8000,loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:a",
        "pcm_s16le",
        output_path,
    ]
    run_cmd(cmd)
    if not file_ok(output_path):
        raise RuntimeError("人声重采样失败")
    return output_path


def _separate_with_demucs(input_wav: str, work_dir: str) -> tuple[str, str]:
    model = os.getenv("DEMUCS_MODEL", "htdemucs").strip() or "htdemucs"
    out_root = os.path.join(work_dir, f"demucs_out_{uuid.uuid4().hex[:8]}")
    os.makedirs(out_root, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "demucs",
        "--two-stems",
        "vocals",
        "-n",
        model,
        "-o",
        out_root,
        input_wav,
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or "Demucs 人声分离失败")

    stem = Path(input_wav).stem
    base = Path(out_root) / model / stem
    vocals = base / "vocals.wav"
    instrumental = base / "no_vocals.wav"
    if not vocals.is_file():
        raise RuntimeError(f"未找到 Demucs 人声输出: {vocals}")
    if not instrumental.is_file():
        instrumental = vocals
    return str(vocals), str(instrumental)


def _separate_with_ffmpeg(video_path: str, vocals_out: str, bgm_out: str) -> None:
    """无 Demucs 时的轻量方案：中置声道增强 + 高通，并导出伴奏估计轨。"""
    resolved = resolve_storage_path(video_path)
    os.makedirs(os.path.dirname(vocals_out) or ".", exist_ok=True)

    vocal_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        resolved,
        "-vn",
        "-af",
        (
            "pan=mono|c0=0.5*c0+0.5*c1,"
            "highpass=f=200,lowpass=f=3800,"
            "afftdn=nf=-20,acompressor=threshold=-18dB:ratio=3:attack=5:release=50"
        ),
        "-ar",
        "44100",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        vocals_out,
    ]
    run_cmd(vocal_cmd)

    bgm_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        resolved,
        "-vn",
        "-af",
        "pan=mono|c0=0.5*c0-0.5*c1,highpass=f=80,lowpass=f=12000",
        "-ar",
        "44100",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        bgm_out,
    ]
    try:
        run_cmd(bgm_cmd)
    except Exception:
        if os.path.isfile(bgm_out):
            os.remove(bgm_out)

    if not file_ok(vocals_out):
        raise RuntimeError("FFmpeg 人声增强失败")


def ensure_vocal_and_bgm_tracks(
    video_path: str,
    template_dir: Optional[str] = None,
    *,
    force: bool = False,
) -> dict[str, Optional[str]]:
    """
    分离模板人声与 BGM，输出：
    - template_vocals.wav（ASR 主源）
    - template_bgm.wav（伴奏/非人声，可选）
    - template_subtitle_audio.wav（16k 单声道人声，兼容旧逻辑）
    """
    resolved = resolve_storage_path(video_path)
    if not resolved or not os.path.isfile(resolved):
        raise RuntimeError("模板视频不存在")

    work_dir = template_dir or _template_dir_from_video(resolved)
    os.makedirs(work_dir, exist_ok=True)

    vocals_path = os.path.join(work_dir, VOCALS_WAV)
    bgm_path = os.path.join(work_dir, BGM_WAV)
    whisper_path = os.path.join(work_dir, "template_subtitle_audio.wav")

    if not force and file_ok(vocals_path):
        if not file_ok(whisper_path):
            _resample_for_whisper(vocals_path, whisper_path)
        return {
            "vocals": vocals_path,
            "bgm": bgm_path if file_ok(bgm_path) else None,
            "whisper": whisper_path if file_ok(whisper_path) else vocals_path,
        }

    mode = VOCAL_SEPARATION
    mixed_path = os.path.join(work_dir, MIXED_WAV)
    demucs_tmp_vocals: Optional[str] = None
    demucs_tmp_bgm: Optional[str] = None

    try:
        if mode == "demucs":
            try:
                _extract_stereo_wav(resolved, mixed_path)
                demucs_tmp_vocals, demucs_tmp_bgm = _separate_with_demucs(mixed_path, work_dir)
                shutil.copy2(demucs_tmp_vocals, vocals_path)
                shutil.copy2(demucs_tmp_bgm, bgm_path)
                print(f"Demucs 人声分离完成: {vocals_path}")
            except Exception as exc:
                print(f"Demucs 分离失败，回退 FFmpeg 增强: {exc}")
                _separate_with_ffmpeg(resolved, vocals_path, bgm_path)
        elif mode == "off":
            _extract_stereo_wav(resolved, vocals_path)
        else:
            _separate_with_ffmpeg(resolved, vocals_path, bgm_path)
            print(f"FFmpeg 人声增强完成: {vocals_path}")
    finally:
        if os.path.isfile(mixed_path) and mode == "demucs":
            try:
                os.remove(mixed_path)
            except OSError:
                pass
        for name in os.listdir(work_dir):
            if name.startswith("demucs_out_"):
                shutil.rmtree(os.path.join(work_dir, name), ignore_errors=True)

    _resample_for_whisper(vocals_path, whisper_path)

    return {
        "vocals": vocals_path if file_ok(vocals_path) else None,
        "bgm": bgm_path if file_ok(bgm_path) else None,
        "whisper": whisper_path if file_ok(whisper_path) else vocals_path,
    }


def resolve_vocal_source_path(template_file_path: str, *, ensure: bool = False, force: bool = False) -> str:
    """返回最适合 ASR 的人声音频路径。"""
    if not template_file_path:
        return ""

    template_dir = _template_dir_from_video(template_file_path)
    whisper = os.path.join(template_dir, "template_subtitle_audio.wav")
    vocals = os.path.join(template_dir, VOCALS_WAV)

    if ensure or force or not file_ok(vocals):
        try:
            tracks = ensure_vocal_and_bgm_tracks(template_file_path, template_dir, force=force)
            return tracks.get("whisper") or tracks.get("vocals") or ""
        except Exception as exc:
            print(f"人声分离跳过: {exc}")

    if file_ok(whisper):
        return whisper
    if file_ok(vocals):
        return vocals
    return resolve_storage_path(template_file_path)
