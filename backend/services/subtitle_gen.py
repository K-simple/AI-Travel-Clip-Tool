import os
from faster_whisper import WhisperModel

# 延迟加载模型（第一次调用时才下载）
_model = None


def get_model():
    global _model
    if _model is None:
        print("正在加载 Whisper 模型...")
        _model = WhisperModel("base", device="cpu", compute_type="int8")
        print("Whisper 模型加载完成")
    return _model


def transcribe(audio_path: str) -> list:
    """语音识别，返回带时间戳的字幕段落"""
    model = get_model()
    segments, _ = model.transcribe(
        audio_path,
        language="zh",
        beam_size=5,
    )
    return [
        {
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
        }
        for seg in segments
    ]


def generate_srt(segments: list, output_path: str) -> str:
    """生成SRT字幕文件"""

    def to_srt_time(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(output_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n")
            f.write(f"{to_srt_time(seg['start'])} --> {to_srt_time(seg['end'])}\n")
            f.write(f"{seg['text']}\n\n")

    return output_path