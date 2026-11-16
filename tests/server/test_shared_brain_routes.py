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
        assignment = {"agent_id": agent["id"], "instruction": "Plan a delivery check."}
        summary = {"summary": "Delivery wording confirmed."}
        assert client.post(share_path, json=summary).status_code == 409
        assert client.post(assign_path, json=assignment).status_code == 409

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
        assert client.post(assign_path, json=assignment).json() == {"queued": False}
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
