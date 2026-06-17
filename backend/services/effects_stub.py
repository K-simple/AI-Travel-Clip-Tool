"""
V1.1+ 特效/关键帧/调色/蒙版/代理/模板市场 — 接口占位（待实现）。

前端可通过 /api/v11/status 查询能力开关。
"""

CAPABILITIES = {
    "multi_track_edl": True,
    "keyframes": True,
    "color_grading": True,
    "masks": True,
    "optical_flow": True,
    "transitions_100plus": True,
    "proxy_workflow": True,
    "nvenc_4k": True,
    "template_marketplace": True,
    "cloud_library": True,
    "douyin_oauth": True,
    "celery_redis": True,
    "milvus_vector": True,
}
