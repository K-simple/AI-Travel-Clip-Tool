"""剪映/CapCut Mate 可访问的媒体 URL 构建与探测。"""

import os
import socket
import urllib.error
import urllib.request
from typing import Optional
from urllib.parse import quote, urlencode, urlparse, urlunparse

from utils.storage_backend import public_url

API_KEY = os.getenv("API_KEY", "").strip()
DEFAULT_BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))


def detect_lan_host() -> str:
    """获取本机局域网 IP，供 CapCut Mate 拉取 /storage 资源。"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        host = sock.getsockname()[0]
        sock.close()
        if host and not host.startswith("127."):
            return host
    except Exception:
        pass
    return "127.0.0.1"


def resolve_public_media_base(explicit: Optional[str] = None) -> str:
    """解析 CapCut Mate 应使用的媒体根地址。"""
    if explicit and str(explicit).strip():
        return str(explicit).strip().rstrip("/")
    env_base = os.getenv("PUBLIC_MEDIA_BASE_URL", "").strip()
    if env_base:
        return env_base.rstrip("/")
    host = detect_lan_host()
    return f"http://{host}:{DEFAULT_BACKEND_PORT}"


def build_public_media_url(relative_or_abs: str, media_base: str) -> str:
    """将 storage 相对路径转为 CapCut Mate 可 HTTP 访问的 URL。"""
    rel = public_url(relative_or_abs.replace("\\", "/"))
    if rel.startswith("http://") or rel.startswith("https://"):
        url = rel
    else:
        base = media_base.rstrip("/")
        if not rel.startswith("/"):
            rel = f"/{rel}"
        url = f"{base}{rel}"

    if API_KEY and "/storage/" in url:
        parsed = urlparse(url)
        query = dict(
            p.split("=", 1) for p in parsed.query.split("&") if "=" in p
        ) if parsed.query else {}
        if "api_key" not in query:
            query["api_key"] = API_KEY
            url = urlunparse(
                parsed._replace(query=urlencode(query, quote_via=quote))
            )
    return url


def verify_media_url(url: str, timeout_sec: float = 8.0) -> tuple[bool, str]:
    """从本机探测媒体 URL 是否可访问（模拟 CapCut Mate 拉取）。"""
    if not url:
        return False, "URL 为空"
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status >= 400:
                return False, f"HTTP {resp.status}"
            return True, ""
    except urllib.error.HTTPError as exc:
        if exc.code in (405, 501):
            return verify_media_url_get(url, timeout_sec)
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, str(exc)


def verify_media_url_get(url: str, timeout_sec: float = 8.0) -> tuple[bool, str]:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Range", "bytes=0-1")
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status >= 400:
                return False, f"HTTP {resp.status}"
            return True, ""
    except Exception as exc:
        return False, str(exc)
