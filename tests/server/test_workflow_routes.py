from __future__ import annotations

import time

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.workflow_routes import create_workflow_runs_router  # noqa: E402


def test_parallel_approvals_survive_runtime_restart(tmp_path, monkeypatch) -> None:
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
            json={"nodes": [
                {"id": "first", "type": "approval"},
                {"id": "second", "type": "approval"},
            ]},
        )
        assert response.status_code == 202
        run_id = response.json()["id"]
        paused = wait_status(client, run_id, "waiting_approval")
        approvals_by_node = paused["context"]["_workflow_approvals"]
        first_id = approvals_by_node["first"]
        second_id = approvals_by_node["second"]
        assert client.post(f"/v1/approvals/{first_id}/approve").status_code == 200
        pending = client.get("/v1/approvals/pending").json()
        assert [action["id"] for action in pending["actions"]] == [second_id]
    original.state.workflow_runtime.close()

    restarted = new_app()
    with TestClient(restarted) as client:
        pending = client.get("/v1/approvals/pending").json()
        assert [action["id"] for action in pending["actions"]] == [second_id]
        assert client.post(f"/v1/approvals/{second_id}/approve").status_code == 200
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
        replacement = {
            "name": "Reusable revised",
            "nodes": [{"id": "next", "type": "transform"}],
        }
        response = client.put(
            f"/v1/workflows/definitions/{saved['id']}",
            json={**replacement, "expected_revision": saved["revision"]},
        )
        assert response.status_code == 200
        revised = response.json()
        assert revised["id"] == saved["id"]
        assert revised["created_at"] == saved["created_at"]
        assert revised["graph"]["name"] == replacement["name"]
        definition_path = f"/v1/workflows/definitions/{saved['id']}"
        stale = client.put(
            definition_path,
            json={
                **replacement,
                "name": "Stale",
                "expected_revision": saved["revision"],
            },
        )
        assert stale.status_code == 409
        assert revised["revision"] != saved["revision"]
        invalid = client.put(
            definition_path,
            json={"nodes": [{"id": "bad", "type": "missing_type"}]},
        )
        assert invalid.status_code == 400
        definitions = client.get("/v1/workflows/definitions").json()["definitions"]
        assert definitions == [revised]
        launched = client.post(
            f"{definition_path}/runs", json={"initial_input": "Revised input"}
        )
        assert launched.status_code == 202
        new_run_id = launched.json()["id"]
        new_run = client.get(f"/v1/workflows/runs/{new_run_id}").json()
        assert new_run["graph"] == revised["graph"]
        history = client.get(f"/v1/workflows/runs/{run_id}").json()
        assert history["graph"] == saved["graph"]
        missing = client.put("/v1/workflows/definitions/missing", json=replacement)
        assert missing.status_code == 404
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


def test_workflow_launch_routes_return_503_after_runtime_closes(tmp_path) -> None:
    from openjarvis.tools.approval_store import ApprovalStore
    from openjarvis.workflow.runtime import WorkflowRuntime
    from openjarvis.workflow.store import WorkflowRunStore

    app = FastAPI()
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    runtime = WorkflowRuntime(
        system=None,
        store=WorkflowRunStore(str(tmp_path / "workflow.db")),
        approval_store=approvals,
    )
    app.state.workflow_runtime = runtime
    app.include_router(create_workflow_runs_router())
    runtime.close()
    approvals.close()
    with TestClient(app) as client:
        requests = [
            ("/v1/workflows/runs", {"nodes": [{"id": "a", "type": "transform"}]}),
            ("/v1/workflows/runs/sample/retry", {}),
            ("/v1/workflows/runs/sample/resume", {}),
            ("/v1/workflows/definitions/sample/runs", {}),
        ]
        for path, body in requests:
            response = client.post(path, json=body)
            assert response.status_code == 503, path
            assert response.json()["detail"] == "Workflow runtime is stopping"


def test_legacy_workflow_can_be_opened_and_repaired(tmp_path, monkeypatch) -> None:
    from openjarvis.server import approval_routes
    from openjarvis.tools.approval_store import ApprovalStore

    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflow.db"))
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    monkeypatch.setattr(approval_routes, "_store", approvals)
    app = FastAPI()
    app.state.workflow_system = None
    app.include_router(create_workflow_runs_router())
    try:
        with TestClient(app) as client:
            client.get("/v1/workflows/definitions").raise_for_status()
            store = app.state.workflow_runtime.store
            format_node = {
                "id": "_input", "type": "transform", "transform_expr": "first_line"
            }
            result_node = {
                "id": "result", "type": "transform", "transform_expr": "concatenate"
            }
            legacy = store.save_definition({
                "name": "Legacy",
                "nodes": [format_node, result_node],
                "edges": [{"source": "_input", "target": "result"}],
            })
            path = f"/v1/workflows/definitions/{legacy['id']}"
            assert client.get(path).json() == legacy
            launch = client.post(f"{path}/runs", json={})
            assert launch.status_code == 400
            assert "reserved for the workflow input" in launch.json()["detail"]
            assert store.list_runs() == []
            repair = client.put(path, json={
                "name": "Legacy",
                "nodes": [{**format_node, "id": "format"}, result_node],
                "edges": [{"source": "format", "target": "result"}],
                "expected_revision": legacy["revision"],
            })
            assert repair.status_code == 200
            started = client.post(
                f"{path}/runs", json={"initial_input": "first\nsecond"}
            )
            assert started.status_code == 202
            run_id = started.json()["id"]
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                run = client.get(f"/v1/workflows/runs/{run_id}").json()
                if run["status"] == "succeeded":
                    assert run["final_output"] == "first"
                    assert [step["node_id"] for step in run["steps"]] == [
                        "format", "result",
                    ]
                    break
                assert run["status"] in {"queued", "running"}, run
                time.sleep(0.01)
            else:
                pytest.fail("Repaired workflow did not finish")
    finally:
        app.state.workflow_runtime.close()
        approvals.close()


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
