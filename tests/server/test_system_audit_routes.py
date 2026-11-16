from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.system_audit_routes import router  # noqa: E402


def _client(api_key: str = "") -> TestClient:
    app = FastAPI()
    app.state.api_key = api_key
    app.state.workflow_runtime = None
    app.include_router(router)
    return TestClient(app)


def test_audit_flags_missing_api_auth_without_exposing_secrets(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    response = _client().get("/v1/system/audit")

    assert response.status_code == 200
    payload = response.json()
    auth = next(
        item for item in payload["findings"] if item["id"] == "api-authentication"
    )
    assert auth["severity"] == "critical"
    assert "credential-storage" in {item["id"] for item in payload["findings"]}
    assert "secret" not in response.text.lower()


def test_audit_passes_api_auth_when_key_is_configured(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    response = _client("configured-but-never-returned").get("/v1/system/audit")

    auth = next(
        item
        for item in response.json()["findings"]
        if item["id"] == "api-authentication"
    )
    assert auth["severity"] == "pass"
    assert "configured-but-never-returned" not in response.text
