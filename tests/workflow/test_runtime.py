from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from openjarvis.tools.approval_store import STATUS_APPROVED, ApprovalStore
from openjarvis.workflow.builder import WorkflowBuilder
from openjarvis.workflow.runtime import WorkflowRuntime, WorkflowRuntimeStopping
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


def test_paused_recurrence_resumes_on_next_future_slot_after_restart(tmp_path) -> None:
    path = str(tmp_path / "workflow.db")
    store = WorkflowRunStore(path)
    graph = WorkflowBuilder("Recurring review").add_transform("format").build()
    definition_id = store.save_definition(graph_to_dict(graph))["id"]
    schedule = store.save_recurrence(definition_id, "saved input", 1000, 60)
    schedule_id = schedule["id"]
    store.set_recurrence_paused(definition_id, schedule_id, paused=True, now=980)
    store.close()

    reopened = WorkflowRunStore(path)
    try:
        reopened.enqueue_due_recurrences(1180)
        assert reopened.list_runs() == []
        assert reopened.list_recurrences(definition_id)[0]["paused"] is True
        resumed = reopened.set_recurrence_paused(
            definition_id, schedule_id, paused=False, now=1180
        )
        assert resumed is not None
        assert resumed["next_due_at"] == 1240
        reopened.enqueue_due_recurrences(1180)
        assert reopened.list_runs() == []
        reopened.enqueue_due_recurrences(1240)
        run, = reopened.list_runs()
        assert run["initial_input"] == "saved input"
        assert run["scheduled_at"] == 1240
    finally:
        reopened.close()


def test_recurrence_skips_an_active_review_after_restart(tmp_path) -> None:
    path = str(tmp_path / "workflow.db")
    start = 1000
    store = WorkflowRunStore(path)
    graph = WorkflowBuilder("Recurring review").add_transform("format").build()
    definition = store.save_definition(graph_to_dict(graph))
    definition_id = definition["id"]
    recurrence = store.save_recurrence(definition_id, "primary", start, 60)
    other = store.save_recurrence(definition_id, "independent", start + 60, 60)
    store.enqueue_due_recurrences(start)
    first, = store.list_runs()
    assert first["recurrence_id"] == recurrence["id"]
    assert store.claim_scheduled_run(first["id"], start)
    store.pause(first["id"], context={})
    store.close()

    reopened = WorkflowRunStore(path)
    try:
        reopened.enqueue_due_recurrences(start + 60)
        scheduled = reopened.list_runs(status="scheduled")
        assert [run["recurrence_id"] for run in scheduled] == [other["id"]]
        schedules = {
            entry["id"]: entry for entry in reopened.list_recurrences(definition_id)
        }
        assert schedules[recurrence["id"]]["skipped_while_active"] == 1
        assert schedules[recurrence["id"]]["next_due_at"] == start + 120
        reopened.finish(first["id"], status="succeeded")
        reopened.enqueue_due_recurrences(start + 120)
        assert {
            (run["recurrence_id"], run["scheduled_at"])
            for run in reopened.list_runs(status="scheduled")
        } == {(other["id"], start + 60), (recurrence["id"], start + 120)}
    finally:
        reopened.close()


def test_recurrence_catchup_counter_migrates_existing_schedules(tmp_path) -> None:
    path = str(tmp_path / "workflow.db")
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            """
            CREATE TABLE workflow_recurrences (
                id TEXT PRIMARY KEY, definition_id TEXT NOT NULL,
                initial_input TEXT NOT NULL, next_due_at REAL NOT NULL,
                interval_seconds INTEGER NOT NULL,
                skipped_while_active INTEGER NOT NULL DEFAULT 0,
                paused INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "INSERT INTO workflow_recurrences VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("existing", "saved", "original input", 1000, 60, 4, 1, 3),
        )

    store = WorkflowRunStore(path)
    try:
        schedule, = store.list_recurrences("saved")
        assert schedule == {
            "id": "existing",
            "definition_id": "saved",
            "initial_input": "original input",
            "next_due_at": 1000,
            "interval_seconds": 60,
            "skipped_while_active": 4,
            "skipped_during_catchup": 0,
            "paused": True,
            "revision": 3,
            "pinned": False,
        }
    finally:
        store.close()


def test_recurrence_records_older_starts_skipped_during_catchup(tmp_path) -> None:
    path = str(tmp_path / "workflow.db")
    store = WorkflowRunStore(path)
    graph = WorkflowBuilder("Recurring review").add_transform("format").build()
    definition_id = store.save_definition(graph_to_dict(graph))["id"]
    store.save_recurrence(definition_id, "saved input", 1000, 60)
    store.close()

    reopened = WorkflowRunStore(path)
    try:
        reopened.enqueue_due_recurrences(1185)
        reopened.enqueue_due_recurrences(1185)
        run, = reopened.list_runs()
        assert run["scheduled_at"] == 1180
        schedule, = reopened.list_recurrences(definition_id)
        assert schedule["next_due_at"] == 1240
        assert schedule["skipped_during_catchup"] == 3
        assert schedule["skipped_while_active"] == 0
    finally:
        reopened.close()


def test_schedule_history_includes_retries_with_legacy_parent_links(
    tmp_path, monkeypatch
) -> None:
    store = WorkflowRunStore(str(tmp_path / "workflow.db"))
    graph = WorkflowBuilder("Recurring review").add_transform("format").build()
    definition = store.save_definition(graph_to_dict(graph))
    schedule = store.save_recurrence(definition["id"], "", 1000, 60)
    try:
        store.enqueue_due_recurrences(1000)
        original, = store.list_runs()
        # Force the two retries to share a timestamp and have reverse UUID order.
        ids = iter(("f" * 32, "0" * 32, "a" * 32))
        monkeypatch.setattr(
            "openjarvis.workflow.store.uuid",
            SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=next(ids))),
        )
        monkeypatch.setattr(
            "openjarvis.workflow.store.time", SimpleNamespace(time=lambda: 1001)
        )
        store.finish(original["id"], status="failed")
        parent = original
        for status in ("failed", "succeeded"):
            parent = store.create_run(
                workflow_name=graph.name, graph=definition["graph"],
                initial_input="", context={}, parent_run_id=parent["id"],
            )
            store.finish(parent["id"], status=status)
        unrelated = store.create_run(
            workflow_name=graph.name, graph=definition["graph"],
            initial_input="", context={},
        )
        store.finish(unrelated["id"], status="succeeded")
        scope = schedule["id"]
        page = store.list_runs(recurrence_id=scope, limit=1)
        assert [run["id"] for run in page] == [parent["id"]]
        remaining = store.list_runs(recurrence_id=scope, before=parent["id"])
        assert [run["id"] for run in remaining] == [
            parent["parent_run_id"], original["id"],
        ]
        matches = store.list_runs(recurrence_id=scope, status="succeeded")
        assert [run["id"] for run in matches] == [parent["id"]]
    finally:
        store.close()


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


def _refuse_thread_start(self):
    raise RuntimeError("cannot start a new thread")


def test_worker_start_failure_leaves_retryable_run(tmp_path, monkeypatch) -> None:
    store = WorkflowRunStore(str(tmp_path / "workflow.db"))
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    runtime = WorkflowRuntime(system=None, store=store, approval_store=approvals)
    graph = WorkflowBuilder("recoverable").add_transform("prepare").build()

    try:
        with monkeypatch.context() as patch:
            patch.setattr(Thread, "start", _refuse_thread_start)
            failed = runtime.submit(
                graph, initial_input="draft", launch=("test", "one")
            )
            assert failed["status"] == "failed"
            assert failed["error"] == "Workflow worker could not start"
            same = runtime.submit(graph, initial_input="draft", launch=("test", "one"))
            assert same["id"] == failed["id"]
            assert same["status"] == "failed"

        retry = runtime.retry(failed["id"])
        completed = _wait_for_terminal(store, retry["id"])
        assert completed["status"] == "succeeded"
        assert completed["final_output"] == "draft"
    finally:
        runtime.close()
        approvals.close()


def test_runtime_pauses_for_approval_and_resumes_without_replay(
    tmp_path, monkeypatch
) -> None:
    store = WorkflowRunStore(str(tmp_path / "workflow.db"))
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    runtime = WorkflowRuntime(system=None, store=store, approval_store=approvals)
    graph = (
        WorkflowBuilder("guarded")
        .add_transform("prepare", transform="first_line")
        .add_approval(
            "approve",
            action_type="publish",
            description="Publish approved content",
        )
        .add_transform("publish")
        .sequential("prepare", "approve", "publish")
        .build()
    )

    submitted = runtime.submit(graph, initial_input="campaign\ninternal notes")
    paused = _wait_for_status(store, submitted["id"], "waiting_approval")
    assert [step["node_id"] for step in paused["steps"]] == [
        "prepare",
        "approve",
    ]
    approval_id = paused["context"]["_workflow_approvals"]["approve"]
    assert paused["steps"][1]["metadata"]["review_input"] == "campaign"
    action = approvals.get_action(approval_id)
    assert "review_input" not in action.payload

    with monkeypatch.context() as patch:
        patch.setattr(Thread, "start", _refuse_thread_start)
        assert runtime.decide_approval(action, STATUS_APPROVED)
        assert approvals.get_action(approval_id).status == STATUS_APPROVED
        with pytest.raises(WorkflowRuntimeStopping, match="could not start"):
            runtime.resume(submitted["id"])
        still_paused = _wait_for_status(store, submitted["id"], "waiting_approval")
        assert still_paused["context"] == paused["context"]
        assert still_paused["steps"] == paused["steps"]

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


@pytest.mark.parametrize(
    ("decision", "expected"), [("approved", "succeeded"), ("denied", "failed")]
)
def test_parallel_approval_keeps_other_checkpoint_available(
    tmp_path, decision, expected
) -> None:
    store = WorkflowRunStore(str(tmp_path / "workflow.db"))
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    runtime = WorkflowRuntime(system=None, store=store, approval_store=approvals)
    try:
        graph = (
            WorkflowBuilder("parallel review")
            .add_approval("a", action_type="review", description="Review A")
            .add_approval("b", action_type="review", description="Review B")
            .build()
        )
        run_id = runtime.submit(graph)["id"]
        _wait_for_status(store, run_id, "waiting_approval")
        first, second = approvals.list_pending()
        assert runtime.decide_approval(first, STATUS_APPROVED)
        assert store.get_run(run_id)["status"] == "waiting_approval"
        assert runtime.is_waiting_for(second)
        assert runtime.decide_approval(second, decision, checks=["Checked source"])
        final = _wait_for_terminal(store, run_id)
        assert final["status"] == expected
        assert any(
            step["metadata"].get("approval_id") == second.id
            and step["metadata"].get("decision_checks") == ["Checked source"]
            for step in final["steps"]
        )
    finally:
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


@pytest.mark.parametrize("step_type", ["agent", "loop", "parallel_loop"])
def test_cancel_during_last_step_is_recorded(tmp_path, step_type) -> None:
    started = Event()
    release = Event()
    calls = []

    class SlowAgent:
        def ask(self, prompt, **_kwargs):
            calls.append(prompt)
            started.set()
            assert release.wait(5)
            return {"content": "Step output"}

    store = WorkflowRunStore(str(tmp_path / "workflow.db"))
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    runtime = WorkflowRuntime(system=SlowAgent(), store=store, approval_store=approvals)
    try:
        builder = WorkflowBuilder("cancel last step")
        if step_type == "agent":
            builder.add_agent("last")
        else:
            builder.add_loop("last", max_iterations=3)
        if step_type == "parallel_loop":
            builder.add_transform("sibling")
        graph = builder.build()
        run_id = runtime.submit(graph)["id"]
        assert started.wait(3)
        assert runtime.cancel(run_id)
        release.set()
        result = _wait_for_terminal(store, run_id)
        assert result["status"] == "cancelled"
        step = next(step for step in result["steps"] if step["node_id"] == "last")
        assert step["output"] == "Step output"
        assert len(calls) == 1
        if step_type != "agent":
            assert step["metadata"]["iterations"] == 1
    finally:
        release.set()
        runtime.close()
        approvals.close()


def test_shutdown_preserves_ledger_for_worker_past_deadline(tmp_path) -> None:
    started = Event()
    release = Event()
    closed = Event()
    path = str(tmp_path / "workflow.db")

    class SlowAgent:
        def ask(self, *_args, **_kwargs):
            started.set()
            assert release.wait(5)
            return {"content": "Step output"}

    class ObservedStore(WorkflowRunStore):
        def close(self):
            super().close()
            closed.set()

    store = ObservedStore(path)
    approvals = ApprovalStore(str(tmp_path / "approvals.db"))
    runtime = WorkflowRuntime(system=SlowAgent(), store=store, approval_store=approvals)
    graph = WorkflowBuilder("shutdown").add_agent("step").build()
    try:
        run_id = runtime.submit(graph)["id"]
        assert started.wait(3)
        runtime.close(timeout=0)
        assert not closed.is_set()
        assert store.get_run(run_id)["cancel_requested"]
        with pytest.raises(RuntimeError, match="runtime is stopping"):
            runtime.submit(graph)
        release.set()
        assert closed.wait(3)
        reopened = WorkflowRunStore(path)
        try:
            run = reopened.get_run(run_id)
            assert run["status"] == "cancelled"
            assert run["steps"][0]["output"] == "Step output"
        finally:
            reopened.close()
    finally:
        release.set()
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
