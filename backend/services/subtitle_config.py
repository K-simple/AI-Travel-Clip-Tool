"""字幕识别配置（口播 speech 优先）。"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field


def _bool(key: str, default: str = "1") -> bool:
    return os.getenv(key, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class SubtitleConfig:
    mode: str = "speech"  # speech | burned | auto
    enable_audio_enhance: bool = True
    enable_vocal_isolation: bool = False
    enable_vad: bool = True
    enable_ocr_assist: bool = False
    enable_screen_text: bool = False
    asr_engine: str = "whisper"
    language: str = "zh"
    max_chars_per_line: int = 16
    max_lines: int = 2
    min_segment_duration: float = 0.6
    max_segment_duration: float = 6.0
    filter_low_confidence: bool = True
    min_confidence: float = 0.35
    whisper_beam_size: int = 5
    no_speech_threshold: float = 0.6
    compression_ratio_threshold: float = 2.0
    log_prob_threshold: float = -1.0
    slot_padding_sec: float = 0.2
    min_overlap_sec: float = 0.15
    min_segment_overlap_ratio: float = 0.15
    min_slot_overlap_ratio: float = 0.10
    slot_word_padding_sec: float = 0.15
    assign_by_word_midpoint: bool = True
    prevent_duplicate_slot_text: bool = True
    clip_min_duration: float = 0.8
    clip_max_duration: float = 4.5
    clip_target_duration: float = 2.2
    clip_max_chars: int = 22
    clip_min_chars: int = 4
    clip_max_lines: int = 2
    clip_max_chars_per_line: int = 16
    clip_pause_threshold_sec: float = 0.35
    clip_merge_gap_sec: float = 0.25
    clip_use_word_timestamps: bool = True
    # 切槽策略：visual | speech | hybrid | caption_slot | sentence
    cut_strategy: str = "caption_slot"
    material_fill_strategy: str = "fit_caption_slots"
    caption_slot_min_duration: float = 0.8
    caption_slot_max_duration: float = 5.0
    caption_slot_target_duration: float = 2.5
    caption_slot_max_chars: int = 28
    caption_slot_min_chars: int = 4
    caption_slot_merge_gap_sec: float = 0.25
    caption_slot_use_ocr_text: bool = False
    caption_slot_use_asr_time: bool = True
    caption_slot_ocr_asr_sim_threshold: float = 0.55
    caption_slot_ocr_subtitle_score_threshold: float = 0.65
    # ASR 主、OCR 校验：用画面硬字幕验证切句边界与文本
    caption_ocr_validate: bool = True
    caption_ocr_validate_split: bool = True
    caption_ocr_validate_merge: bool = True
    caption_ocr_text_correct_threshold: float = 0.82
    caption_ocr_mismatch_review_threshold: float = 0.45
    caption_ocr_overlap_min_ratio: float = 0.18

    def to_dict(self) -> dict:
        return asdict(self)


def is_caption_slot_strategy(strategy: str | None = None) -> bool:
    raw = (strategy or os.getenv("CUT_STRATEGY", "caption_slot")).strip().lower()
    return raw in ("caption_slot", "sentence")


def caption_slot_clip_config(cfg: SubtitleConfig | None = None) -> SubtitleConfig:
    """caption_slot 模式下切句参数映射到 clip_*。"""
    base = cfg or get_subtitle_config()
    if not is_caption_slot_strategy(base.cut_strategy):
        return base
    return SubtitleConfig(
        **{
            **base.to_dict(),
            "clip_min_duration": base.caption_slot_min_duration,
            "clip_max_duration": base.caption_slot_max_duration,
            "clip_target_duration": base.caption_slot_target_duration,
            "clip_max_chars": base.caption_slot_max_chars,
            "clip_min_chars": base.caption_slot_min_chars,
            "clip_merge_gap_sec": base.caption_slot_merge_gap_sec,
        }
    )


def get_subtitle_config() -> SubtitleConfig:
    return SubtitleConfig(
        mode=os.getenv("SUBTITLE_MODE", "speech").strip().lower() or "speech",
        enable_audio_enhance=_bool("SUBTITLE_ENABLE_AUDIO_ENHANCE", "1"),
        enable_vocal_isolation=_bool("SUBTITLE_ENABLE_VOCAL_ISOLATION", "0"),
        enable_vad=_bool("SUBTITLE_ENABLE_VAD", "1"),
        enable_ocr_assist=_bool("SUBTITLE_ENABLE_OCR_ASSIST", "0"),
        enable_screen_text=_bool("SUBTITLE_ENABLE_SCREEN_TEXT", "0"),
        asr_engine=os.getenv("SUBTITLE_ASR_ENGINE", "whisper").strip().lower() or "whisper",
        language=os.getenv("SUBTITLE_ASR_LANGUAGE", "zh").strip().lower() or "zh",
        max_chars_per_line=int(os.getenv("SUBTITLE_MAX_CHARS_PER_LINE", "16")),
        max_lines=int(os.getenv("SUBTITLE_MAX_LINES", "2")),
        min_segment_duration=float(os.getenv("SUBTITLE_MIN_SEGMENT_DURATION", "0.6")),
        max_segment_duration=float(os.getenv("SUBTITLE_MAX_SEGMENT_DURATION", "6.0")),
        filter_low_confidence=_bool("SUBTITLE_FILTER_LOW_CONFIDENCE", "1"),
        min_confidence=float(os.getenv("SUBTITLE_MIN_CONFIDENCE", "0.35")),
        whisper_beam_size=int(os.getenv("SUBTITLE_SPEECH_BEAM_SIZE", "5")),
        no_speech_threshold=float(os.getenv("SUBTITLE_NO_SPEECH_THRESHOLD", "0.6")),
        compression_ratio_threshold=float(os.getenv("SUBTITLE_COMPRESSION_RATIO_THRESHOLD", "2.0")),
        log_prob_threshold=float(os.getenv("SUBTITLE_LOG_PROB_THRESHOLD", "-1.0")),
        slot_padding_sec=float(os.getenv("SUBTITLE_SLOT_PADDING_SEC", "0.2")),
        min_overlap_sec=float(os.getenv("SUBTITLE_MIN_OVERLAP_SEC", "0.15")),
        min_segment_overlap_ratio=float(os.getenv("SUBTITLE_MIN_SEGMENT_OVERLAP_RATIO", "0.15")),
        min_slot_overlap_ratio=float(os.getenv("SUBTITLE_MIN_SLOT_OVERLAP_RATIO", "0.10")),
        slot_word_padding_sec=float(os.getenv("SUBTITLE_SLOT_WORD_PADDING_SEC", "0.15")),
        assign_by_word_midpoint=_bool("SUBTITLE_SLOT_ASSIGN_BY_WORD_MIDPOINT", "1"),
        prevent_duplicate_slot_text=_bool("SUBTITLE_PREVENT_DUPLICATE_SLOT_TEXT", "1"),
        clip_min_duration=float(os.getenv("SUBTITLE_CLIP_MIN_DURATION", "0.8")),
        clip_max_duration=float(os.getenv("SUBTITLE_CLIP_MAX_DURATION", "4.5")),
        clip_target_duration=float(os.getenv("SUBTITLE_CLIP_TARGET_DURATION", "2.2")),
        clip_max_chars=int(os.getenv("SUBTITLE_CLIP_MAX_CHARS", "22")),
        clip_min_chars=int(os.getenv("SUBTITLE_CLIP_MIN_CHARS", "4")),
        clip_max_lines=int(os.getenv("SUBTITLE_CLIP_MAX_LINES", "2")),
        clip_max_chars_per_line=int(os.getenv("SUBTITLE_CLIP_MAX_CHARS_PER_LINE", "16")),
        clip_pause_threshold_sec=float(os.getenv("SUBTITLE_CLIP_PAUSE_THRESHOLD_SEC", "0.35")),
        clip_merge_gap_sec=float(os.getenv("SUBTITLE_CLIP_MERGE_GAP_SEC", "0.35")),
        clip_use_word_timestamps=_bool("SUBTITLE_CLIP_USE_WORD_TIMESTAMPS", "1"),
        cut_strategy=os.getenv("CUT_STRATEGY", "caption_slot").strip().lower() or "caption_slot",
        material_fill_strategy=os.getenv("MATERIAL_FILL_STRATEGY", "fit_caption_slots").strip().lower()
        or "fit_caption_slots",
        caption_slot_min_duration=float(os.getenv("CAPTION_SLOT_MIN_DURATION", "0.8")),
        caption_slot_max_duration=float(os.getenv("CAPTION_SLOT_MAX_DURATION", "5.0")),
        caption_slot_target_duration=float(os.getenv("CAPTION_SLOT_TARGET_DURATION", "2.5")),
        caption_slot_max_chars=int(os.getenv("CAPTION_SLOT_MAX_CHARS", "28")),
        caption_slot_min_chars=int(os.getenv("CAPTION_SLOT_MIN_CHARS", "4")),
        caption_slot_merge_gap_sec=float(os.getenv("CAPTION_SLOT_MERGE_GAP_SEC", "0.25")),
        caption_slot_use_ocr_text=_bool("CAPTION_SLOT_USE_OCR_TEXT", "0"),
        caption_slot_use_asr_time=_bool("CAPTION_SLOT_USE_ASR_TIME", "1"),
        caption_slot_ocr_asr_sim_threshold=float(os.getenv("CAPTION_SLOT_OCR_ASR_SIM_THRESHOLD", "0.55")),
        caption_slot_ocr_subtitle_score_threshold=float(
            os.getenv("CAPTION_SLOT_OCR_SUBTITLE_SCORE_THRESHOLD", "0.65")
        ),
        caption_ocr_validate=_bool("CAPTION_OCR_VALIDATE", "1"),
        caption_ocr_validate_split=_bool("CAPTION_OCR_VALIDATE_SPLIT", "1"),
        caption_ocr_validate_merge=_bool("CAPTION_OCR_VALIDATE_MERGE", "1"),
        caption_ocr_text_correct_threshold=float(
            os.getenv("CAPTION_OCR_TEXT_CORRECT_THRESHOLD", "0.82")
        ),
        caption_ocr_mismatch_review_threshold=float(
            os.getenv("CAPTION_OCR_MISMATCH_REVIEW_THRESHOLD", "0.45")
        ),
        caption_ocr_overlap_min_ratio=float(os.getenv("CAPTION_OCR_OVERLAP_MIN_RATIO", "0.18")),
    )


def resolve_recognition_mode(request_mode: str | None) -> str:
    """解析 API mode → speech | burned（默认 speech，auto 默认 speech）。"""
    raw = str(request_mode or "speech").strip().lower()
    if raw in ("speech", "audio", ""):
        return "speech"
    if raw in ("burned", "visual"):
        return "burned"
    if raw == "auto":
        cfg = get_subtitle_config()
        return "burned" if cfg.mode == "burned" else "speech"
    return "speech"
