from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.workflow_routes import create_workflow_runs_router  # noqa: E402


def test_import_attachments_from_the_selected_gmail_message(tmp_path, monkeypatch):
    import base64

    from openjarvis.connectors import gmail
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.server import upload_router

    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    db_path = tmp_path / "knowledge.db"
    with KnowledgeStore(db_path) as store:
        store.store(
            "Please review the attached invoice", source="gmail",
            source_id="abc123", doc_id="gmail:abc123", doc_type="email",
        )

    invoice_content = b"Invoice M-42, total AUD 132.00"

    def provider(operation, credentials, message_id, *args):
        assert message_id == "abc123"
        if operation is gmail._gmail_api_get_message:
            return {"payload": {"parts": [{
                "filename": "invoice.csv",
                "body": {"attachmentId": "invoice-id", "size": 32},
            }]}}
        assert operation is gmail._gmail_api_get_attachment and args == ("invoice-id",)
        return base64.urlsafe_b64encode(invoice_content).decode()

    monkeypatch.setattr(gmail, "_call_with_refresh", provider)
    app = FastAPI()
    app.include_router(upload_router.router)
    with TestClient(app) as client:
        base = "/v1/connectors/upload/ingest/gmail"
        assert client.post(f"{base}/other").status_code == 404
        with ThreadPoolExecutor(max_workers=3) as pool:
            imports = list(pool.map(client.post, [f"{base}/abc123"] * 3))
        result = imports[0]
        result.raise_for_status()
        assert result.json()["chunks_added"] == 1
        assert all(item.status_code == 200 and item.json() == result.json()
                   for item in imports)
        reused = client.post(f"{base}/abc123")
        assert reused.status_code == 200 and reused.json() == result.json()
        invoice_content = b"Invoice M-42, total AUD 142.00"
        revised = client.post(f"{base}/abc123")
        revised.raise_for_status()
        assert revised.json()["reference"] != result.json()["reference"]
    with KnowledgeStore(db_path) as store:
        evidence, = store.uploaded_evidence(result.json()["reference"], limit=5)
        assert evidence.content == "Invoice M-42, total AUD 132.00"
        assert evidence.metadata["title"].startswith("invoice.csv")
        assert evidence.metadata["url"] == "https://mail.google.com/mail/u/0/#all/abc123"
        new_evidence, = store.uploaded_evidence(revised.json()["reference"], limit=5)
        assert new_evidence.content == "Invoice M-42, total AUD 142.00"


def test_workflow_reviews_only_the_selected_upload_batch(tmp_path, monkeypatch):
    from openjarvis.server import approval_routes, upload_router
    from openjarvis.tools.approval_store import ApprovalStore

    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflow.db"))
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    monkeypatch.setattr(approval_routes, "_store", approvals)
    app = FastAPI()
    app.state.workflow_system = None
    app.include_router(create_workflow_runs_router())
    app.include_router(upload_router.router)

    with TestClient(app) as client:
        url = "/v1/connectors/upload/ingest/files"
        response = client.post(url, files=[
            ("files", ("draft.txt", b"Draft promises delivery in 24 hours")),
            ("files", ("approved.txt", b"Approved delivery target is 48 hours")),
        ])
        response.raise_for_status()
        batch = response.json()
        assert batch["chunks_added"] == 2
        assert client.post(url, files=[
            ("files", ("draft.txt", b"Unrelated delivery guarantee")),
        ]).status_code == 200
        result = client.post("/v1/workflows/runs", json={
            "initial_input": batch["reference"],
            "nodes": [
                {"id": "source", "type": "tool", "config": {
                    "tool_name": "knowledge_search", "query_from_input": True,
                    "source": "upload", "require_match": True,
                }},
                {"id": "review", "type": "approval"},
            ],
            "edges": [{"source": "source", "target": "review"}],
        })
        assert result.status_code == 202
        run_url = f"/v1/workflows/runs/{result.json()['id']}"
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                run = client.get(run_url).json()
                if run["status"] == "waiting_approval":
                    break
                time.sleep(0.01)
            else:
                pytest.fail(f"Upload review did not reach approval: {run}")
            evidence = run["steps"][1]["metadata"]["review_input"]
            assert "draft.txt" in evidence and "24 hours" in evidence
            assert "approved.txt" in evidence and "48 hours" in evidence
            assert "Unrelated" not in evidence
        finally:
            app.state.workflow_runtime.close()
            approvals.close()


def test_recurring_workflow_catches_up_once_after_restart(tmp_path, monkeypatch):
    from openjarvis.server import approval_routes
    from openjarvis.server.workflow_routes import start_workflow_scheduler
    from openjarvis.tools.approval_store import ApprovalStore
    from openjarvis.workflow.store import WorkflowRunStore

    db_path = str(tmp_path / "workflow.db")
    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", db_path)
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    monkeypatch.setattr(approval_routes, "_store", approvals)

    def new_app():
        app = FastAPI()
        app.state.workflow_system = None
        app.include_router(create_workflow_runs_router())
        return app

    original = new_app()
    with TestClient(original) as client:
        definition = client.post("/v1/workflows/definitions", json={
            "name": "Recurring review",
            "nodes": [{"id": "review", "type": "approval"}],
        }).json()
        url = f"/v1/workflows/definitions/{definition['id']}/recurrences"
        request = {"first_due_at": time.time() + 120, "interval_seconds": 60}
        invalid = client.post(url, json={**request, "interval_seconds": 0})
        assert invalid.status_code == 422
        created = client.post(url, json=request)
        assert created.status_code == 201
        assert client.get(url).json()["recurrences"] == [created.json()]
        upcoming_url = "/v1/workflows/recurrences/upcoming"
        assert client.get(upcoming_url).json()["recurrences"] == [{
            "id": created.json()["id"],
            "definition_id": definition["id"],
            "next_due_at": request["first_due_at"],
            "interval_seconds": 60,
            "workflow_name": "Recurring review",
            "skipped_while_active": 0,
            "skipped_during_catchup": 0,
        }]
        schedule_url = f"{url}/{created.json()['id']}"
        paused = client.patch(schedule_url, json={"paused": True})
        assert paused.status_code == 200 and paused.json()["paused"] is True
        assert client.get(upcoming_url).json()["recurrences"] == []
        resumed = client.patch(schedule_url, json={"paused": False})
        assert resumed.status_code == 200 and resumed.json() == created.json()
        changes = {
            "first_due_at": time.time() + 360,
            "interval_seconds": 180,
            "initial_input": "Updated recurring input",
            "expected_revision": 0,
        }
        edited = client.put(schedule_url, json=changes)
        assert edited.status_code == 200
        updated = edited.json()
        assert updated["id"] == created.json()["id"] and updated["revision"] == 1
        assert updated["initial_input"] == changes["initial_input"]
        assert updated["interval_seconds"] == 180
        assert client.put(schedule_url, json=changes).status_code == 409
        upcoming, = client.get(upcoming_url).json()["recurrences"]
        assert upcoming["interval_seconds"] == 180
        original.state.workflow_runtime.close()

    offline_store = WorkflowRunStore(db_path)
    overdue = offline_store.save_recurrence(
        definition["id"], "Recurring evidence", time.time() - 190, 60,
    )
    offline_store.close()
    restarted = new_app()
    start_workflow_scheduler(restarted.state)
    try:
        with TestClient(restarted) as client:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                runs = client.get("/v1/workflows/runs").json()["runs"]
                if runs and runs[0]["status"] == "waiting_approval":
                    break
                time.sleep(0.01)
            else:
                pytest.fail("Recurring run did not reach its approval checkpoint")
            assert len(runs) == 1
            assert runs[0]["scheduled_at"] == overdue["next_due_at"] + 180
            scoped = client.get("/v1/workflows/runs", params={
                "recurrence_id": overdue["id"], "status": "waiting_approval",
            }).json()
            assert scoped["runs"] == runs
            assert scoped["recurrence_id"] == overdue["id"]
            assert client.get("/v1/workflows/runs", params={
                "recurrence_id": updated["id"],
            }).json()["runs"] == []
            schedule = client.get(url).json()["recurrences"][0]
            assert schedule["next_due_at"] == overdue["next_due_at"] + 240
            upcoming = client.get(upcoming_url).json()["recurrences"][0]
            assert upcoming["id"] == overdue["id"]
            assert upcoming["skipped_during_catchup"] == 3
            assert upcoming["skipped_while_active"] == 0
            assert client.delete(f"{url}/{overdue['id']}").status_code == 204
            assert client.get(url).json()["recurrences"] == [updated]
    finally:
        restarted.state.workflow_runtime.close()
        approvals.close()


@pytest.mark.parametrize("cancel_after_restart", [False, True])
def test_parallel_approvals_survive_runtime_restart(
    tmp_path, monkeypatch, cancel_after_restart
) -> None:
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
                    {"id": "second", "type": "approval", "config": {"payload": {
                        "review_checklist": ["Check source", "", "Verify amount"],
                        "require_review_checklist": True,
                        "decision_checks": ["Untrusted imported assertion"],
                    }}},
                ],
            },
        )
        assert response.status_code == 202
        run_id = response.json()["id"]
        paused = wait_status(client, run_id, "waiting_approval")
        approvals_by_node = paused["context"]["_workflow_approvals"]
        first_id = approvals_by_node["first"]
        second_id = approvals_by_node["second"]
        review_note = "First source verified."
        assert client.post(
            f"/v1/approvals/{first_id}/decide-with-note",
            json={"decision": "approve", "note": review_note},
        ).status_code == 200
        pending = client.get("/v1/approvals/pending").json()
        assert [action["id"] for action in pending["actions"]] == [second_id]
    original.state.workflow_runtime.close()

    restarted = new_app()
    with TestClient(restarted) as client:
        pending = client.get("/v1/approvals/pending").json()
        assert [action["id"] for action in pending["actions"]] == [second_id]
        assert "review_input" not in pending["actions"][0]["payload"]
        assert "decision_checks" not in pending["actions"][0]["payload"]
        if cancel_after_restart:
            path = f"/v1/workflows/runs/{run_id}/cancel"
            assert client.post(path).status_code == 202
            cancelled = wait_status(client, run_id, "cancelled")
            recorded, = cancelled["review_decisions"]
            assert recorded["approval_id"] == first_id
            assert recorded["status"] == "approved"
            assert recorded["note"] == review_note
            restarted.state.workflow_runtime.close()
            approvals.close()
            return
        paused = wait_status(client, run_id, "waiting_approval")
        second_step = next(
            step for step in paused["steps"] if step["node_id"] == "second"
        )
        assert second_step["metadata"]["review_input"] == "Evidence for reviewer"
        path = f"/v1/approvals/{second_id}/decide-with-note"
        invalid = client.post(path, json={"decision": "approve", "checked_items": [2]})
        assert invalid.status_code == 422
        assert client.post(f"/v1/approvals/{second_id}/approve").status_code == 422
        partial = client.post(path, json={"decision": "approve", "checked_items": [1]})
        assert partial.status_code == 422
        assert "Complete every reviewer check" in partial.json()["detail"]
        assert wait_status(client, run_id, "waiting_approval")
        note = {
            "decision": "approve", "note": "Evidence checked against the source.",
            "checked_items": [1, 0],
        }
        assert client.post(path, json=note).status_code == 200
        repeat = client.post(path, json={**note, "note": "Replacement"})
        assert repeat.status_code == 409
        completed = wait_status(client, run_id, "succeeded")
        assert any(
            step["node_id"] == "second"
            and step["metadata"].get("decision_note") == note["note"]
            and step["metadata"].get("decision_checks")
            == ["Check source", "Verify amount"]
            for step in completed["steps"]
        )
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


def test_pinned_recurring_schedule_keeps_reviewed_graph(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflow.db"))
    app = FastAPI()
    app.state.workflow_system = None
    app.include_router(create_workflow_runs_router())
    path = "/v1/workflows/definitions"

    with TestClient(app) as client:
        graph = {"name": "Original", "nodes": [{"id": "copy", "type": "transform"}]}
        original = client.post(path, json=graph).json()
        definition_path = f"{path}/{original['id']}"
        schedule_path = f"{definition_path}/recurrences"
        due = time.time() + 600
        schedule = {"first_due_at": due, "interval_seconds": 60}
        pinned_inputs = {**schedule, "definition_revision": original["revision"]}
        pinned = client.post(f"{schedule_path}/pinned", json=pinned_inputs)
        assert pinned.status_code == 201 and pinned.json()["pinned"] is True
        following = client.post(schedule_path, json=schedule)
        assert following.status_code == 201 and following.json()["pinned"] is False

        revised = client.put(definition_path, json={**graph, "name": "Revised"})
        assert revised.status_code == 200
        stale = client.post(f"{schedule_path}/pinned", json=pinned_inputs)
        assert stale.status_code == 412
        upcoming = client.get("/v1/workflows/recurrences/upcoming").json()
        names = {row["id"]: row["workflow_name"] for row in upcoming["recurrences"]}
        assert names == {
            pinned.json()["id"]: "Original", following.json()["id"]: "Revised",
        }

        store = app.state.workflow_runtime.store
        store.enqueue_due_recurrences(due)
        runs = {
            item["recurrence_id"]: store.get_run(item["id"], include_graph=True)
            for item in store.list_runs()
        }
        assert runs[pinned.json()["id"]]["graph"] == original["graph"]
        assert runs[following.json()["id"]]["graph"] == revised.json()["graph"]
        app.state.workflow_runtime.close()


def test_scoped_workflow_key_can_launch_only_its_saved_revision(tmp_path, monkeypatch):
    import hashlib
    import json

    from openjarvis.server.auth_middleware import AuthMiddleware

    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflow.db"))
    app = FastAPI()
    app.state.workflow_system = None
    app.include_router(create_workflow_runs_router())
    path = "/v1/workflows/definitions"
    graph = {"name": "External intake", "nodes": [{"id": "copy", "type": "transform"}]}
    with TestClient(app) as client:
        saved = client.post(path, json=graph).json()
        other = client.post(path, json=graph).json()
        app.state.workflow_runtime.close()

    token = "test-scoped-launch-token"
    monkeypatch.setenv("OPENJARVIS_WORKFLOW_LAUNCH_KEYS", json.dumps({
        saved["id"]: hashlib.sha256(token.encode()).hexdigest(),
    }))
    secured = FastAPI()
    secured.state.workflow_system = None
    secured.include_router(create_workflow_runs_router())
    secured.add_middleware(AuthMiddleware, api_key="test-owner-key")
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "event-1"}
    launch = f"{path}/{saved['id']}/runs"
    body = {"expected_revision": saved["revision"], "initial_input": "sample event"}
    with TestClient(secured) as client:
        assert client.get(path, headers=headers).status_code == 401
        other_path = f"{path}/{other['id']}/runs"
        assert client.post(other_path, json=body, headers=headers).status_code == 401
        schedule = f"{path}/{saved['id']}/schedule"
        assert client.post(schedule, json=body, headers=headers).status_code == 401
        assert client.post(launch, headers=headers, json={}).status_code == 422
        assert client.post(
            launch, headers=headers, json={**body, "context": {"extra": "value"}},
        ).status_code == 422
        assert client.post(
            launch, headers=headers, json={**body, "expected_revision": "stale"},
        ).status_code == 412

        response = client.post(launch, headers=headers, json=body)
        assert response.status_code == 202
        run_id = response.json()["id"]
        replay = client.post(launch, headers=headers, json=body)
        assert replay.status_code == 202 and replay.json()["id"] == run_id
        assert set(replay.json()) == {"id", "status"}
        run_path = f"/v1/workflows/runs/{run_id}"
        assert client.get(run_path, headers=headers).status_code == 401
        owner = {"Authorization": "Bearer test-owner-key"}
        result = client.get(run_path, headers=owner)
        assert result.status_code == 200
        assert result.json()["launch_source"] == "external_automation"
        spoof = client.post(launch, headers=owner, json={
            **body, "context": {"launch_source": "external_automation"},
        })
        assert spoof.status_code == 202 and "launch_source" not in spoof.json()
        secured.state.workflow_runtime.close()


@pytest.mark.parametrize("action", ["runs", "schedule"])
def test_saved_launch_checks_revision_and_confirms_retries(
    tmp_path, monkeypatch, action
):
    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflow.db"))
    app = FastAPI()
    app.state.workflow_system = None
    app.include_router(create_workflow_runs_router())
    path = "/v1/workflows/definitions"

    with TestClient(app) as client:
        graph = {"name": "Original", "nodes": [{"id": "copy", "type": "transform"}]}
        saved = client.post(path, json=graph).json()
        definition_path = f"{path}/{saved['id']}"
        launch_path = f"{definition_path}/{action}"
        payload = {
            "initial_input": "same input",
            "expected_revision": saved["revision"],
        }
        if action == "schedule":
            payload["scheduled_at"] = time.time() + 600
        headers = {"Idempotency-Key": "original-attempt"}
        launched = client.post(launch_path, json=payload, headers=headers)
        assert launched.status_code == 202
        old_run_id = launched.json()["id"]

        updated = client.put(definition_path, json={
            **graph, "name": "Updated", "expected_revision": saved["revision"],
        })
        assert updated.status_code == 200
        retry = client.post(launch_path, json=payload, headers=headers)
        assert retry.status_code == 202 and retry.json()["id"] == old_run_id

        new_headers = {"Idempotency-Key": "new-attempt"}
        stale = client.post(launch_path, json=payload, headers=new_headers)
        assert stale.status_code == 412
        payload["expected_revision"] = updated.json()["revision"]
        fresh = client.post(launch_path, json=payload, headers=new_headers)
        assert fresh.status_code == 202 and fresh.json()["id"] != old_run_id
        assert fresh.json()["workflow_name"] == "Updated"
        app.state.workflow_runtime.close()


def test_saved_workflow_pages_remain_stable_with_new_definitions(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflow.db"))
    ids = iter(digit * 32 for digit in "fca0")
    monkeypatch.setattr(
        "openjarvis.workflow.store.uuid",
        SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=next(ids))),
    )
    monkeypatch.setattr(
        "openjarvis.workflow.store.time", SimpleNamespace(time=lambda: 1000)
    )
    app = FastAPI()
    app.state.workflow_system = None
    app.include_router(create_workflow_runs_router())
    path = "/v1/workflows/definitions"

    with TestClient(app) as client:
        def save(name):
            response = client.post(path, json={
                "name": name, "nodes": [{"id": "copy", "type": "transform"}],
            })
            assert response.status_code == 201
            return response.json()

        oldest = save("Oldest 100%")
        middle = save("Middle")
        newest = save("Newest")
        page = client.get(path, params={"limit": 2}).json()
        assert page["definitions"] == [newest, middle]
        assert page["next_before"] == middle["id"]

        save("Added after the first page")
        page = client.get(path, params={
            "limit": 2, "before": middle["id"],
        }).json()
        assert page["definitions"] == [oldest]
        assert page["next_before"] is None
        matches = client.get(path, params={"search": " OLDEST 100% "}).json()
        assert matches["definitions"] == [oldest]
        matches = client.get(path, params={"search": "%"}).json()
        assert matches["definitions"] == [oldest]
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
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
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
            retry_path = f"{base}/{original_id}/retry-with-input"
            headers = {"Idempotency-Key": "correction-attempt"}
            retried = client.post(
                retry_path, json={"initial_input": "Kestrel"}, headers=headers
            )
            assert retried.status_code == 202
            repeat = client.post(
                retry_path, json={"initial_input": "Kestrel"}, headers=headers
            )
            assert repeat.status_code == 202
            assert repeat.json()["id"] == retried.json()["id"]
            conflict = client.post(
                retry_path, json={"initial_input": "Other"}, headers=headers
            )
            assert conflict.status_code == 409
            runs = client.get(base).json()["runs"]
            children = [run for run in runs if run["parent_run_id"] == original_id]
            assert len(children) == 1
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

def test_proposal_history_filters_by_approval_step_type(tmp_path, monkeypatch):
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
            payload = {
                "name": "Renamed research workflow",
                "initial_input": "Track conversion benchmarks with 10% sample coverage",
                "nodes": [
                    {
                        "id": "review",
                        "type": "approval",
                        "config": {"action_type": "system_builder_proposal"},
                    }
                ],
            }
            proposal = client.post(base, json=payload)
            assert proposal.status_code == 202
            payload["nodes"][0]["config"]["action_type"] = "finance_review"
            assert client.post(base, json=payload).status_code == 202

            response = client.get(
                base,
                params={
                    "approval_type": "system_builder_proposal",
                    "limit": 1,
                },
            )
            assert response.status_code == 200
            history = response.json()
            assert history["approval_type"] == "system_builder_proposal"
            assert [run["id"] for run in history["runs"]] == [proposal.json()["id"]]
            payload["nodes"][0]["config"]["action_type"] = "system_builder_proposal"
            payload["initial_input"] = "Audit competitor landing pages"
            assert client.post(base, json=payload).status_code == 202
            params = {
                "approval_type": "system_builder_proposal",
                "input_contains": "  BENCHMARKS with 10%  ",
                "limit": 1,
            }
            matched = client.get(base, params=params).json()
            assert matched["input_contains"] == "BENCHMARKS with 10%"
            assert [run["id"] for run in matched["runs"]] == [proposal.json()["id"]]
            params["input_contains"] = "%missing"
            assert client.get(base, params=params).json()["runs"] == []

            payload["nodes"][0]["config"]["action_type"] = "project_contribution_review"
            payload["initial_input"] = '{"task_id": "task-12", "task": "Draft a brief"}'
            task_draft = client.post(base, json=payload)
            assert task_draft.status_code == 202
            duplicate = client.post(base, json=payload)
            assert duplicate.status_code == 409
            assert "already active for this task" in duplicate.json()["detail"]
            for initial_input in ('{"task_id":"task-123"}', 'text containing task-12'):
                payload["initial_input"] = initial_input
                assert client.post(base, json=payload).status_code == 202
            payload["nodes"][0]["config"]["action_type"] = "finance_review"
            payload["initial_input"] = '{"task_id":"task-12"}'
            assert client.post(base, json=payload).status_code == 202

            task_history = client.get(base, params={
                "approval_type": "project_contribution_review",
                "project_task_id": "task-12",
            }).json()
            assert task_history["project_task_id"] == "task-12"
            assert [run["id"] for run in task_history["runs"]] == [
                task_draft.json()["id"]
            ]
    finally:
        app.state.workflow_runtime.close()
        approvals.close()


def test_workflow_index_preview_reads_only_the_selected_index(tmp_path, monkeypatch):
    from openjarvis.connectors.store import KnowledgeStore

    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    workflow_db = tmp_path / "workflows.db"
    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(workflow_db))
    with KnowledgeStore() as store:
        store.store("Preview sentinel from selected source", source="upload")
        store.store("Preview sentinel from excluded source", source="another-source")

    app = FastAPI()
    app.include_router(create_workflow_runs_router())
    with TestClient(app) as client:
        endpoint = "/v1/workflows/preview-index"
        response = client.post(endpoint, json={"source": "upload", "query": "sentinel"})
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        result = response.json()
        assert result["success"]
        assert "selected source" in result["output"]
        assert "excluded source" not in result["output"]
        assert not workflow_db.exists()
        invalid = client.post(endpoint, json={"source": " ", "query": "sentinel"})
        assert invalid.status_code == 422


def test_index_sync_age_applies_to_preview_and_execution(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from openjarvis.connectors.gmail_imap import GmailIMAPConnector
    from openjarvis.connectors.pipeline import IngestionPipeline
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.connectors.sync_engine import SyncEngine
    from openjarvis.core.registry import ConnectorRegistry

    if not ConnectorRegistry.contains("gmail_imap"):
        ConnectorRegistry.register_value("gmail_imap", GmailIMAPConnector)
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflows.db"))
    with KnowledgeStore() as store:
        store.store("Freshness sentinel indexed email", source="gmail")

    app = FastAPI()
    app.state.workflow_system = None
    app.include_router(create_workflow_runs_router())
    payload = {"source": "gmail_imap", "query": "sentinel", "max_sync_age_hours": 2}
    endpoint = "/v1/workflows/preview-index"

    with (
        TestClient(app) as client,
        KnowledgeStore() as store,
        SyncEngine(IngestionPipeline(store=store)) as sync,
    ):
        assert not client.post(endpoint, json=payload).json()["success"]
        for hours_ago, error in [(3, None), (1, "Sync failed"), (1, None)]:
            sync.restore_checkpoint("gmail_imap", {
                "items_synced": 1,
                "cursor": None,
                "last_sync": (
                    datetime.now(timezone.utc) - timedelta(hours=hours_ago)
                ).isoformat(),
                "error": error,
            })
            result = client.post(endpoint, json=payload).json()
            assert result["success"] is (hours_ago == 1 and error is None)
        assert "Freshness sentinel" in result["output"]

        sync.reset_checkpoint("gmail_imap")
        launched = client.post("/v1/workflows/runs", json={
            "name": "Checked index",
            "initial_input": payload["query"],
            "nodes": [{"id": "search", "type": "tool", "config": {
                "tool_name": "knowledge_search", "query_from_input": True,
                "source": payload["source"],
                "max_sync_age_hours": payload["max_sync_age_hours"],
            }}],
        })
        assert launched.status_code == 202
        run_path = f"/v1/workflows/runs/{launched.json()['id']}"
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            run = client.get(run_path).json()
            if run["status"] == "failed":
                assert "needs a successful sync" in run["steps"][0]["output"]
                break
            time.sleep(0.01)
        else:
            pytest.fail("Workflow did not stop at the sync age check")
        app.state.workflow_runtime.close()


def test_workflow_condition_preview_matches_branch_labels(tmp_path, monkeypatch):
    workflow_db = tmp_path / "workflows.db"
    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(workflow_db))
    app = FastAPI()
    app.include_router(create_workflow_runs_router())
    endpoint = "/v1/workflows/preview-condition"
    payload = {
        "expression": "outputs['_input'] == 'yes'",
        "outputs": {"_input": "yes"},
        "branches": [
            {"target": "continue", "condition": "true"},
            {"target": "stop", "condition": "false"},
            {"target": "record"},
        ],
    }
    with TestClient(app) as client:
        assert client.post(endpoint, json=payload).json() == {
            "success": True,
            "output": "True",
            "matched_targets": ["continue", "record"],
        }
        payload["outputs"]["_input"] = "no"
        assert client.post(endpoint, json=payload).json()["matched_targets"] == [
            "stop", "record",
        ]
        payload["outputs"] = {}
        failed = client.post(endpoint, json=payload).json()
        assert not failed["success"]
        assert failed["matched_targets"] == []
        assert not workflow_db.exists()


def test_transform_preview_applies_runtime_json_extraction(tmp_path, monkeypatch):
    workflow_db = tmp_path / "workflows.db"
    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(workflow_db))
    app = FastAPI()
    app.include_router(create_workflow_runs_router())
    endpoint = "/v1/workflows/preview-transform"
    with TestClient(app) as client:
        result = client.post(endpoint, json={
            "expression": "json_select:owner,total",
            "sample": '{"owner":"Finance","total":42,"unused":true}',
        })
        assert result.status_code == 200
        assert result.headers["Cache-Control"] == "no-store"
        assert result.json() == {
            "success": True, "output": '{"owner": "Finance", "total": 42}',
        }
        failed = client.post(endpoint, json={
            "expression": "json_field:missing",
            "sample": '{"owner":"Finance"}',
        }).json()
        assert not failed["success"]
        assert not workflow_db.exists()


def test_run_details_explain_skipped_branches(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflows.db"))
    app = FastAPI()
    app.state.workflow_system = None
    app.include_router(create_workflow_runs_router())
    endpoint = "/v1/workflows/runs"
    payload = {
        "initial_input": "yes",
        "nodes": [
            {"id": "choose", "type": "condition", "condition_expr": "True"},
            {"id": "accepted", "type": "transform"},
            {"id": "declined", "type": "transform"},
            {"id": "follow-up", "type": "transform"},
        ],
        "edges": [
            {"source": "choose", "target": "accepted", "condition": "true"},
            {"source": "choose", "target": "declined", "condition": "false"},
            {"source": "declined", "target": "follow-up"},
        ],
    }
    try:
        with TestClient(app) as client:
            created = client.post(endpoint, json=payload)
            assert created.status_code == 202
            path = f"{endpoint}/{created.json()['id']}"
            for _ in range(100):
                run = client.get(path).json()
                if run["status"] == "succeeded":
                    break
                time.sleep(0.02)
            assert run["status"] == "succeeded"
            assert run["skipped_steps"] == [
                {"node_id": "declined", "incoming": [
                    {"source": "choose", "condition": "false",
                     "reason": "condition_mismatch"},
                ]},
                {"node_id": "follow-up", "incoming": [
                    {"source": "declined", "condition": "", "reason": "source_not_run"},
                ]},
            ]
    finally:
        app.state.workflow_runtime.close()


def test_review_history_matches_current_and_legacy_finance_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "workflows.db"))
    app = FastAPI()
    app.state.workflow_system = None
    app.include_router(create_workflow_runs_router())
    endpoint = "/v1/workflows/runs"
    try:
        with TestClient(app) as client:
            def start(name, node_id, action_type):
                config = {} if action_type is None else {"action_type": action_type}
                response = client.post(endpoint, json={
                    "name": name, "initial_input": "Invoice 731",
                    "nodes": [{"id": node_id, "type": "approval", "config": config}],
                })
                assert response.status_code == 202
                return response.json()["id"]

            legacy = start("Old workpaper", "finance-review", None)
            modern = start("Renamed workpaper", "custom-id", "finance_workpaper_review")
            start("Unrelated", "finance-review", "unrelated")
            result = client.get(endpoint, params={
                "approval_type": "finance_workpaper_review",
                "legacy_approval_node": "finance-review",
                "input_contains": "731",
            })
            assert result.status_code == 200
            assert [run["id"] for run in result.json()["runs"]] == [modern, legacy]
    finally:
        app.state.workflow_runtime.close()
