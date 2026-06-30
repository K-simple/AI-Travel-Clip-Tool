"""后台分析性能开关（默认偏向快速就绪）。"""

import os

from services.resource_profile import clamp_workers

# 四档预设：budget（默认，千元机+~3k PC）| standard | dev | quality
PROCESSING_PRESET = os.getenv("PROCESSING_PRESET", "budget").strip().lower()


def _w(env_key: str, default: int) -> int:
    try:
        raw = int(os.getenv(env_key, str(default)))
    except (TypeError, ValueError):
        raw = default
    reserve = 2 if PROCESSING_PRESET in ("budget", "dev") else 1
    return clamp_workers(raw, reserve_cores=reserve)


_PRESET_ENV: dict[str, dict[str, str]] = {
    "budget": {
        "FAST_PROCESSING": "1",
        "TEMPLATE_FAST_EDIT_READY": "1",
        "ASSET_FAST_EDIT_READY": "1",
        "AUTO_SUBTITLE_AFTER_INTAKE": "0",
        "DEFER_TEMPLATE_PROXIES": "1",
        "DEFER_ASSET_PROXIES": "1",
        "DEFER_ASSET_AI_LABELS": "1",
        "DEFER_TEMPLATE_AI_LABELS": "1",
        "ENABLE_AI_LABELS": "0",
        "TEMPLATE_FAST_SKIP_AUTO_TUNE": "1",
        "TEMPLATE_SCENE_AUTO_TUNE": "0",
        "ENABLE_AI_SHOT_REFINE": "0",
        "ENABLE_TEMPLATE_VISION": "0",
        "ENABLE_TEMPLATE_EFFECTS_ANALYSIS": "0",
        "ENABLE_SUBTITLE_SCENE_AI": "0",
        "ENABLE_SUBTITLE_STYLE_ANALYSIS": "0",
        "ENABLE_SFX_DETECTION": "0",
        "SUBTITLE_PRELOAD": "0",
        "VOCAL_SEPARATION": "ffmpeg",
        "WHISPER_MODEL": "small",
        "WHISPER_MODEL_FALLBACKS": "base,tiny",
        "WHISPER_COMPUTE_TYPE": "int8",
        "WHISPER_DEVICE": "cpu",
        "WHISPER_BATCH_BEAM_SIZE": "1",
        "WHISPER_QUALITY_BEAM_SIZE": "3",
        "WHISPER_BEAM_SIZE": "5",
        "SUBTITLE_OCR_WORKERS": "2",
        "SUBTITLE_BATCH_WORKERS": "1",
        "FRAME_EXTRACT_WORKERS": "2",
        "SEGMENT_CUT_WORKERS": "2",
        "TEMPLATE_INTAKE_AI_WORKERS": "2",
        "TASK_QUEUE_WORKERS": "2",
        "MAX_TEMPLATE_SEGMENTS": "50",
        "AI_LABEL_MAX_ITEMS": "24",
        "TEMPLATE_INTAKE_BUDGET_SEC": "28",
    },
    "dev": {
        "FAST_PROCESSING": "1",
        "SUBTITLE_PRELOAD": "0",
        "ENABLE_AI_SHOT_REFINE": "0",
        "ENABLE_TEMPLATE_VISION": "0",
        "ENABLE_TEMPLATE_EFFECTS_ANALYSIS": "0",
        "DEFER_WHISPER": "1",
        "AUTO_SUBTITLE_AFTER_INTAKE": "0",
    },
    "standard": {
        "FAST_PROCESSING": "1",
        "TEMPLATE_FAST_EDIT_READY": "1",
        "ASSET_FAST_EDIT_READY": "1",
        "AUTO_SUBTITLE_AFTER_INTAKE": "1",
    },
    "quality": {
        "FAST_PROCESSING": "0",
        "TEMPLATE_FAST_EDIT_READY": "0",
        "ASSET_FAST_EDIT_READY": "0",
        "DEFER_WHISPER": "0",
        "DEFER_TEMPLATE_PROXIES": "0",
        "DEFER_ASSET_PROXIES": "0",
        "TEMPLATE_FAST_SKIP_AUTO_TUNE": "0",
        "AUTO_SUBTITLE_AFTER_INTAKE": "1",
    },
}


def _apply_processing_preset() -> None:
    for key, value in _PRESET_ENV.get(PROCESSING_PRESET, _PRESET_ENV["standard"]).items():
        os.environ.setdefault(key, value)


_apply_processing_preset()

FAST_MODE = os.getenv("FAST_PROCESSING", "1").strip().lower() in ("1", "true", "yes")

# 素材：先入库可拖拽，镜头精分/代理/AI 标签后台继续
ASSET_FAST_EDIT_READY = os.getenv("ASSET_FAST_EDIT_READY", "1" if FAST_MODE else "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
DEFER_ASSET_PROXIES = os.getenv(
    "DEFER_ASSET_PROXIES", "1" if ASSET_FAST_EDIT_READY else "0"
).strip().lower() in ("1", "true", "yes")
DEFER_ASSET_AI_LABELS = os.getenv(
    "DEFER_ASSET_AI_LABELS", "1" if ASSET_FAST_EDIT_READY else "0"
).strip().lower() in ("1", "true", "yes")
# 快速入库先用等间隔镜头 + 单封面，精分与逐段缩略图延后
ASSET_QUICK_SEGMENTS = os.getenv(
    "ASSET_QUICK_SEGMENTS", "1" if ASSET_FAST_EDIT_READY else "0"
).strip().lower() in ("1", "true", "yes")

SKIP_CLIP = os.getenv("SKIP_CLIP_ANALYSIS", "1" if FAST_MODE else "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
# 默认导出镜头 MP4，时间轴才能按真实视频片段展示
SKIP_SEGMENT_MP4 = os.getenv("SKIP_SEGMENT_MP4", "1" if FAST_MODE else "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
SKIP_PROXY = os.getenv("SKIP_PROXY", "0").strip().lower() in ("1", "true", "yes")
DEFER_WHISPER = os.getenv("DEFER_WHISPER", "1" if FAST_MODE else "0").strip().lower() in (
    "1",
    "true",
    "yes",
)

# 模板：约 30s intake（切分+AI理解+字幕花字），代理/Whisper/深度特效后台继续
TEMPLATE_FAST_EDIT_READY = os.getenv("TEMPLATE_FAST_EDIT_READY", "1" if FAST_MODE else "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
# 快速就绪阶段跳过 threshold 网格校准（省 5 次场景检测）
TEMPLATE_FAST_SKIP_AUTO_TUNE = os.getenv(
    "TEMPLATE_FAST_SKIP_AUTO_TUNE", "1" if TEMPLATE_FAST_EDIT_READY else "0"
).strip().lower() in ("1", "true", "yes")
# 预览代理延后到可编辑之后生成
DEFER_TEMPLATE_PROXIES = os.getenv(
    "DEFER_TEMPLATE_PROXIES", "1" if TEMPLATE_FAST_EDIT_READY else "0"
).strip().lower() in ("1", "true", "yes")
# 模板 DeepSeek 槽位标签延后（intake 已有 CLIP 标签即可编辑/匹配）
DEFER_TEMPLATE_AI_LABELS = os.getenv(
    "DEFER_TEMPLATE_AI_LABELS", "1" if TEMPLATE_FAST_EDIT_READY else "0"
).strip().lower() in ("1", "true", "yes")
# 场景检测失败时不回退等间隔切分（仅按画面切分）
TEMPLATE_SCENE_INTERVAL_FALLBACK = os.getenv("TEMPLATE_SCENE_INTERVAL_FALLBACK", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)

MAX_SEGMENTS = int(os.getenv("MAX_ANALYSIS_SEGMENTS", "20"))
# 旅游混剪档位：travel_ultra | travel_fast | travel_normal | travel_slow
TEMPLATE_SCENE_PROFILE = os.getenv("TEMPLATE_SCENE_PROFILE", "travel_fast")
# 上传模板时按样片自动校准 threshold（在档位候选值中选最优）
TEMPLATE_SCENE_AUTO_TUNE = os.getenv("TEMPLATE_SCENE_AUTO_TUNE", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
# 以下可由档位预设推导，环境变量仍可覆盖
MAX_TEMPLATE_SEGMENTS = int(os.getenv("MAX_TEMPLATE_SEGMENTS", "80"))
SCENE_THRESHOLD = float(os.getenv("SCENE_DETECT_THRESHOLD", "32.0"))
TEMPLATE_SCENE_THRESHOLD = float(os.getenv("TEMPLATE_SCENE_THRESHOLD", "27.0"))
MIN_TEMPLATE_SHOT_DURATION = float(os.getenv("MIN_TEMPLATE_SHOT_DURATION", "0.25"))
FRAME_EXTRACT_WORKERS = _w("FRAME_EXTRACT_WORKERS", 4 if PROCESSING_PRESET == "standard" else 2)
SEGMENT_CUT_WORKERS = _w("SEGMENT_CUT_WORKERS", 3 if PROCESSING_PRESET == "standard" else 2)
TEMPLATE_SLOT_INTERVAL = float(os.getenv("TEMPLATE_SLOT_INTERVAL", "4.0"))
# 模板默认启用场景切分（旅游混剪：一镜一槽），FAST_MODE 下不再跳过
SKIP_TEMPLATE_SCENE_DETECT = os.getenv(
    "SKIP_TEMPLATE_SCENE_DETECT", "0"
).strip().lower() in ("1", "true", "yes")
# 模板导入时不做 PySceneDetect 切分，整段原视频作为一个画面槽（字幕/TTS 流程后再切）
TEMPLATE_SINGLE_VIDEO_SLOT = os.getenv("TEMPLATE_SINGLE_VIDEO_SLOT", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
# base：上传后仅 base slot；auto_visual：上传时 PySceneDetect 自动切槽（旧行为）
_slot_mode_raw = os.getenv("SLOT_CREATION_MODE", "").strip().lower()
if _slot_mode_raw in ("base", "auto_visual"):
    SLOT_CREATION_MODE = _slot_mode_raw
elif not TEMPLATE_SINGLE_VIDEO_SLOT:
    SLOT_CREATION_MODE = "auto_visual"
else:
    SLOT_CREATION_MODE = "base"


def is_base_slot_creation_mode() -> bool:
    return SLOT_CREATION_MODE == "base"


def _flag_on(env_key: str, default: str = "1") -> bool:
    return os.getenv(env_key, default).strip().lower() in ("1", "true", "yes")


# 一句字幕 = 一个画面槽 = 一个素材片段（默认严格一一对应）
ONE_CAPTION_ONE_SHOT = _flag_on("ONE_CAPTION_ONE_SHOT", "1")
ONE_SLOT_ONE_MATERIAL = _flag_on("ONE_SLOT_ONE_MATERIAL", "1")
ENABLE_SECONDARY_CUTS = _flag_on("ENABLE_SECONDARY_CUTS", "0")
ALLOW_MULTI_MATERIAL_PER_CAPTION = _flag_on("ALLOW_MULTI_MATERIAL_PER_CAPTION", "0")
MATERIAL_FILL_STRATEGY = os.getenv(
    "MATERIAL_FILL_STRATEGY", "one_material_per_caption_slot"
).strip().lower()


def is_one_caption_one_shot() -> bool:
    return ONE_CAPTION_ONE_SHOT


def is_one_slot_one_material() -> bool:
    return ONE_SLOT_ONE_MATERIAL


def is_secondary_cuts_enabled() -> bool:
    return ENABLE_SECONDARY_CUTS


def is_multi_material_per_caption_allowed() -> bool:
    return ALLOW_MULTI_MATERIAL_PER_CAPTION
TEMPLATE_EXTRACT_AUDIO_EARLY = os.getenv("TEMPLATE_EXTRACT_AUDIO_EARLY", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)

# DeepSeek V4 辅助镜头切分（需 DEEPSEEK_API_KEY）
ENABLE_AI_SHOT_REFINE = os.getenv("ENABLE_AI_SHOT_REFINE", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
AI_SHOT_MAX_BOUNDARY_CHECKS = int(os.getenv("AI_SHOT_MAX_BOUNDARY_CHECKS", "60"))
AI_SHOT_SPLIT_MIN_DURATION = float(os.getenv("AI_SHOT_SPLIT_MIN_DURATION", "2.0"))

# DeepSeek V4 中文画面描述（模板槽位 + 素材片段）
ENABLE_AI_LABELS = os.getenv("ENABLE_AI_LABELS", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
AI_LABEL_MAX_ITEMS = int(os.getenv("AI_LABEL_MAX_ITEMS", "80"))

# 模板成片级 AI 视觉理解（多帧摘要 + 槽位替换建议，需 DEEPSEEK_API_KEY）
ENABLE_TEMPLATE_VISION = os.getenv("ENABLE_TEMPLATE_VISION", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
TEMPLATE_VISION_MAX_FRAMES = int(os.getenv("TEMPLATE_VISION_MAX_FRAMES", "6"))

# 模板槽位 AI 特效理解（每槽调色/动效/字幕动画，需 DEEPSEEK_API_KEY）
ENABLE_TEMPLATE_EFFECTS_ANALYSIS = os.getenv("ENABLE_TEMPLATE_EFFECTS_ANALYSIS", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
TEMPLATE_EFFECTS_MAX_SLOTS = int(os.getenv("TEMPLATE_EFFECTS_MAX_SLOTS", "40"))

# 字幕花字样式分析（OpenCV 帧差 + 可选 DeepSeek 视觉）
ENABLE_SUBTITLE_STYLE_ANALYSIS = os.getenv("ENABLE_SUBTITLE_STYLE_ANALYSIS", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
SUBTITLE_STYLE_MAX_SEGMENTS = int(os.getenv("SUBTITLE_STYLE_MAX_SEGMENTS", "40"))

# 字幕识别后：AI 理解花字特效 + 字幕与画面对齐（需 DEEPSEEK_API_KEY 视觉；无 key 时仅 OpenCV 样式）
ENABLE_SUBTITLE_SCENE_AI = os.getenv("ENABLE_SUBTITLE_SCENE_AI", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
SUBTITLE_SCENE_MAX_SLOTS = int(os.getenv("SUBTITLE_SCENE_MAX_SLOTS", "40"))

# 模板导入：~30s 内切分 + AI 画面理解 + 字幕/花字（重活仍后台增强）
TEMPLATE_INTAKE_BUDGET_SEC = int(os.getenv("TEMPLATE_INTAKE_BUDGET_SEC", "30"))
TEMPLATE_INTAKE_AI_WORKERS = _w("TEMPLATE_INTAKE_AI_WORKERS", 3 if PROCESSING_PRESET == "standard" else 2)
TEMPLATE_INTAKE_SUBTITLE_OCR = os.getenv("TEMPLATE_INTAKE_SUBTITLE_OCR", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
TEMPLATE_INTAKE_VISION_LABELS = os.getenv("TEMPLATE_INTAKE_VISION_LABELS", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
# intake 阶段花字/场景 AI 仅用 OpenCV（DeepSeek 视觉留后台增强）
TEMPLATE_INTAKE_OPENCV_SUBTITLE_ONLY = os.getenv("TEMPLATE_INTAKE_OPENCV_SUBTITLE_ONLY", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)

# 音效点位检测（librosa onset + 节拍过滤）
ENABLE_SFX_DETECTION = os.getenv("ENABLE_SFX_DETECTION", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
SFX_BEAT_TOLERANCE_SEC = float(os.getenv("SFX_BEAT_TOLERANCE_SEC", "0.08"))
SFX_MIN_ENERGY = float(os.getenv("SFX_MIN_ENERGY", "0.018"))
SFX_MIN_INTERVAL_SEC = float(os.getenv("SFX_MIN_INTERVAL_SEC", "0.15"))

# intake 完成后后台 OCR+ASR 融合（standard/quality 预设默认开启）
AUTO_SUBTITLE_AFTER_INTAKE = os.getenv("AUTO_SUBTITLE_AFTER_INTAKE", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)

# 字幕识别模式：speech（口播 ASR 默认）| burned | auto
SUBTITLE_MODE = os.getenv("SUBTITLE_MODE", "speech").strip().lower()

ENABLE_SUBTITLE_TIMELINE_SCAN = os.getenv("ENABLE_SUBTITLE_TIMELINE_SCAN", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
# 一镜多句时按字幕边界自动拆槽（剪映式一句一槽）
ENABLE_SUBTITLE_DRIVEN_SLOT_SPLIT = os.getenv("ENABLE_SUBTITLE_DRIVEN_SLOT_SPLIT", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
# align=保留镜头槽，只写准字幕（默认，约等于字幕句数）
# split_distinct=仅当同一镜头内 2 句不同字幕才拆槽
SUBTITLE_SLOT_STRATEGY = os.getenv("SUBTITLE_SLOT_STRATEGY", "align").strip().lower()
SUBTITLE_SPLIT_MIN_SLOT_SEC = float(os.getenv("SUBTITLE_SPLIT_MIN_SLOT_SEC", "0.28"))
SUBTITLE_SCAN_FPS = float(os.getenv("SUBTITLE_SCAN_FPS", "4" if PROCESSING_PRESET in ("budget", "dev") else "6"))

# 字幕识别档位：fast（默认，偏速度）| quality（精识别，全量 Whisper + HQ OCR）
SUBTITLE_RECOGNITION_MODE = os.getenv("SUBTITLE_RECOGNITION_MODE", "fast").strip().lower()


def is_subtitle_quality_mode() -> bool:
    return SUBTITLE_RECOGNITION_MODE == "quality"


# 字幕 / 任务队列并行度（经 CPU 上限裁剪）
SUBTITLE_OCR_WORKERS = _w("SUBTITLE_OCR_WORKERS", 3 if PROCESSING_PRESET in ("budget", "dev") else 4)
SUBTITLE_BATCH_WORKERS = _w("SUBTITLE_BATCH_WORKERS", 1 if PROCESSING_PRESET in ("budget", "dev") else 2)
TASK_QUEUE_WORKERS = _w("TASK_QUEUE_WORKERS", 2 if PROCESSING_PRESET in ("budget", "dev") else 4)
