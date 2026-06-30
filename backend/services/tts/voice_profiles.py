"""TTS 音色配置。"""

from __future__ import annotations

from typing import Any

VOICE_PROFILES: list[dict[str, Any]] = [
    {
        "voiceId": "real_blog_female",
        "displayName": "真人博客女",
        "language": "zh-CN",
        "gender": "female",
        "style": "blogger",
        "provider": "mock",
    },
]


def list_voice_profiles() -> list[dict[str, Any]]:
    return [dict(v) for v in VOICE_PROFILES]


def get_voice_profile(voice_id: str) -> dict[str, Any] | None:
    vid = str(voice_id or "").strip()
    for profile in VOICE_PROFILES:
        if str(profile.get("voiceId") or "") == vid:
            return dict(profile)
    return None
