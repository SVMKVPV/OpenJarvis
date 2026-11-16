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
        pending = client.get("/v1/approvals/pending").json()
        assert [action["id"] for action in pending["actions"]] == [approval_id]
        assert client.post(f"/v1/approvals/{approval_id}/approve").status_code == 200
        wait_status(client, run_id, "succeeded")
    restarted.state.workflow_runtime.close()
    approvals.close()


@pytest.mark.parametrize("terminal_status", ["failed", "cancelled", "succeeded"])
def test_terminal_workflow_approval_is_not_actionable(
    tmp_path, monkeypatch, terminal_status
) -> None:
    from openjarvis.server import approval_routes
    from openjarvis.tools.approval_store import STATUS_PENDING, ApprovalStore
    from openjarvis.workflow.runtime import WorkflowRuntime
    from openjarvis.workflow.store import WorkflowRunStore

    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    monkeypatch.setattr(approval_routes, "_store", approvals)
    runtime = WorkflowRuntime(
        system=None,
        store=WorkflowRunStore(str(tmp_path / "workflow.db")),
        approval_store=approvals,
    )
    app = FastAPI()
    app.state.workflow_runtime = runtime
    app.include_router(approval_routes.router)
    try:
        run = runtime.store.create_run(
            workflow_name="review", graph={}, initial_input="", context={}
        )
        action = approvals.queue_action(
            action_type="review",
            description="Review output",
            payload={"workflow_run_id": run["id"], "workflow_node_id": "review"},
            permission_key="review",
            tier="high",
        )
        runtime.store.pause(
            run["id"], context={"_workflow_approvals": {"review": action.id}}
        )
        if terminal_status == "cancelled":
            assert runtime.cancel(run["id"])
        else:
            runtime.store.finish(run["id"], status=terminal_status)
        with TestClient(app) as client:
            assert client.get("/v1/approvals/pending").json()["actions"] == []
            assert client.post(f"/v1/approvals/{action.id}/approve").status_code == 409
        assert approvals.get_action(action.id).status == STATUS_PENDING
    finally:
        runtime.close()
        approvals.close()


def test_saved_definition_survives_runtime_restart(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflow.db"))
    app = FastAPI()
    app.state.workflow_system = None
    app.include_router(create_workflow_runs_router())

    with TestClient(app) as client:
        response = client.post(
            "/v1/workflows/definitions",
            json={
                "name": "Reusable",
                "nodes": [{
                    "id": "format",
                    "type": "transform",
                    "transform_expr": "json_field:email",
                }],
            },
        )
        assert response.status_code == 201
        saved = response.json()
        app.state.workflow_runtime.close()
        app.state.workflow_runtime = None
        assert client.get("/v1/workflows/definitions").json()["definitions"] == [saved]
        response = client.post(
            f"/v1/workflows/definitions/{saved['id']}/runs",
            json={"initial_input": '{"email":"lead@example.com"}'},
        )
        assert response.status_code == 202
        assert response.json()["workflow_name"] == "Reusable"
        run_id = response.json()["id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            run = client.get(f"/v1/workflows/runs/{run_id}").json()
            if run["status"] == "succeeded":
                assert run["final_output"] == "lead@example.com"
                break
            assert run["status"] in {"queued", "running"}, run
            time.sleep(0.01)
        else:
            pytest.fail("Saved workflow did not finish")
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
