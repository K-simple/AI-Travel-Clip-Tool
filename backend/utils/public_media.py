"""剪映/CapCut Mate 可访问的媒体 URL 构建与探测。"""

import os
import socket
import urllib.error
import urllib.request
from typing import Optional
from urllib.parse import quote, unquote, urlencode, urlparse, urlunparse

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
    env_base = os.getenv("PUBLIC_MEDIA_BASE_URL", "").strip()
    if env_base:
        base = env_base.rstrip("/")
    elif explicit and str(explicit).strip():
        base = str(explicit).strip().rstrip("/")
    else:
        base = f"http://127.0.0.1:{DEFAULT_BACKEND_PORT}"

    base = base.replace("://localhost", "://127.0.0.1").replace("://[::1]", "://127.0.0.1")

    mate_url = os.getenv("CAPCUT_MATE_BASE_URL", "http://127.0.0.1:30000")
    mate_local = "127.0.0.1" in mate_url or "localhost" in mate_url.lower()
    if mate_local and "127.0.0.1" not in base and not env_base:
        base = f"http://127.0.0.1:{DEFAULT_BACKEND_PORT}"
    return base


def build_public_media_url(relative_or_abs: str, media_base: str) -> str:
    """将 storage 相对路径转为 CapCut Mate 可 HTTP 访问的 URL。"""
    raw = str(relative_or_abs or "").replace("\\", "/")
    if raw.startswith("http://") or raw.startswith("https://"):
        url = raw
    else:
        if (len(raw) > 1 and raw[1] == ":") or (
            raw.startswith("/") and "/storage/" not in raw
        ):
            raw = _storage_relative_path(os.path.abspath(raw.replace("/", os.sep)))
        rel = public_url(raw)
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


def _storage_relative_path(abs_path: str) -> str:
    norm = os.path.abspath(str(abs_path or "")).replace("\\", "/")
    idx = norm.find("/storage/")
    if idx >= 0:
        return norm[idx:]
    if norm.startswith("storage/"):
        return f"/{norm}"
    return norm


def build_capcut_clip_url(abs_path: str, media_base: str) -> str:
    """
    构建 CapCut Mate add_videos 可接受的 http(s) 片段 URL。
    CapCut Mate 的 video_infos 校验要求 video_url 以 http:// 或 https:// 开头。
    """
    return ensure_http_video_url(abs_path, media_base)


def ensure_http_video_url(url_or_path: str, media_base: str | None = None) -> str:
    """将本地路径 / file:// / 相对 storage 路径统一为 http(s) URL。"""
    raw = str(url_or_path or "").strip()
    if not raw:
        raise RuntimeError("素材 URL 为空")

    base = (media_base or resolve_public_media_base()).rstrip("/")

    if raw.startswith(("http://", "https://")):
        fixed = raw.replace("://localhost", "://127.0.0.1").replace("://[::1]", "://127.0.0.1")
        # 修复错误拼接：/storage/E:/...
        if "/storage/" in fixed and ":/" in fixed.split("/storage/", 1)[-1][:4]:
            local = resolve_local_capcut_path(fixed) or _abs_path_from_storage_url(fixed)
            if local:
                return build_public_media_url(_storage_relative_path(local), base)
        return fixed

    if raw.startswith("file://"):
        local = resolve_local_capcut_path(raw)
        if not local:
            raise RuntimeError(f"无法解析本地素材 URL: {raw}")
        return build_public_media_url(_storage_relative_path(local), base)

    if raw.startswith("/storage/"):
        return f"{base}{raw}"

    norm = os.path.abspath(raw.replace("/", os.sep))
    if os.path.isfile(norm):
        return build_public_media_url(_storage_relative_path(norm), base)

    raise RuntimeError(f"素材 URL 格式无效: {raw}")


def _abs_path_from_storage_url(url: str) -> str | None:
    """从错误的 /storage/E:/... URL 中提取本地绝对路径。"""
    try:
        parsed = urlparse(url)
        path = unquote(parsed.path or "")
        marker = "/storage/"
        idx = path.find(marker)
        if idx < 0:
            return None
        tail = path[idx + len(marker) :]
        if len(tail) > 2 and tail[1] == ":":
            return os.path.abspath(tail)
    except Exception:
        return None
    return None


def is_local_capcut_url(url: str) -> bool:
    return str(url or "").lower().startswith("file://")


def resolve_local_capcut_path(url: str) -> str | None:
    """从 file:// URL 解析本地绝对路径（供 CapCut Mate 侧复用）。"""
    if not is_local_capcut_url(url):
        return None
    parsed = urlparse(str(url))
    raw = unquote(parsed.path or "")
    if os.name == "nt" and raw.startswith("/") and len(raw) > 2 and raw[2] == ":":
        raw = raw[1:]
    norm = os.path.abspath(raw)
    return norm if os.path.isfile(norm) else None


def verify_media_url(url: str, timeout_sec: float = 8.0) -> tuple[bool, str]:
    """从本机探测媒体 URL 是否可访问（模拟 CapCut Mate 拉取）。"""
    local = resolve_local_capcut_path(url)
    if local:
        return True, ""
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
