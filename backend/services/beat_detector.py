"""BGM 节拍标记（librosa 优先，固定 BPM 回退）。"""

import os
from typing import List


def estimate_beat_markers(duration: float, bpm: float = 118.0, audio_path: str = "") -> List[float]:
    if audio_path and os.path.isfile(audio_path):
        try:
            from services.sfx_detector import detect_beats_from_audio

            beats = detect_beats_from_audio(audio_path)
            if beats:
                return beats
        except Exception as exc:
            print(f"librosa 节拍检测失败，使用固定 BPM 回退: {exc}")

    if duration <= 0 or bpm <= 0:
        return []

    interval = 60.0 / bpm
    markers: List[float] = []
    t = 0.0
    while t < duration:
        markers.append(round(t, 3))
        t += interval
    return markers
