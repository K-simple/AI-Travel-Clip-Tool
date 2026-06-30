"""音频预处理 / 增强（可选 Demucs，默认 fallback）。"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable

ProgressCb = Callable[[str, int], None] | None


@dataclass
class AudioEnhanceResult:
    output_path: str
    used_loudnorm: bool = False
    vocal_isolation_used: bool = False
    vocal_isolation_source: str = ""
    fallback_to_original: bool = False
    elapsed_ms: int = 0
    steps: list[str] = field(default_factory=list)


class AudioEnhancer:
    """口播 ASR 前音频增强；Demucs 默认关闭，失败无感 fallback。"""

    def __init__(self, *, enable_enhance: bool = True, enable_vocal_isolation: bool = False):
        self.enable_enhance = enable_enhance
        self.enable_vocal_isolation = enable_vocal_isolation

    def enhance(
        self,
        input_audio: str,
        output_audio: str,
        *,
        on_progress: ProgressCb = None,
    ) -> AudioEnhanceResult:
        t0 = time.monotonic()
        steps: list[str] = []
        result = AudioEnhanceResult(output_path=output_audio)

        if on_progress:
            on_progress("audio_preprocess", 15)

        os.makedirs(os.path.dirname(output_audio) or ".", exist_ok=True)

        if not self.enable_enhance:
            if os.path.abspath(input_audio) != os.path.abspath(output_audio):
                import shutil

                shutil.copy2(input_audio, output_audio)
            steps.append("enhance_disabled_copy")
            result.steps = steps
            result.elapsed_ms = int((time.monotonic() - t0) * 1000)
            print(f"[speech][audio] 跳过增强，直接复制 ({result.elapsed_ms}ms)")
            return result

        vocal_path = input_audio
        if self.enable_vocal_isolation:
            try:
                from services.vocal_separator import resolve_vocal_source_path

                isolated = resolve_vocal_source_path(input_audio, force=False)
                if isolated and os.path.isfile(isolated) and os.path.getsize(isolated) > 0:
                    vocal_path = isolated
                    result.vocal_isolation_used = True
                    result.vocal_isolation_source = isolated
                    steps.append("vocal_isolation_cached")
                    print(f"[speech][audio] 使用缓存人声轨 ({result.elapsed_ms}ms): {isolated}")
                else:
                    steps.append("vocal_isolation_skip_no_cache")
                    print("[speech][audio] 无人声分离缓存，使用原音频（未触发 Demucs）")
            except Exception as exc:
                steps.append(f"vocal_isolation_error:{exc}")
                print(f"[speech][audio] 人声分离跳过: {exc}")
        else:
            steps.append("vocal_isolation_disabled")

        t_loud = time.monotonic()
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            vocal_path,
            "-ac",
            "1",
            "-ar",
            "16000",
            "-af",
            "highpass=f=80,lowpass=f=8000,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:a",
            "pcm_s16le",
            output_audio,
        ]
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        loud_ms = int((time.monotonic() - t_loud) * 1000)

        if proc.returncode != 0 or not os.path.isfile(output_audio):
            result.fallback_to_original = True
            steps.append("loudnorm_failed_fallback")
            print(f"[speech][audio] loudnorm 失败 ({loud_ms}ms)，回退原音频: {proc.stderr[:160]}")
            if os.path.abspath(vocal_path) != os.path.abspath(output_audio):
                import shutil

                shutil.copy2(vocal_path, output_audio)
        else:
            result.used_loudnorm = True
            steps.append(f"loudnorm_ok:{loud_ms}ms")
            print(f"[speech][audio] loudnorm 完成 ({loud_ms}ms)")

        result.steps = steps
        result.elapsed_ms = int((time.monotonic() - t0) * 1000)
        print(
            f"[speech][audio] 预处理完成 {result.elapsed_ms}ms | "
            f"loudnorm={result.used_loudnorm} vocal={result.vocal_isolation_used} fallback={result.fallback_to_original}"
        )
        return result
