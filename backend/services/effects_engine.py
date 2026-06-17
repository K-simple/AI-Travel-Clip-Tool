"""关键帧 / 调色 / 蒙版 / 变速 / 光流 — FFmpeg 滤镜编译。"""

from typing import Any, Dict, List, Optional


def _interp_keyframes(keyframes: List[Dict], prop: str, t: float, default: float) -> float:
    if not keyframes:
        return default
    sorted_kf = sorted(keyframes, key=lambda k: float(k.get("time", 0)))
    if t <= float(sorted_kf[0].get("time", 0)):
        return float(sorted_kf[0].get("props", {}).get(prop, default))
    for i in range(1, len(sorted_kf)):
        t0 = float(sorted_kf[i - 1].get("time", 0))
        t1 = float(sorted_kf[i].get("time", 0))
        if t0 <= t <= t1:
            v0 = float(sorted_kf[i - 1].get("props", {}).get(prop, default))
            v1 = float(sorted_kf[i].get("props", {}).get(prop, default))
            if t1 <= t0:
                return v1
            ratio = (t - t0) / (t1 - t0)
            return v0 + (v1 - v0) * ratio
    return float(sorted_kf[-1].get("props", {}).get(prop, default))


def build_color_filter(color: Optional[Dict[str, Any]]) -> str:
    if not color:
        return ""
    b = float(color.get("brightness", 0))
    c = float(color.get("contrast", 1))
    s = float(color.get("saturation", 1))
    g = float(color.get("gamma", 1))
    parts = []
    if b or c != 1 or s != 1:
        parts.append(f"eq=brightness={b}:contrast={c}:saturation={s}")
    if g != 1:
        parts.append(f"gamma={g}")
    hue = color.get("hue")
    if hue is not None:
        parts.append(f"hue=h={float(hue)}")
    return ",".join(parts)


def build_mask_filter(mask: Optional[Dict[str, Any]], width: int, height: int) -> str:
    if not mask or not mask.get("enabled"):
        return ""
    mtype = mask.get("type", "rect")
    feather = float(mask.get("feather", 0))
    if mtype == "circle":
        r = int(mask.get("radius", min(width, height) // 3))
        cx = int(mask.get("cx", width // 2))
        cy = int(mask.get("cy", height // 2))
        return f"geq=lum='if(lt(sqrt(pow(X-{cx},2)+pow(Y-{cy},2)),{r}),lum(X,Y),0)':cb='cb(X,Y)':cr='cr(X,Y)'"
    # 矩形蒙版
    x = int(mask.get("x", width // 4))
    y = int(mask.get("y", height // 4))
    w = int(mask.get("w", width // 2))
    h = int(mask.get("h", height // 2))
    if feather > 0:
        return f"crop={w}:{h}:{x}:{y},scale={width}:{height}"
    return f"crop={w}:{h}:{x}:{y},pad={width}:{height}:{x}:{y}"


def build_speed_filter(speed: float, use_optical_flow: bool = False) -> str:
    if abs(speed - 1.0) < 0.01:
        return ""
    if use_optical_flow and 0.25 <= speed <= 4.0:
        return f"minterpolate=fps=30:mi_mode=mci,setpts=PTS/{speed}"
    return f"setpts=PTS/{speed}"


def compile_clip_filters(
    clip: Dict[str, Any],
    width: int,
    height: int,
    *,
    local_time: float = 0.0,
) -> str:
    """将 clip 上的 effects 编译为 ffmpeg -vf 链。"""
    chain: List[str] = [f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"]

    speed = float(clip.get("speed", 1.0))
    sf = build_speed_filter(speed, use_optical_flow=bool(clip.get("optical_flow", False)))
    if sf:
        chain.append(sf)

    keyframes = clip.get("keyframes") or []
    if keyframes:
        scale = _interp_keyframes(keyframes, "scale", local_time, 1.0)
        opacity = _interp_keyframes(keyframes, "opacity", local_time, 1.0)
        if abs(scale - 1.0) > 0.01:
            chain.append(f"scale=iw*{scale}:ih*{scale}")
        if opacity < 0.99:
            chain.append(f"colorchannelmixer=aa={opacity}")

    color_f = build_color_filter(clip.get("color_grade"))
    if color_f:
        chain.append(color_f)

    mask_f = build_mask_filter(clip.get("mask"), width, height)
    if mask_f:
        chain.append(mask_f)

    chain.append("fps=30")
    return ",".join(chain)
