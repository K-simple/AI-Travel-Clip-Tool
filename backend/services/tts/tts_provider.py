"""TTS provider 抽象与 mock 实现。"""

from __future__ import annotations

import os
import wave
from abc import ABC, abstractmethod
from typing import Any

from services.tts.tts_utils import estimate_duration_from_text


class TtsProvider(ABC):
    @abstractmethod
    def synthesize(
        self,
        text: str,
        *,
        voice_id: str,
        output_path: str,
        language: str = "zh-CN",
    ) -> dict[str, Any]:
        """返回 {duration, provider, audioPath}。"""


class MockTtsProvider(TtsProvider):
    """生成静音 wav，时长按中文字数估算。"""

    provider_name = "mock"
    sample_rate = 24000

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str,
        output_path: str,
        language: str = "zh-CN",
    ) -> dict[str, Any]:
        duration = estimate_duration_from_text(text)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        _write_silent_wav(output_path, duration, sample_rate=self.sample_rate)
        from services.subtitle_gen import _audio_duration_seconds

        actual = _audio_duration_seconds(output_path) or duration
        rel = output_path.replace("\\", "/")
        return {
            "duration": round(float(actual), 3),
            "provider": self.provider_name,
            "audioPath": rel,
        }


def _write_silent_wav(path: str, duration_sec: float, *, sample_rate: int = 24000) -> None:
    duration_sec = max(0.08, min(float(duration_sec), 120.0))
    n_frames = max(1, int(duration_sec * sample_rate))
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        chunk = 4096
        silence = b"\x00\x00" * chunk
        remaining = n_frames
        while remaining > 0:
            take = min(chunk, remaining)
            wf.writeframes(silence[: take * 2])
            remaining -= take


def get_tts_provider(provider: str | None = None) -> TtsProvider:
    name = str(provider or os.getenv("TTS_PROVIDER", "mock")).strip().lower()
    if name in ("edge", "azure", "volcengine", "local"):
        # 真实 TTS 后续接入；当前 fallback 到 mock
        return MockTtsProvider()
    return MockTtsProvider()
