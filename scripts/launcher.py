#!/usr/bin/env python3
"""
AI Travel Cut 便携版启动器。
可单独运行，也可用 PyInstaller 打成 AITravelCut.exe。

目录结构（与 exe 同级）：
  app/
    backend/          FastAPI + venv
    frontend/         next standalone（含 server.js）
    node/node.exe     便携 Node（可选，否则用系统 node）
    ffmpeg/ffmpeg.exe 便携 ffmpeg（可选，否则用 PATH）
  data/               用户数据（storage、数据库），首次运行自动创建
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

BACKEND_PORT = int(os.environ.get("AITC_BACKEND_PORT", "8000"))
FRONTEND_PORT = int(os.environ.get("AITC_FRONTEND_PORT", "3000"))
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
FRONTEND_URL = f"http://127.0.0.1:{FRONTEND_PORT}"

PROCS: list[subprocess.Popen] = []


def root_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    return root_dir() / "app"


def data_dir() -> Path:
    return root_dir() / "data"


def log(msg: str) -> None:
    print(msg, flush=True)


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except Exception:
        return False


def wait_url(url: str, label: str, timeout_sec: int = 120) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if http_ok(url):
            log(f"[OK] {label} {url}")
            return True
        time.sleep(1)
    log(f"[FAIL] {label} 启动超时: {url}")
    return False


def find_node() -> str:
    bundled = app_dir() / "node" / "node.exe"
    if bundled.is_file():
        return str(bundled)
    found = shutil.which("node")
    if found:
        return found
    raise FileNotFoundError(
        "未找到 Node.js。请将 node.exe 放到 app/node/node.exe，或安装 Node 18+。"
    )


def find_ffmpeg() -> str | None:
    bundled = app_dir() / "ffmpeg" / "ffmpeg.exe"
    if bundled.is_file():
        return str(bundled.parent)
    found = shutil.which("ffmpeg")
    if found:
        return str(Path(found).parent)
    return None


def find_python() -> str:
    bundled = app_dir() / "backend" / "venv" / "Scripts" / "python.exe"
    if bundled.is_file():
        return str(bundled)
    dev = root_dir() / "backend" / "venv" / "Scripts" / "python.exe"
    if dev.is_file():
        return str(dev)
    raise FileNotFoundError(
        "未找到 Python 环境。打包时请包含 app/backend/venv，或在本机先创建 venv。"
    )


def backend_root() -> Path:
    packaged = app_dir() / "backend"
    if (packaged / "main.py").is_file():
        return packaged
    dev = root_dir() / "backend"
    if (dev / "main.py").is_file():
        return dev
    raise FileNotFoundError("未找到 backend/main.py")


def frontend_root() -> Path:
    standalone = app_dir() / "frontend"
    if (standalone / "server.js").is_file():
        return standalone
    dev = root_dir() / "frontend" / ".next" / "standalone"
    if (dev / "server.js").is_file():
        return dev
    raise FileNotFoundError(
        "未找到 Next standalone。请先运行 scripts/build-portable.ps1 构建前端。"
    )


def prepare_data() -> None:
    data = data_dir()
    storage = data / "storage"
    for sub in ("templates", "assets", "thumbnails", "exports", "temp"):
        (storage / sub).mkdir(parents=True, exist_ok=True)

    backend = backend_root()
    env_example = backend / ".env.example"
    env_target = backend / ".env"
    if not env_target.is_file() and env_example.is_file():
        shutil.copy(env_example, env_target)

    # 用户数据放到 data/，避免写进 app/backend（方便升级覆盖 app 目录）
    backend_storage = backend / "storage"
    if not backend_storage.exists():
        if os.name == "nt":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(backend_storage), str(storage)],
                check=False,
                capture_output=True,
            )
        else:
            try:
                backend_storage.symlink_to(storage, target_is_directory=True)
            except OSError:
                shutil.copytree(storage, backend_storage, dirs_exist_ok=True)

    db_path = (data / "ai_travel_cut.db").resolve()
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ.setdefault("PROCESSING_PRESET", "budget")


def spawn(cmd: list[str], *, cwd: Path, env: dict[str, str], name: str) -> subprocess.Popen:
    log(f"[START] {name}: {' '.join(cmd)}")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        creationflags=flags,
    )
    PROCS.append(proc)
    return proc


def start_backend(env: dict[str, str]) -> subprocess.Popen:
    python = find_python()
    backend = backend_root()
    env = env.copy()
    env["PYTHONUNBUFFERED"] = "1"
    return spawn(
        [python, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", f"--port={BACKEND_PORT}"],
        cwd=backend,
        env=env,
        name="backend",
    )


def start_frontend(env: dict[str, str]) -> subprocess.Popen:
    node = find_node()
    frontend = frontend_root()
    env = env.copy()
    env["PORT"] = str(FRONTEND_PORT)
    env["HOSTNAME"] = "127.0.0.1"
    env.setdefault("NEXT_PUBLIC_API_BASE", BACKEND_URL)
    return spawn(
        [node, "server.js"],
        cwd=frontend,
        env=env,
        name="frontend",
    )


def shutdown() -> None:
    for proc in reversed(PROCS):
        if proc.poll() is None:
            proc.terminate()
    for proc in reversed(PROCS):
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def check_prerequisites() -> bool:
    ok = True
    try:
        find_python()
    except FileNotFoundError as exc:
        log(f"[ERROR] {exc}")
        ok = False
    try:
        find_node()
    except FileNotFoundError as exc:
        log(f"[ERROR] {exc}")
        ok = False
    try:
        backend_root()
        frontend_root()
    except FileNotFoundError as exc:
        log(f"[ERROR] {exc}")
        ok = False
    ffmpeg_dir = find_ffmpeg()
    if not ffmpeg_dir:
        log("[WARN] 未找到 ffmpeg，视频处理功能将不可用。")
        log("       请下载 ffmpeg 并放到 app/ffmpeg/ffmpeg.exe")
    return ok


def main() -> int:
    log("=== AI Travel Cut 便携版启动器 ===")
    log(f"根目录: {root_dir()}")

    if not check_prerequisites():
        log("\n启动失败：缺少运行环境。请参考 docs/PACKAGING-WINDOWS.md 重新打包。")
        input("按回车退出...")
        return 1

    prepare_data()
    env = os.environ.copy()
    env["DATABASE_URL"] = os.environ.get("DATABASE_URL", "")
    env.setdefault("PROCESSING_PRESET", "budget")
    ffmpeg_dir = find_ffmpeg()
    if ffmpeg_dir:
        env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")

    atexit.register(shutdown)
    if os.name == "nt":
        signal.signal(signal.SIGBREAK, lambda *_: sys.exit(0))

    try:
        start_backend(env)
        if not wait_url(f"{BACKEND_URL}/health", "后端", timeout_sec=180):
            return 1

        start_frontend(env)
        if not wait_url(FRONTEND_URL, "前端", timeout_sec=120):
            return 1

        editor = f"{FRONTEND_URL}/editor"
        log(f"\n正在打开浏览器: {editor}")
        webbrowser.open(editor)
        log("\n服务运行中。关闭本窗口即可停止（或 Ctrl+C）。")
        log(f"  前端: {FRONTEND_URL}")
        log(f"  后端: {BACKEND_URL}")
        log(f"  数据: {data_dir()}")

        while True:
            time.sleep(2)
            for proc in PROCS:
                if proc.poll() is not None:
                    log(f"[ERROR] 子进程异常退出 code={proc.returncode}")
                    return proc.returncode or 1
    except KeyboardInterrupt:
        log("\n正在停止...")
        return 0
    finally:
        shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
