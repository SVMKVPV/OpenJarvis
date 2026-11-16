from __future__ import annotations

import time

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.workflow_routes import create_workflow_runs_router  # noqa: E402


def test_approval_reopens_runtime_after_restart(tmp_path, monkeypatch) -> None:
    from openjarvis.server import approval_routes
    from openjarvis.tools.approval_store import ApprovalStore

    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflow.db"))
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    monkeypatch.setattr(approval_routes, "_store", approvals)

    def new_app():
        app = FastAPI()
        app.state.workflow_system = None
        app.include_router(create_workflow_runs_router())
        app.include_router(approval_routes.router)
        return app

    def wait_status(client, run_id, expected):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            run = client.get(f"/v1/workflows/runs/{run_id}").json()
            if run["status"] == expected:
                return run
            time.sleep(0.01)
        pytest.fail(f"Run did not reach {expected}")

    original = new_app()
    with TestClient(original) as client:
        response = client.post(
            "/v1/workflows/runs",
            json={"nodes": [{"id": "review", "type": "approval"}]},
        )
        assert response.status_code == 202
        run_id = response.json()["id"]
        paused = wait_status(client, run_id, "waiting_approval")
    original.state.workflow_runtime.close()

    restarted = new_app()
    with TestClient(restarted) as client:
        approval_id = paused["steps"][0]["metadata"]["approval_id"]
        assert client.post(f"/v1/approvals/{approval_id}/approve").status_code == 200
        wait_status(client, run_id, "succeeded")
    restarted.state.workflow_runtime.close()
    approvals.close()


def test_saved_definition_survives_runtime_restart(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflow.db"))
    app = FastAPI()
    app.state.workflow_system = None
    app.include_router(create_workflow_runs_router())

    with TestClient(app) as client:
        response = client.post(
            "/v1/workflows/definitions",
            json={"name": "Reusable", "nodes": [{"id": "format", "type": "transform"}]},
        )
        assert response.status_code == 201
        saved = response.json()
        app.state.workflow_runtime.close()
        app.state.workflow_runtime = None
        assert client.get("/v1/workflows/definitions").json()["definitions"] == [saved]
        response = client.post(
            f"/v1/workflows/definitions/{saved['id']}/runs",
            json={"initial_input": "new input"},
        )
        assert response.status_code == 202
        assert response.json()["workflow_name"] == "Reusable"
        assert response.json()["initial_input"] == "new input"
        app.state.workflow_runtime.close()


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
