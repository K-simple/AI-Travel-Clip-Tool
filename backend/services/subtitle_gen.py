import os
import re
import subprocess
from typing import Any

from faster_whisper import WhisperModel

_model = None
_model_name = ""

DEFAULT_INITIAL_PROMPT = "以下是中文旅行短视频旁白，使用规范简体中文和标点。"
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "medium")
WHISPER_MODEL_FALLBACKS = [
    part.strip()
    for part in os.getenv("WHISPER_MODEL_FALLBACKS", "small,base").split(",")
    if part.strip()
]
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "10"))


def normalize_chinese_subtitle(text: str) -> str:
    """清理 Whisper 常见的中文输出问题。"""
    if not text:
        return ""
    text = str(text).strip()
    text = text.replace("\u3000", " ")
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"\s+([，。！？；：、])", r"\1", text)
    text = re.sub(r"([，。！？；：、])\s+", r"\1", text)
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[。\.]{2,}", "。", text)
    return text.strip()


def _audio_duration_seconds(audio_path: str) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        return max(0.0, float((result.stdout or "0").strip() or 0))
    except (TypeError, ValueError, OSError):
        return 0.0


def get_model() -> WhisperModel:
    global _model, _model_name
    if _model is not None:
        return _model

    candidates: list[str] = []
    for name in [WHISPER_MODEL, *WHISPER_MODEL_FALLBACKS]:
        if name and name not in candidates:
            candidates.append(name)

    last_error: Exception | None = None
    for name in candidates:
        try:
            print(f"正在加载 Whisper 模型 ({name})...")
            _model = WhisperModel(name, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
            _model_name = name
            print(f"Whisper 模型加载完成: {name}")
            break
        except Exception as exc:
            last_error = exc
            print(f"Whisper 模型 {name} 加载失败: {exc}")
            _model = None
            _model_name = ""

    if _model is None:
        raise RuntimeError("Whisper 模型加载失败") from last_error
    return _model


def get_loaded_model_name() -> str:
    return _model_name


def transcribe(
    audio_path: str,
    *,
    clip_mode: bool = False,
    initial_prompt: str | None = None,
    with_words: bool = False,
) -> list[dict[str, Any]]:
    """语音识别，返回带时间戳的字幕段落。"""
    model = get_model()
    prompt = (initial_prompt or os.getenv("WHISPER_INITIAL_PROMPT") or DEFAULT_INITIAL_PROMPT).strip()
    duration = _audio_duration_seconds(audio_path)
    short_clip = clip_mode or (0 < duration <= 4.0)
    use_words = with_words and not short_clip

    segments, _ = model.transcribe(
        audio_path,
        language="zh",
        task="transcribe",
        beam_size=WHISPER_BEAM_SIZE,
        best_of=1,
        patience=1.2,
        repetition_penalty=1.15,
        no_repeat_ngram_size=3,
        condition_on_previous_text=not short_clip,
        vad_filter=True,
        vad_parameters={
            "min_silence_duration_ms": 220,
            "speech_pad_ms": 80,
            "threshold": 0.45,
        },
        word_timestamps=use_words,
        initial_prompt=prompt,
        temperature=[0.0, 0.2, 0.35] if short_clip else 0.0,
        compression_ratio_threshold=2.2,
        log_prob_threshold=-1.0,
        no_speech_threshold=0.55,
    )

    result: list[dict[str, Any]] = []
    for seg in segments:
        text = normalize_chinese_subtitle(seg.text)
        if not text:
            continue
        item: dict[str, Any] = {
            "start": round(float(seg.start), 3),
            "end": round(float(seg.end), 3),
            "text": text,
        }
        if use_words and getattr(seg, "words", None):
            words = []
            for word in seg.words:
                token = normalize_chinese_subtitle(getattr(word, "word", ""))
                if not token:
                    continue
                words.append(
                    {
                        "start": round(float(word.start), 3),
                        "end": round(float(word.end), 3),
                        "word": token,
                    }
                )
            if words:
                item["words"] = words
        result.append(item)
    return result


def generate_srt(segments: list, output_path: str) -> str:
    """生成SRT字幕文件"""

    def to_srt_time(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(output_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n")
            f.write(f"{to_srt_time(seg['start'])} --> {to_srt_time(seg['end'])}\n")
            f.write(f"{seg['text']}\n\n")

    return output_path
