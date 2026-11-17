from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.app import create_app  # noqa: E402


def test_handoff_approved_run_keeps_evidence_in_workflow(tmp_path, monkeypatch):
    from openjarvis.agents.manager import AgentManager
    from openjarvis.server import approval_routes
    from openjarvis.tools.approval_store import ApprovalStore

    monkeypatch.setenv("OPENJARVIS_WORKFLOW_DB", str(tmp_path / "runs.db"))
    monkeypatch.setattr("openjarvis.core.shared_brain.get_config_dir", lambda: tmp_path)
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    monkeypatch.setattr(approval_routes, "_store", approvals)
    manager = AgentManager(str(tmp_path / "agents.db"))
    agent = manager.create_agent("Operations")
    app = create_app(MagicMock(), "test", agent_manager=manager)
    brief_path = "/v1/shared-brain/brief"
    with TestClient(app) as client:
        assert client.put(
            brief_path, json={"context": "Existing draft", "revision": 0}
        ).status_code == 200
        started = client.post("/v1/workflows/runs", json={
            "initial_input": "Private evidence should stay in the workflow",
            "nodes": [{"id": "review", "type": "approval"}],
        })
        assert started.status_code == 202
        run_id = started.json()["id"]
        run_path = f"/v1/workflows/runs/{run_id}"
        share_path = f"{run_path}/share-to-brain"
        assign_path = f"{run_path}/assign-workstation"
        follow_ups_path = f"{run_path}/workstation-follow-ups"
        route = {
            "source_workstation": "Finance",
            "manager_workstation": "Operations Manager",
        }
        assignment = {
            "agent_id": agent["id"], "instruction": "Plan a delivery check.",
            "reporting_route": route,
        }
        summary = {"summary": "Delivery wording confirmed."}
        assert client.post(share_path, json=summary).status_code == 409
        assert client.post(assign_path, json=assignment).status_code == 409
        assert client.get(follow_ups_path).status_code == 409

        def wait_for(expected):
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                run = client.get(run_path).json()
                if run["status"] == expected:
                    return run
                time.sleep(0.01)
            pytest.fail(f"Workflow did not reach {expected}")

        paused = wait_for("waiting_approval")
        approval_id = paused["context"]["_workflow_approvals"]["review"]
        assert client.post(f"/v1/approvals/{approval_id}/approve").status_code == 200
        wait_for("succeeded")
        assert client.post(share_path, json=summary).json() == {"added": True}
        assert client.post(share_path, json=summary).json() == {"added": False}
        assert client.get(brief_path).json() == {
            "context": (
                f"Existing draft\n\n[Approved workflow {run_id}]\n"
                "Delivery wording confirmed."
            ),
            "revision": 2,
        }
        assert client.post(assign_path, json=assignment).json() == {"queued": True}
        repeated = client.post(assign_path, json={
            **assignment,
            "reporting_route": {**route, "manager_workstation": "Renamed"},
        })
        assert repeated.json() == {"queued": False}
        unavailable = client.post(
            assign_path, json={**assignment, "agent_id": "missing"}
        )
        assert unavailable.status_code == 409
        queued, = manager.get_pending_messages(agent["id"])
        assert queued["mode"] == "handoff"
        assert queued["workflow_run_id"] == run_id
        assert queued["content"] == (
            f"Approved workflow {run_id}\n\nPlan a delivery check."
        )
        follow_up, = client.get(follow_ups_path).json()["follow_ups"]
        assert follow_up["agent_name"] == agent["name"]
        assert follow_up["status"] == "pending"
        assert follow_up["reporting_route"] == route
        reply = manager.store_agent_response(
            agent["id"], "Checklist ready", delivered_message_ids=(queued["id"],)
        )
        received, = client.get(follow_ups_path).json()["follow_ups"]
        assert received == {
            **follow_up,
            "status": "delivered",
            "response": {key: reply[key] for key in ("id", "content", "created_at")},
        }
        manager.store_agent_response(agent["id"], "Unrelated later reply.")
        assert client.get(follow_ups_path).json()["follow_ups"] == [received]
    approvals.close()
    manager.close()


def test_shared_brief_is_authenticated_persistent_and_revisioned(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "openjarvis.core.shared_brain.get_config_dir", lambda: tmp_path
    )
    path = "/v1/shared-brain/brief"
    headers = {"Authorization": "Bearer test-shared-brain-key"}

    def client() -> TestClient:
        return TestClient(
            create_app(MagicMock(), "test", api_key="test-shared-brain-key")
        )

    with client() as original:
        assert original.get(path).status_code == 401
        assert (
            original.put(path, json={"context": "", "revision": 0}).status_code == 401
        )
        assert original.get(path, headers=headers).json() == {
            "context": "",
            "revision": 0,
        }

        def save(text):
            return original.put(
                path, json={"context": text, "revision": 0}, headers=headers
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(save, value) for value in ("First", "Second")]
            results = [future.result() for future in futures]
        assert sorted(response.status_code for response in results) == [200, 409]
        winner = next(
            response.json() for response in results if response.status_code == 200
        )
        assert winner["revision"] == 1

    with client() as restarted:
        assert restarted.get(path, headers=headers).json() == winner
        too_long = restarted.put(
            path, json={"context": "x" * 4001, "revision": 1}, headers=headers
        )
        assert too_long.status_code == 422
        assert restarted.get(path, headers=headers).json() == winner


def test_shared_brain_read_key_cannot_edit_or_access_other_routes(tmp_path, monkeypatch):
    import hashlib

    from fastapi import FastAPI

    from openjarvis.server.auth_middleware import AuthMiddleware
    from openjarvis.server.shared_brain_routes import router

    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    read_key = "test-brief-reader"
    monkeypatch.setenv(
        "OPENJARVIS_SHARED_BRAIN_READ_KEY_SHA256",
        hashlib.sha256(read_key.encode()).hexdigest(),
    )
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(AuthMiddleware, api_key="test-owner")
    reader = {"Authorization": f"Bearer {read_key}"}
    owner = {"Authorization": "Bearer test-owner"}
    path = "/v1/shared-brain/brief"
    payload = {"context": "Approved shared context", "revision": 0}
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        saved = client.put(path, json=payload, headers=owner)
        assert saved.status_code == 200
        brief = client.get(path, headers=reader)
        assert brief.status_code == 200
        assert brief.headers["Cache-Control"] == "no-store"
        assert brief.json() == saved.json()
        assert client.put(path, json=payload, headers=reader).status_code == 401
        assert client.get("/v1/workflows/runs", headers=reader).status_code == 401
