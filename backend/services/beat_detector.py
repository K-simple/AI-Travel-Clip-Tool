"""简易 BGM 节拍标记（Phase C MVP：按固定间隔生成，可后续换 librosa）。"""

from typing import List


def estimate_beat_markers(duration: float, bpm: float = 118.0) -> List[float]:
    if duration <= 0 or bpm <= 0:
        return []
    interval = 60.0 / bpm
    markers: List[float] = []
    t = 0.0
    while t < duration:
        markers.append(round(t, 3))
        t += interval
    return markers
