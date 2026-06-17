"""测试 DeepSeek API Key 是否可用（勿提交 Git）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(".env")

import json
import os
import urllib.error
import urllib.request

from services.deepseek_client import deepseek_enabled


def main() -> int:
    print("=== DeepSeek API Key 测试 ===")
    print("Key 已配置:", deepseek_enabled())
    print("Model:", os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    base = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/")
    print("Base:", base)

    if not deepseek_enabled():
        print("失败: 未配置 DEEPSEEK_API_KEY")
        return 1

    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "只回复两个字母 OK"}],
        "max_tokens": 16,
        "stream": False,
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        reply = body["choices"][0]["message"]["content"]
        print("API 调用: 成功")
        print("模型回复:", (reply or "").strip())
        return 0
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        print("API 调用: 失败 HTTP", exc.code)
        print("详情:", detail)
        return 2
    except Exception as exc:
        print("API 调用: 失败", type(exc).__name__, str(exc)[:300])
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
