"""可选 JWT 账号体系（Phase D MVP）。设置 AUTH_SECRET 启用。"""

import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter()

_USERS: dict = {}
_AUTH_SECRET = os.getenv("AUTH_SECRET", "")


class AuthRegister(BaseModel):
    username: str
    password: str


class AuthLogin(BaseModel):
    username: str
    password: str


def _enabled() -> bool:
    return bool(_AUTH_SECRET)


@router.get("/status")
def auth_status():
    return {"enabled": _enabled(), "provider": "local-jwt-stub"}


@router.post("/register")
def register(body: AuthRegister):
    if not _enabled():
        raise HTTPException(status_code=503, detail="未配置 AUTH_SECRET，鉴权未启用")
    if body.username in _USERS:
        raise HTTPException(status_code=400, detail="用户已存在")
    _USERS[body.username] = {
        "id": str(uuid.uuid4()),
        "password": body.password,
        "created_at": time.time(),
    }
    return {"success": True, "username": body.username}


@router.post("/login")
def login(body: AuthLogin):
    if not _enabled():
        return {"success": True, "token": "anonymous", "auth": "disabled"}
    user = _USERS.get(body.username)
    if not user or user["password"] != body.password:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = f"{body.username}:{int(time.time())}:{_AUTH_SECRET[:8]}"
    return {"success": True, "token": token, "user_id": user["id"]}
