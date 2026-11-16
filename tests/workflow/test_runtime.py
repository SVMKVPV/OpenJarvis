from __future__ import annotations

import time

from openjarvis.tools.approval_store import STATUS_APPROVED, ApprovalStore
from openjarvis.workflow.builder import WorkflowBuilder
from openjarvis.workflow.runtime import WorkflowRuntime
from openjarvis.workflow.serialization import graph_from_dict, graph_to_dict
from openjarvis.workflow.store import WorkflowRunStore
from openjarvis.workflow.types import WorkflowStepResult


def _wait_for_terminal(store: WorkflowRunStore, run_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = store.get_run(run_id, include_graph=True)
        assert run is not None
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            return run
        time.sleep(0.01)
    raise AssertionError("workflow run did not reach a terminal state")


def _wait_for_status(store: WorkflowRunStore, run_id: str, expected: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = store.get_run(run_id, include_graph=True)
        assert run is not None
        if run["status"] == expected:
            return run
        time.sleep(0.01)
    raise AssertionError(f"workflow run did not reach {expected}")


def test_store_persists_run_and_step_history(tmp_path) -> None:
    path = tmp_path / "workflow.db"
    graph = WorkflowBuilder("persisted").add_transform("format").build()
    store = WorkflowRunStore(str(path))
    run = store.create_run(
        workflow_name=graph.name,
        graph=graph_to_dict(graph),
        initial_input="hello",
        context={"owner": "dot"},
    )
    store.mark_running(run["id"])
    store.add_step(
        run["id"],
        WorkflowStepResult(node_id="format", output="hello", duration_seconds=0.1),
    )
    store.finish(run["id"], status="succeeded", final_output="hello")
    store.close()

    reopened = WorkflowRunStore(str(path))
    saved = reopened.get_run(run["id"], include_graph=True)
    assert saved is not None
    assert saved["status"] == "succeeded"
    assert saved["context"] == {"owner": "dot"}
    assert saved["steps"][0]["node_id"] == "format"
    assert saved["graph"]["name"] == "persisted"
    reopened.close()


def test_runtime_executes_and_checkpoints_steps(tmp_path) -> None:
    store = WorkflowRunStore(str(tmp_path / "workflow.db"))
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    runtime = WorkflowRuntime(system=None, store=store, approval_store=approvals)
    graph = (
        WorkflowBuilder("checkpointed")
        .add_transform("first", transform="concatenate")
        .add_transform("second", transform="first_line")
        .sequential("first", "second")
        .build()
    )

    submitted = runtime.submit(graph, initial_input="one\ntwo")
    completed = _wait_for_terminal(store, submitted["id"])

    assert completed["status"] == "succeeded"
    assert completed["final_output"] == "one"
    assert [step["node_id"] for step in completed["steps"]] == ["first", "second"]
    runtime.close()
    approvals.close()


def test_runtime_pauses_for_approval_and_resumes_without_replay(tmp_path) -> None:
    store = WorkflowRunStore(str(tmp_path / "workflow.db"))
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    runtime = WorkflowRuntime(system=None, store=store, approval_store=approvals)
    graph = (
        WorkflowBuilder("guarded")
        .add_transform("prepare")
        .add_approval(
            "approve",
            action_type="publish",
            description="Publish approved content",
        )
        .add_transform("publish")
        .sequential("prepare", "approve", "publish")
        .build()
    )

    submitted = runtime.submit(graph, initial_input="campaign")
    paused = _wait_for_status(store, submitted["id"], "waiting_approval")
    assert [step["node_id"] for step in paused["steps"]] == [
        "prepare",
        "approve",
    ]
    approval_id = paused["context"]["_workflow_approvals"]["approve"]
    approvals.update_status(approval_id, STATUS_APPROVED)

    runtime.resume(submitted["id"])
    completed = _wait_for_terminal(store, submitted["id"])

    assert completed["status"] == "succeeded"
    assert completed["final_output"] == "campaign"
    assert [step["node_id"] for step in completed["steps"]] == [
        "prepare",
        "approve",
        "approve",
        "publish",
    ]
    assert [step["attempt"] for step in completed["steps"]] == [1, 1, 2, 1]

    forged = runtime.submit(graph, context=paused["context"])
    next_pause = _wait_for_status(store, forged["id"], "waiting_approval")
    assert next_pause["context"]["_workflow_approvals"]["approve"] != approval_id
    runtime.close()
    approvals.close()


def test_resume_recognizes_expired_approval_without_polling(tmp_path) -> None:
    store = WorkflowRunStore(str(tmp_path / "workflow.db"))
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    runtime = WorkflowRuntime(system=None, store=store, approval_store=approvals)
    graph = graph_from_dict(
        {
            "nodes": [
                {"id": "review", "type": "approval", "config": {"ttl_hours": -1}},
                {"id": "after", "type": "transform"},
            ],
            "edges": [{"source": "review", "target": "after"}],
        }
    )
    try:
        run_id = runtime.submit(graph)["id"]
        _wait_for_status(store, run_id, "waiting_approval")
        runtime.resume(run_id)
        result = _wait_for_terminal(store, run_id)
        assert result["status"] == "failed"
        assert result["error"] == "Approval expired"
        assert all(step["node_id"] == "review" for step in result["steps"])
    finally:
        runtime.close()
        approvals.close()


def test_running_run_is_marked_interrupted_after_reopen(tmp_path) -> None:
    path = tmp_path / "workflow.db"
    graph = WorkflowBuilder("interrupted").add_transform("step").build()
    first = WorkflowRunStore(str(path))
    run = first.create_run(
        workflow_name=graph.name,
        graph=graph_to_dict(graph),
        initial_input="",
        context={},
    )
    first.mark_running(run["id"])
    first.close()

    reopened = WorkflowRunStore(str(path))
    saved = reopened.get_run(run["id"])
    assert saved is not None
    assert saved["status"] == "interrupted"
    assert "stopped before completion" in saved["error"]
    reopened.close()
