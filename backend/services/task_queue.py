"""异步任务队列（Phase B/D MVP：内存实现，可选 Redis）。"""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

_executor = ThreadPoolExecutor(max_workers=4)
_tasks: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def create_task(task_type: str, payload: Optional[Dict[str, Any]] = None) -> str:
    task_id = str(uuid.uuid4())
    with _lock:
        _tasks[task_id] = {
            "id": task_id,
            "type": task_type,
            "status": "pending",
            "progress": 0,
            "message": "排队中",
            "payload": payload or {},
            "result": None,
            "error": None,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
    return task_id


def update_task(task_id: str, **fields: Any) -> None:
    with _lock:
        task = _tasks.get(task_id)
        if not task:
            return
        task.update(fields)
        task["updated_at"] = time.time()


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        task = _tasks.get(task_id)
        return dict(task) if task else None


def run_task(task_id: str, fn: Callable[[], Any]) -> None:
    def _worker():
        update_task(task_id, status="running", progress=5, message="处理中")
        try:
            result = fn()
            update_task(
                task_id,
                status="completed",
                progress=100,
                message="完成",
                result=result,
            )
        except Exception as exc:
            update_task(
                task_id,
                status="failed",
                progress=100,
                message=str(exc),
                error=str(exc),
            )

    _executor.submit(_worker)
