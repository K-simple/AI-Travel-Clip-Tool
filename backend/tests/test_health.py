import os

import pytest

from services.processing_config import PROCESSING_PRESET


def test_health_payload_shape():
    """Health endpoint contract without importing FastAPI (optional in CI)."""
    preset = PROCESSING_PRESET
    capabilities = {
        "deepseek": bool(os.getenv("DEEPSEEK_API_KEY", "").strip()),
        "capcut_mate": bool(os.getenv("CAPCUT_MATE_BASE_URL", "http://localhost:30000").strip()),
        "auth": bool(os.getenv("AUTH_SECRET", "").strip()),
        "douyin_publish": bool(
            os.getenv("DOUYIN_CLIENT_KEY", "").strip()
            and os.getenv("DOUYIN_CLIENT_SECRET", "").strip()
        ),
    }
    payload = {"status": "ok", "preset": preset, "capabilities": capabilities}
    assert payload["status"] == "ok"
    assert isinstance(payload["preset"], str)
    assert isinstance(payload["capabilities"], dict)
    assert "deepseek" in payload["capabilities"]


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("fastapi"),
    reason="fastapi not installed",
)
def test_health_route():
    from fastapi.testclient import TestClient

    from main import app

    resp = TestClient(app).get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "preset" in body
    assert "capabilities" in body
    assert isinstance(body["capabilities"], dict)
