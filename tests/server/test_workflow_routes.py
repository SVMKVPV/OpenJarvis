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
            json={
                "initial_input": "Evidence for reviewer",
                "nodes": [
                    {"id": "first", "type": "approval"},
                    {"id": "second", "type": "approval"},
                ],
            },
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
        assert "review_input" not in pending["actions"][0]["payload"]
        paused = wait_status(client, run_id, "waiting_approval")
        second_step = next(
            step for step in paused["steps"] if step["node_id"] == "second"
        )
        assert second_step["metadata"]["review_input"] == "Evidence for reviewer"
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


def test_saved_workflow_launch_key_reuses_run_after_restart(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflow.db"))
    app = FastAPI()
    app.state.workflow_system = None
    app.include_router(create_workflow_runs_router())

    with TestClient(app) as client:
        saved = client.post("/v1/workflows/definitions", json={
            "name": "Retryable launch",
            "nodes": [{"id": "format", "type": "transform"}],
        }).json()
        path = f"/v1/workflows/definitions/{saved['id']}/runs"
        payload = {"initial_input": "one request", "context": {"count": 1}}
        headers = {"Idempotency-Key": "event-1"}

        def launch():
            return client.post(path, json=payload, headers=headers)

        with ThreadPoolExecutor(max_workers=2) as workers:
            pending = [workers.submit(launch), workers.submit(launch)]
            first, second = (future.result() for future in pending)
        assert first.status_code == second.status_code == 202
        assert first.json()["id"] == second.json()["id"]
        assert client.get("/v1/workflows/runs").json()["count"] == 1

        app.state.workflow_runtime.close()
        app.state.workflow_runtime = None
        replay = launch()
        assert replay.status_code == 202
        assert replay.json()["id"] == first.json()["id"]
        conflict = client.post(
            path, json={"initial_input": "different"}, headers=headers
        )
        assert conflict.status_code == 409
        assert client.get("/v1/workflows/runs").json()["count"] == 1

        no_key = client.post(path, json=payload)
        assert no_key.status_code == 202
        assert no_key.json()["id"] != first.json()["id"]
        app.state.workflow_runtime.close()


def test_scheduled_workflow_launch_survives_app_restart(tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    from openjarvis.server.app import create_app

    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflow.db"))
    engine = MagicMock()
    with TestClient(create_app(engine, "test")) as client:
        saved = client.post("/v1/workflows/definitions", json={
            "name": "Scheduled launch",
            "nodes": [{"id": "format", "type": "transform"}],
        }).json()
        path = f"/v1/workflows/definitions/{saved['id']}/schedule"
        payload = {"initial_input": "Scheduled result", "scheduled_at": time.time() + 2}
        headers = {"Idempotency-Key": "calendar-job"}
        started = client.post(path, json=payload, headers=headers)
        assert started.status_code == 202
        run = started.json()
        assert run["status"] == "scheduled"
        assert run["scheduled_at"] == payload["scheduled_at"]
        other = client.post(path, json={**payload, "scheduled_at": time.time() + 60})
        cancelled_id = other.json()["id"]
        cancelled_path = f"/v1/workflows/runs/{cancelled_id}"
        move = {
            "scheduled_at": time.time() + 120,
            "expected_scheduled_at": other.json()["scheduled_at"],
        }
        moved = client.patch(cancelled_path + "/schedule", json=move)
        assert moved.status_code == 200
        assert moved.json()["id"] == cancelled_id
        assert moved.json()["scheduled_at"] == move["scheduled_at"]
        assert client.patch(cancelled_path + "/schedule", json=move).status_code == 409
        assert client.post(cancelled_path + "/cancel").status_code == 202
        assert client.get(cancelled_path).json()["status"] == "cancelled"
        move["expected_scheduled_at"] = move["scheduled_at"]
        assert client.patch(cancelled_path + "/schedule", json=move).status_code == 409

    restarted = create_app(engine, "test")
    with TestClient(restarted) as client:
        assert restarted.state.workflow_runtime is not None
        due_path = f"/v1/workflows/runs/{run['id']}"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = client.get(due_path).json()
            if result["status"] == "succeeded":
                break
            time.sleep(.05)
        else:
            pytest.fail(f"Scheduled run failed to complete: {result}")
        assert result["final_output"] == "Scheduled result"
        assert len(result["steps"]) == 1
        duplicate = client.post(path, json=payload, headers=headers)
        assert duplicate.status_code == 202
        assert duplicate.json()["id"] == run["id"]
        assert client.get(cancelled_path).json()["steps"] == []


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

def test_retry_with_input_preserves_original_run_and_graph(tmp_path, monkeypatch):
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.server import approval_routes
    from openjarvis.tools.approval_store import ApprovalStore

    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflow.db"))
    monkeypatch.setattr("openjarvis.core.config.DEFAULT_CONFIG_DIR", tmp_path)
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    monkeypatch.setattr(approval_routes, "_store", approvals)
    with KnowledgeStore() as store:
        store.store(
            "Corrected query matches Kestrel", source="upload", doc_type="document"
        )
    app = FastAPI()
    app.state.workflow_system = None
    app.include_router(create_workflow_runs_router())
    base = "/v1/workflows/runs"
    try:
        with TestClient(app) as client:
            def wait(run_id, state):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    run = client.get(f"{base}/{run_id}").json()
                    if run["status"] == state:
                        return run
                    time.sleep(0.02)
                pytest.fail(f"Run did not reach {state}")

            started = client.post(base, json={
                "initial_input": "NonexistentReference",
                "nodes": [{"id": "search", "type": "tool", "config": {
                    "tool_name": "knowledge_search", "query_from_input": True,
                    "source": "upload", "require_match": True,
                }}],
            })
            original_id = started.json()["id"]
            original = wait(original_id, "failed")
            retried = client.post(
                f"{base}/{original_id}/retry-with-input",
                json={"initial_input": "Kestrel"},
            )
            assert retried.status_code == 202
            updated = wait(retried.json()["id"], "succeeded")
            assert updated["parent_run_id"] == original_id
            assert updated["initial_input"] == "Kestrel"
            assert updated["graph"] == original["graph"]
            assert client.get(f"{base}/{original_id}").json() == original
            legacy = client.post(f"{base}/{original_id}/retry")
            assert legacy.status_code == 202
            legacy_run = wait(legacy.json()["id"], "failed")
            assert legacy_run["initial_input"] == original["initial_input"]
    finally:
        app.state.workflow_runtime.close()
        approvals.close()

def test_workflow_history_cursor_is_stable_when_new_runs_arrive(tmp_path, monkeypatch):
    from openjarvis.server import approval_routes
    from openjarvis.tools.approval_store import ApprovalStore

    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflow.db"))
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    monkeypatch.setattr(approval_routes, "_store", approvals)
    app = FastAPI()
    app.state.workflow_system = None
    app.include_router(create_workflow_runs_router())
    base = "/v1/workflows/runs"

    try:
        with TestClient(app) as client:
            payload = {"nodes": [{"id": "first", "type": "transform"}]}
            ids = [client.post(base, json=payload).json()["id"] for _ in range(4)]
            latest = client.get(base, params={"limit": 2}).json()["runs"]
            assert [run["id"] for run in latest] == ids[2:][::-1]
            cursor = latest[-1]["id"]
            assert client.post(base, json=payload).status_code == 202
            older = client.get(base, params={"limit": 2, "before": cursor}).json()
            assert older["before"] == cursor
            assert [run["id"] for run in older["runs"]] == ids[:2][::-1]
            definition = client.post("/v1/workflows/definitions", json=payload).json()
            schedule = f"/v1/workflows/definitions/{definition['id']}/schedule"
            first_due = client.post(schedule, json={"scheduled_at": time.time() + 600})
            second_due = client.post(
                schedule, json={"scheduled_at": time.time() + 1200}
            )
            first_id, second_id = first_due.json()["id"], second_due.json()["id"]
            due = client.get(base, params={"status": "scheduled"}).json()["runs"]
            assert [run["id"] for run in due] == [first_id, second_id]
            filtered = {"status": "scheduled", "recent": "true", "limit": 1}
            newest = client.get(base, params=filtered).json()["runs"]
            assert [run["id"] for run in newest] == [second_id]
            earlier = client.get(base, params={**filtered, "before": second_id}).json()
            assert [run["id"] for run in earlier["runs"]] == [first_id]
    finally:
        app.state.workflow_runtime.close()
        approvals.close()
