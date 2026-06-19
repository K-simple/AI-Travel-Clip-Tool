"""后台分析性能开关（默认偏向快速就绪）。"""

import os

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

# 模板：约 10 秒内可编辑（先场景切分就绪，AI 修正/代理/音频后台继续）
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
FRAME_EXTRACT_WORKERS = int(os.getenv("FRAME_EXTRACT_WORKERS", "6"))
SEGMENT_CUT_WORKERS = int(os.getenv("SEGMENT_CUT_WORKERS", "4"))
TEMPLATE_SLOT_INTERVAL = float(os.getenv("TEMPLATE_SLOT_INTERVAL", "4.0"))
# 模板默认启用场景切分（旅游混剪：一镜一槽），FAST_MODE 下不再跳过
SKIP_TEMPLATE_SCENE_DETECT = os.getenv(
    "SKIP_TEMPLATE_SCENE_DETECT", "0"
).strip().lower() in ("1", "true", "yes")
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

# 字幕花字样式分析（OpenCV 帧差 + 可选 DeepSeek 视觉）
ENABLE_SUBTITLE_STYLE_ANALYSIS = os.getenv("ENABLE_SUBTITLE_STYLE_ANALYSIS", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
SUBTITLE_STYLE_MAX_SEGMENTS = int(os.getenv("SUBTITLE_STYLE_MAX_SEGMENTS", "40"))

# 音效点位检测（librosa onset + 节拍过滤）
ENABLE_SFX_DETECTION = os.getenv("ENABLE_SFX_DETECTION", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
SFX_BEAT_TOLERANCE_SEC = float(os.getenv("SFX_BEAT_TOLERANCE_SEC", "0.08"))
SFX_MIN_ENERGY = float(os.getenv("SFX_MIN_ENERGY", "0.018"))
SFX_MIN_INTERVAL_SEC = float(os.getenv("SFX_MIN_INTERVAL_SEC", "0.15"))
