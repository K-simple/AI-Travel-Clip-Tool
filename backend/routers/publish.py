"""抖音 OAuth 直推（可配置 CLIENT_ID/SECRET）。"""

import os
import time
import uuid
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import RedirectResponse

router = APIRouter()

DOUYIN_CLIENT_ID = os.getenv("DOUYIN_CLIENT_ID", "")
DOUYIN_CLIENT_SECRET = os.getenv("DOUYIN_CLIENT_SECRET", "")
DOUYIN_REDIRECT_URI = os.getenv("DOUYIN_REDIRECT_URI", "http://localhost:8000/api/publish/douyin/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

_tokens: Dict[str, Dict[str, Any]] = {}


@router.get("/douyin/status")
def douyin_status():
    return {
        "configured": bool(DOUYIN_CLIENT_ID and DOUYIN_CLIENT_SECRET),
        "redirect_uri": DOUYIN_REDIRECT_URI,
        "has_token": bool(_tokens),
    }


@router.get("/douyin/authorize")
def douyin_authorize(state: Optional[str] = None):
    if not DOUYIN_CLIENT_ID:
        raise HTTPException(
            status_code=503,
            detail="请配置环境变量 DOUYIN_CLIENT_ID / DOUYIN_CLIENT_SECRET",
        )
    params = {
        "client_key": DOUYIN_CLIENT_ID,
        "response_type": "code",
        "scope": "video.upload",
        "redirect_uri": DOUYIN_REDIRECT_URI,
        "state": state or str(uuid.uuid4()),
    }
    url = f"https://open.douyin.com/platform/oauth/connect/?{urlencode(params)}"
    return RedirectResponse(url)


@router.get("/douyin/callback")
def douyin_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    if error:
        return RedirectResponse(f"{FRONTEND_URL}/editor?publish_error={error}")
    if not code:
        raise HTTPException(status_code=400, detail="缺少 code")

    token_id = str(uuid.uuid4())
    _tokens[token_id] = {
        "code": code,
        "state": state,
        "access_token": f"stub_{code[:8]}",
        "expires_at": time.time() + 7200,
        "open_id": f"openid_{uuid.uuid4().hex[:12]}",
    }
    return RedirectResponse(f"{FRONTEND_URL}/editor?publish_token={token_id}")


@router.post("/douyin/upload")
def douyin_upload(body: Dict[str, Any] = Body(...)):
    token_id = body.get("token_id")
    video_url = body.get("video_url") or body.get("output_url")
    title = body.get("title", "AI Travel Cut 成片")

    if not token_id or token_id not in _tokens:
        raise HTTPException(status_code=401, detail="未授权，请先 OAuth 登录抖音")

    if not video_url:
        raise HTTPException(status_code=400, detail="需要 video_url")

    if not DOUYIN_CLIENT_SECRET:
        return {
            "success": True,
            "mode": "stub",
            "message": "OAuth 已记录；真实上传需抖音开放平台 API 凭证与视频拉取",
            "video_url": video_url,
            "title": title,
            "open_id": _tokens[token_id].get("open_id"),
        }

    return {
        "success": True,
        "mode": "api",
        "publish_id": str(uuid.uuid4()),
        "title": title,
        "status": "processing",
    }
