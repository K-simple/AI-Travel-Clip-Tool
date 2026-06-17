"""导出时解析轨道控制，与前端 preview mix 规则一致。"""

from typing import Any, Dict, Optional


def _ctrl(track_controls: Optional[Dict[str, Any]], key: str) -> Dict[str, Any]:
    if not track_controls:
        return {}
    value = track_controls.get(key)
    return value if isinstance(value, dict) else {}


def _has_solo(track_controls: Optional[Dict[str, Any]]) -> bool:
    if not track_controls:
        return False
    return any(isinstance(v, dict) and v.get("solo") for v in track_controls.values())


def _track_active(track_controls: Optional[Dict[str, Any]], key: str) -> bool:
    ctrl = _ctrl(track_controls, key)
    if ctrl.get("visible") is False:
        return False
    if _has_solo(track_controls):
        return bool(ctrl.get("solo"))
    return True


def resolve_export_mix(
    track_controls: Optional[Dict[str, Any]] = None,
    *,
    template_music_enabled: bool = True,
    use_asset_audio: bool = False,
    asset_audio_volume: float = 0.3,
    template_audio_volume: float = 1.0,
    add_subtitles: bool = True,
) -> Dict[str, Any]:
    """根据轨道控制与模板音乐开关，计算导出音频/字幕/轨道可见性。"""
    vol = float(template_audio_volume)
    if not template_music_enabled:
        vol = 0.0
    if not _track_active(track_controls, "audio") or _ctrl(track_controls, "audio").get("muted"):
        vol = 0.0

    use_asset = bool(use_asset_audio)
    if not _track_active(track_controls, "audioVoice") or _ctrl(track_controls, "audioVoice").get("muted"):
        use_asset = False
    if not _track_active(track_controls, "video") or _ctrl(track_controls, "video").get("muted"):
        use_asset = False

    burn_subtitles = bool(add_subtitles)
    if not _track_active(track_controls, "subtitle") or _ctrl(track_controls, "subtitle").get("muted"):
        burn_subtitles = False

    return {
        "template_audio_volume": vol,
        "use_asset_audio": use_asset,
        "asset_audio_volume": float(asset_audio_volume),
        "add_subtitles": burn_subtitles,
        "include_video_track": _track_active(track_controls, "video"),
        "include_overlay": _track_active(track_controls, "overlay")
        or _track_active(track_controls, "sticker"),
        "include_video2": _track_active(track_controls, "video2"),
    }
