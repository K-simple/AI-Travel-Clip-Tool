"""DeepSeek OpenAI 兼容 API 客户端（支持 V4 视觉输入）。"""

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any


DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEEPSEEK_TIMEOUT_SEC = float(os.getenv("DEEPSEEK_TIMEOUT_SEC", "60"))


def deepseek_enabled() -> bool:
    return bool(os.getenv("DEEPSEEK_API_KEY", "").strip())


def is_vision_unsupported_error(exc: BaseException) -> bool:
    """当前模型/网关不支持 image_url 多模态输入时返回 True。"""
    msg = str(exc).lower()
    return "image_url" in msg or "unknown variant" in msg


def _encode_image_path(image_path: str) -> str:
    with open(image_path, "rb") as f:
        raw = f.read()
    ext = os.path.splitext(image_path)[1].lower().lstrip(".") or "jpeg"
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/{mime};base64,{b64}"


def chat_vision(
    prompt: str,
    image_paths: list[str],
    *,
    model: str | None = None,
    max_tokens: int = 256,
    temperature: float = 0.1,
) -> str:
    """发送带图片的多模态请求，返回 assistant 文本。"""
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for path in image_paths:
        if path and os.path.isfile(path):
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _encode_image_path(path)},
                }
            )

    payload = {
        "model": model or DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    req = urllib.request.Request(
        f"{DEEPSEEK_API_BASE}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=DEEPSEEK_TIMEOUT_SEC) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API 错误 {exc.code}: {detail}") from exc

    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError(f"DeepSeek 无响应: {body}")
    message = choices[0].get("message") or {}
    return str(message.get("content") or "").strip()
