"""Background workflow execution backed by :mod:`workflow.store`."""

from __future__ import annotations

import logging
import threading
from typing import Any, Mapping

from openjarvis.core.events import EventBus
from openjarvis.tools.approval_store import ApprovalStore
from openjarvis.workflow.engine import WorkflowEngine
from openjarvis.workflow.graph import WorkflowGraph
from openjarvis.workflow.serialization import graph_from_dict, graph_to_dict
from openjarvis.workflow.store import WorkflowRunStore

logger = logging.getLogger(__name__)


class WorkflowRuntime:
    def __init__(
        self,
        *,
        system: Any,
        store: WorkflowRunStore | None = None,
        approval_store: ApprovalStore | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self._system = system
        self.store = store or WorkflowRunStore()
        self.approval_store = approval_store or ApprovalStore()
        self._owns_approval_store = approval_store is None
        self._engine = WorkflowEngine(bus=bus, approval_store=self.approval_store)
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self._stopping = False

    def submit(
        self,
        graph: WorkflowGraph,
        *,
        initial_input: str = "",
        context: Mapping[str, Any] | None = None,
        parent_run_id: str | None = None,
    ) -> dict[str, Any]:
        if self._stopping:
            raise RuntimeError("Workflow runtime is stopping")
        context = {
            key: value for key, value in (context or {}).items()
            if key not in {"_workflow_run_id", "_workflow_approvals"}
        }
        run = self.store.create_run(
            workflow_name=graph.name,
            graph=graph_to_dict(graph),
            initial_input=initial_input,
            context=dict(context or {}),
            parent_run_id=parent_run_id,
        )
        run_id = run["id"]
        worker = threading.Thread(
            target=self._execute,
            args=(run_id, graph, initial_input, dict(context or {})),
            name=f"workflow-{run_id[:8]}",
            daemon=True,
        )
        with self._lock:
            self._threads[run_id] = worker
        worker.start()
        return run

    def _execute(
        self,
        run_id: str,
        graph: WorkflowGraph,
        initial_input: str,
        context: dict[str, Any],
    ) -> None:
        try:
            if self.store.is_cancel_requested(run_id):
                self.store.finish(run_id, status="cancelled")
                return
            self.store.mark_running(run_id)
            context["_workflow_run_id"] = run_id
            previous = self.store.get_run(run_id)
            resume_outputs: dict[str, str] = {}
            completed_nodes: set[str] = set()
            if previous is not None:
                for step in previous["steps"]:
                    if (
                        step["success"]
                        and step["metadata"].get("workflow_status")
                        != "waiting_approval"
                    ):
                        completed_nodes.add(step["node_id"])
                        resume_outputs[step["node_id"]] = step["output"]
            result = self._engine.run(
                graph,
                self._system,
                initial_input=initial_input,
                context=context,
                step_callback=lambda step: self.store.add_step(run_id, step),
                should_cancel=lambda: self.store.is_cancel_requested(run_id),
                resume_outputs=resume_outputs,
                completed_nodes=completed_nodes,
            )
            if result.status == "waiting_approval":
                with self._lock:
                    if self.store.is_cancel_requested(run_id):
                        self.store.finish(run_id, status="cancelled")
                        return
                    approvals = context.setdefault("_workflow_approvals", {})
                    for step in result.steps:
                        if step.metadata.get("workflow_status") == "waiting_approval":
                            approvals[step.node_id] = step.metadata["approval_id"]
                    self.store.pause(run_id, context=context)
                    self._threads.pop(run_id, None)
                return
            error = (
                ""
                if result.success or result.status == "cancelled"
                else result.final_output
            )
            self.store.finish(
                run_id,
                status=result.status,
                final_output=result.final_output,
                error=error,
            )
        except Exception as exc:
            logger.exception("Workflow run %s failed", run_id)
            self.store.finish(run_id, status="failed", error=str(exc))
        finally:
            with self._lock:
                if self._threads.get(run_id) is threading.current_thread():
                    self._threads.pop(run_id, None)

    def retry(self, run_id: str) -> dict[str, Any]:
        previous = self.store.get_run(run_id, include_graph=True)
        if previous is None:
            raise KeyError(run_id)
        if previous["status"] not in {"failed", "cancelled", "interrupted"}:
            raise ValueError(
                "Only failed, cancelled, or interrupted runs can be retried"
            )
        return self.submit(
            graph_from_dict(previous["graph"]),
            initial_input=previous["initial_input"],
            context=previous["context"],
            parent_run_id=run_id,
        )

    def resume(self, run_id: str) -> dict[str, Any]:
        """Resume a paused run without replaying completed nodes."""
        with self._lock:
            if self._stopping:
                raise ValueError("Workflow runtime is stopping")
            run = self.store.get_run(run_id, include_graph=True)
            if run is None:
                raise KeyError(run_id)
            if run["status"] != "waiting_approval" or run_id in self._threads:
                raise ValueError("Only workflows waiting for approval can be resumed")
            worker = threading.Thread(
                target=self._execute,
                args=(
                    run_id,
                    graph_from_dict(run["graph"]),
                    run["initial_input"],
                    dict(run["context"]),
                ),
                name=f"workflow-{run_id[:8]}",
                daemon=True,
            )
            self._threads[run_id] = worker
            self.store.mark_running(run_id)
            worker.start()
        return run

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            run = self.store.get_run(run_id)
            if run is None or not self.store.request_cancel(run_id):
                return False
            if run["status"] == "waiting_approval":
                self.store.finish(run_id, status="cancelled")
            return True

    def close(self, *, timeout: float = 5.0) -> None:
        self._stopping = True
        with self._lock:
            run_ids = list(self._threads)
            workers = list(self._threads.values())
        for run_id in run_ids:
            self.store.request_cancel(run_id)
        for worker in workers:
            worker.join(timeout=timeout)
        self.store.close()
        if self._owns_approval_store:
            self.approval_store.close()


__all__ = ["WorkflowRuntime"]
