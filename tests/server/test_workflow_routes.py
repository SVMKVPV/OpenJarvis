from __future__ import annotations

import time

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.workflow_routes import create_workflow_runs_router  # noqa: E402


def test_workflow_run_routes_persist_execution(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflow.db"))
    app = FastAPI()
    app.state.workflow_runtime = None
    app.state.workflow_system = None
    app.state.bus = None
    app.include_router(create_workflow_runs_router())

    with TestClient(app) as client:
        response = client.post(
            "/v1/workflows/runs",
            json={
                "name": "api-workflow",
                "nodes": [
                    {
                        "id": "format",
                        "type": "transform",
                        "transform_expr": "first_line",
                    }
                ],
                "initial_input": "hello\nworld",
            },
        )
        assert response.status_code == 202
        run_id = response.json()["id"]

        deadline = time.monotonic() + 3
        detail = None
        while time.monotonic() < deadline:
            detail = client.get(f"/v1/workflows/runs/{run_id}")
            if detail.json()["status"] == "succeeded":
                break
            time.sleep(0.01)

        assert detail is not None
        assert detail.status_code == 200
        assert detail.json()["status"] == "succeeded"
        assert detail.json()["steps"][0]["node_id"] == "format"
        assert client.get("/v1/workflows/runs").json()["count"] == 1

    app.state.workflow_runtime.close()


def test_workflow_run_route_rejects_empty_graph(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflow.db"))
    app = FastAPI()
    app.state.workflow_runtime = None
    app.state.workflow_system = None
    app.state.bus = None
    app.include_router(create_workflow_runs_router())

    with TestClient(app) as client:
        response = client.post(
            "/v1/workflows/runs",
            json={"name": "empty", "nodes": []},
        )

    assert response.status_code == 422
