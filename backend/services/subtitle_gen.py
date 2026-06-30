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
WHISPER_BATCH_BEAM_SIZE = int(os.getenv("WHISPER_BATCH_BEAM_SIZE", "1"))
WHISPER_QUALITY_BEAM_SIZE = int(os.getenv("WHISPER_QUALITY_BEAM_SIZE", "5"))


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
    fast_batch: bool = False,
) -> list[dict[str, Any]]:
    """语音识别，返回带时间戳的字幕段落。"""
    model = get_model()
    prompt = (initial_prompt or os.getenv("WHISPER_INITIAL_PROMPT") or DEFAULT_INITIAL_PROMPT).strip()
    duration = _audio_duration_seconds(audio_path)
    short_clip = clip_mode or (0 < duration <= 4.0)
    use_words = with_words and not short_clip
    # 短槽位单独识别时不带整片旁白 prompt，避免每段都 hallucinate 成同一句开头
    if short_clip and initial_prompt is None:
        prompt = ""

    beam_size = WHISPER_BATCH_BEAM_SIZE if fast_batch else WHISPER_QUALITY_BEAM_SIZE

    segments, _ = model.transcribe(
        audio_path,
        language="zh",
        task="transcribe",
        beam_size=beam_size,
        best_of=1,
        patience=0.8 if fast_batch else 1.2,
        repetition_penalty=1.15,
        no_repeat_ngram_size=3,
        condition_on_previous_text=not short_clip and not fast_batch,
        vad_filter=True,
        vad_parameters={
            "min_silence_duration_ms": 220,
            "speech_pad_ms": 80,
            "threshold": 0.45,
        },
        word_timestamps=use_words,
        initial_prompt=prompt or None,
        temperature=0.0 if fast_batch else ([0.0, 0.2, 0.35] if short_clip else 0.0),
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
        if getattr(seg, "avg_logprob", None) is not None:
            item["avg_logprob"] = round(float(seg.avg_logprob), 4)
        if getattr(seg, "no_speech_prob", None) is not None:
            item["no_speech_prob"] = round(float(seg.no_speech_prob), 4)
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


def transcribe_speech(
    audio_path: str,
    *,
    language: str = "zh",
    config=None,
) -> list[dict[str, Any]]:
    """口播 ASR：优化参数，减少 BGM 幻听与上下文串台。"""
    from services.subtitle_config import SubtitleConfig, get_subtitle_config

    cfg: SubtitleConfig = config or get_subtitle_config()
    model = get_model()

    beam_size = max(1, int(cfg.whisper_beam_size))
    use_vad = bool(cfg.enable_vad)

    base_kwargs: dict[str, Any] = {
        "language": language or cfg.language or "zh",
        "task": "transcribe",
        "beam_size": beam_size,
        "best_of": 1,
        "patience": 1.0,
        "repetition_penalty": 1.2,
        "no_repeat_ngram_size": 3,
        "condition_on_previous_text": False,
        "vad_filter": use_vad,
        "initial_prompt": None,
        "temperature": 0.0,
        "compression_ratio_threshold": float(cfg.compression_ratio_threshold),
        "log_prob_threshold": float(cfg.log_prob_threshold),
        "no_speech_threshold": float(cfg.no_speech_threshold),
    }
    if use_vad:
        base_kwargs["vad_parameters"] = {
            "min_silence_duration_ms": 280,
            "speech_pad_ms": 120,
            "threshold": 0.5,
        }

    segments = None
    info = None
    word_ts = True
    for attempt in range(2):
        try:
            kwargs = dict(base_kwargs)
            if word_ts:
                kwargs["word_timestamps"] = True
            segments, info = model.transcribe(audio_path, **kwargs)
            break
        except TypeError as exc:
            msg = str(exc).lower()
            if word_ts and "word_timestamps" in msg:
                print("[speech][asr] word_timestamps 不支持，fallback 关闭")
                word_ts = False
                continue
            if attempt == 0:
                print(f"[speech][asr] 参数兼容 fallback: {exc}")
                base_kwargs.pop("repetition_penalty", None)
                base_kwargs.pop("no_repeat_ngram_size", None)
                continue
            raise
        except Exception as exc:
            if attempt == 0:
                print(f"[speech][asr] 首次 transcribe 失败，简化参数重试: {exc}")
                base_kwargs.pop("repetition_penalty", None)
                base_kwargs.pop("no_repeat_ngram_size", None)
                word_ts = False
                continue
            raise

    if segments is None:
        raise RuntimeError("Whisper transcribe 失败")

    result: list[dict[str, Any]] = []
    seg_index = 0
    for seg in segments:
        text = normalize_chinese_subtitle(seg.text)
        if not text:
            continue
        seg_index += 1
        start = round(float(seg.start), 3)
        end = round(float(seg.end), 3)
        if end <= start:
            end = round(start + 0.08, 3)

        avg_logprob = getattr(seg, "avg_logprob", None)
        no_speech_prob = getattr(seg, "no_speech_prob", None)
        compression_ratio = getattr(seg, "compression_ratio", None)

        confidence = 0.55
        if avg_logprob is not None:
            confidence = max(0.0, min(1.0, 1.0 + float(avg_logprob) * 0.35))
        if no_speech_prob is not None:
            confidence *= max(0.0, 1.0 - float(no_speech_prob))

        item: dict[str, Any] = {
            "id": f"subtitle_{seg_index}",
            "start": start,
            "end": end,
            "duration": round(end - start, 3),
            "text": text,
            "source": "asr",
            "type": "spoken_caption",
            "confidence": round(confidence, 3),
            "debug": {
                "avg_logprob": round(float(avg_logprob), 4) if avg_logprob is not None else None,
                "no_speech_prob": round(float(no_speech_prob), 4) if no_speech_prob is not None else None,
                "compression_ratio": round(float(compression_ratio), 4) if compression_ratio is not None else None,
                "engine": "faster-whisper",
                "vad_used": use_vad,
                "word_timestamps": word_ts,
            },
        }
        if word_ts and getattr(seg, "words", None):
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

    _ = info
    print(f"[speech][asr] vad={use_vad} word_ts={word_ts} segments={len(result)}")
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
