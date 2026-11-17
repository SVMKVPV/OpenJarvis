"""Durable workflow run API for the command center."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, StrictBool

from openjarvis.core.paths import get_config_dir
from openjarvis.core.shared_brain import SharedBriefConflict, append_workflow_handoff
from openjarvis.server.approval_routes import get_approval_store
from openjarvis.tools.approval_store import STATUS_APPROVED, STATUS_DENIED
from openjarvis.workflow.engine import WorkflowEngine
from openjarvis.workflow.graph import edge_matches_output
from openjarvis.workflow.runtime import WorkflowRuntime, WorkflowRuntimeStopping
from openjarvis.workflow.serialization import graph_from_dict, graph_to_dict
from openjarvis.workflow.store import (
    WorkflowDefinitionConflict,
    WorkflowLaunchConflict,
    WorkflowRunStore,
)
from openjarvis.workflow.types import NodeType, WorkflowNode


class WorkflowDefinition(BaseModel):
    name: str = "workflow"
    nodes: list[Dict[str, Any]] = Field(min_length=1)
    edges: list[Dict[str, Any]] = Field(default_factory=list)


class WorkflowInputs(BaseModel):
    initial_input: str = ""
    context: Dict[str, Any] = Field(default_factory=dict)


class SavedWorkflowInputs(WorkflowInputs):
    expected_revision: str | None = Field(default=None, min_length=1, max_length=128)


class ScheduledWorkflowInputs(SavedWorkflowInputs):
    scheduled_at: float = Field(gt=0, allow_inf_nan=False)


class RecurringWorkflowInputs(BaseModel):
    initial_input: str = ""
    first_due_at: float = Field(gt=0, le=253402300799, allow_inf_nan=False)
    interval_seconds: int = Field(ge=60, le=31536000)


class PinnedRecurringWorkflowInputs(RecurringWorkflowInputs):
    definition_revision: str = Field(min_length=1, max_length=128)


class RecurringWorkflowStatus(BaseModel):
    paused: StrictBool


class RecurringWorkflowEdit(RecurringWorkflowInputs):
    expected_revision: int = Field(ge=0)


class RescheduleWorkflowRun(BaseModel):
    scheduled_at: float = Field(gt=0, allow_inf_nan=False)
    expected_scheduled_at: float = Field(gt=0, allow_inf_nan=False)


class RetryWorkflowInput(BaseModel):
    initial_input: str | None = None


class WorkflowHandoff(BaseModel):
    summary: str = Field(min_length=1, max_length=750)


class WorkflowReportingRoute(BaseModel):
    source_workstation: str = Field(min_length=1, max_length=80)
    manager_workstation: str = Field(min_length=1, max_length=80)


class WorkflowAgentHandoff(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    instruction: str = Field(min_length=1, max_length=2000)
    reporting_route: WorkflowReportingRoute | None = None


class WorkflowDefinitionUpdate(WorkflowDefinition):
    expected_revision: str | None = None


class WorkflowRunRequest(WorkflowDefinition, WorkflowInputs):
    pass


class WorkflowIndexPreview(BaseModel):
    source: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=500)
    allow_gmail_reference: StrictBool = False
    max_sync_age_hours: int | None = Field(default=None, ge=1, le=8760, strict=True)


class PreviewBranch(BaseModel):
    target: str = Field(min_length=1, max_length=128)
    condition: str = Field(default="", max_length=32)


class WorkflowConditionPreview(BaseModel):
    expression: str = Field(max_length=4000)
    outputs: dict[str, str] = Field(max_length=100)
    branches: list[PreviewBranch] = Field(default_factory=list, max_length=100)


class WorkflowTransformPreview(BaseModel):
    expression: str = Field(max_length=1000)
    sample: str = Field(max_length=16000)


_runtime_creation_lock = threading.Lock()


def start_workflow_scheduler(state: Any) -> None:
    path = Path(os.environ.get("OPENJARVIS_WORKFLOW_DB") or (
        get_config_dir() / "workflow_runs.db"
    ))
    if path.is_file():
        _workflow_runtime_for_state(state).start_scheduling()


def get_workflow_runtime(request: Request) -> WorkflowRuntime:
    return _workflow_runtime_for_state(request.app.state)


def _workflow_runtime_for_state(state: Any) -> WorkflowRuntime:
    with _runtime_creation_lock:
        runtime = getattr(state, "workflow_runtime", None)
        if runtime is None:
            db_path = os.environ.get("OPENJARVIS_WORKFLOW_DB", "")
            store = WorkflowRunStore(db_path=db_path)
            runtime = WorkflowRuntime(
                system=state.workflow_system,
                store=store,
                approval_store=get_approval_store(),
                bus=getattr(state, "bus", None),
            )
            state.workflow_runtime = runtime
        return runtime


def _skipped_steps(run: dict) -> list[dict]:
    # A failed or still-running workflow can have untouched branches without
    # having reached their routing decisions.
    if run["status"] != "succeeded":
        return []
    outputs = {step["node_id"]: step["output"] for step in run["steps"]}
    incoming: dict[str, list[dict]] = {}
    for edge in run["graph"].get("edges", []):
        incoming.setdefault(edge["target"], []).append(edge)

    skipped = []
    for node in run["graph"]["nodes"]:
        node_id = node["id"]
        edges = incoming.get(node_id, [])
        if node_id in outputs or not edges:
            continue
        if any(
            edge["source"] in outputs
            and edge_matches_output(edge.get("condition", ""), outputs[edge["source"]])
            for edge in edges
        ):
            continue
        skipped.append({
            "node_id": node_id,
            "incoming": [{
                "source": edge["source"],
                "condition": edge.get("condition", ""),
                "reason": "condition_mismatch" if edge["source"] in outputs
                else "source_not_run",
            } for edge in edges],
        })
    return skipped


def create_workflow_runs_router() -> APIRouter:
    root = APIRouter(prefix="/v1/workflows", tags=["workflows"])
    router = APIRouter(prefix="/runs")
    _runtime = get_workflow_runtime

    @root.post("/preview-transform")
    def preview_transform(
        payload: WorkflowTransformPreview, response: Response,
    ) -> dict:
        node = WorkflowNode(
            id="preview-transform",
            node_type=NodeType.TRANSFORM,
            transform_expr=payload.expression,
        )
        result = WorkflowEngine().evaluate_transform(node, payload.sample)
        response.headers["Cache-Control"] = "no-store"
        return {"success": result.success, "output": result.output}

    @root.post("/preview-condition")
    def preview_condition(
        payload: WorkflowConditionPreview, response: Response,
    ) -> dict:
        if sum(len(key) + len(value) for key, value in payload.outputs.items()) > 16000:
            raise HTTPException(422, "Reduce the sample output size.")
        node = WorkflowNode(
            id="preview-condition",
            node_type=NodeType.CONDITION,
            condition_expr=payload.expression,
        )
        result = WorkflowEngine().evaluate_condition(node, payload.outputs)
        response.headers["Cache-Control"] = "no-store"
        return {
            "success": result.success,
            "output": result.output,
            "matched_targets": [
                edge.target for edge in payload.branches
                if result.success and edge_matches_output(edge.condition, result.output)
            ],
        }

    @root.post("/preview-index")
    def preview_index(
        payload: WorkflowIndexPreview, request: Request, response: Response,
    ) -> dict:
        query = payload.query.strip()
        source = payload.source.strip()
        if not query or not source:
            raise HTTPException(422, "Enter a search query and indexed source.")
        node = WorkflowNode(
            id="preview-index",
            node_type=NodeType.TOOL,
            config={
                "source": source,
                "allow_gmail_reference": payload.allow_gmail_reference,
                "max_sync_age_hours": payload.max_sync_age_hours,
            },
        )
        state = request.app.state
        result = WorkflowEngine(bus=getattr(state, "bus", None)).search_connector_index(
            node, query, getattr(state, "workflow_system", None),
        )
        response.headers["Cache-Control"] = "no-store"
        return {"success": result.success, "output": result.output}

    @router.post("", status_code=status.HTTP_202_ACCEPTED)
    async def start_run(payload: WorkflowRunRequest, request: Request) -> dict:
        try:
            graph = graph_from_dict(
                {"name": payload.name, "nodes": payload.nodes, "edges": payload.edges}
            )
            return _runtime(request).submit(
                graph,
                initial_input=payload.initial_input,
                context=payload.context,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except WorkflowRuntimeStopping as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.get("")
    async def list_runs(
        request: Request,
        run_status: str = Query(default="", alias="status"),
        limit: int = Query(default=50, ge=1, le=200),
        before: str = Query(default="", max_length=128),
        recent: bool = False,
        recurrence_id: str = Query(default="", max_length=128),
        approval_type: str = Query(default="", max_length=128),
        legacy_approval_node: str = Query(default="", max_length=128),
        input_contains: str = Query(default="", max_length=200),
    ) -> dict:
        if before and run_status == "scheduled" and not recent:
            raise HTTPException(
                status_code=400, detail="Scheduled runs are ordered by their start time"
            )
        runs = _runtime(request).store.list_runs(
            status=run_status, limit=limit, before=before, recent=recent,
            recurrence_id=recurrence_id, approval_type=approval_type,
            input_contains=input_contains.strip(),
            legacy_approval_node=legacy_approval_node,
        )
        return {
            "runs": runs, "count": len(runs), "before": before, "recent": recent,
            "recurrence_id": recurrence_id,
            "approval_type": approval_type, "input_contains": input_contains.strip(),
            "legacy_approval_node": legacy_approval_node,
        }

    @router.get("/{run_id}")
    async def get_run(run_id: str, request: Request) -> dict:
        runtime = _runtime(request)
        run = runtime.store.get_run(run_id, include_graph=True)
        if run is None:
            raise HTTPException(status_code=404, detail="Workflow run not found")
        decisions = []
        for node_id, action_id in run["context"].get("_workflow_approvals", {}).items():
            action = runtime.approval_store.get_action(action_id)
            if (
                action is None
                or action.status not in {STATUS_APPROVED, STATUS_DENIED}
                or action.payload.get("workflow_run_id") != run_id
                or action.payload.get("workflow_node_id") != node_id
            ):
                continue
            decisions.append({
                "node_id": node_id,
                "approval_id": action_id,
                "status": action.status,
                "decided_at": action.decision_at,
                "note": action.payload.get("decision_note", ""),
                "checks": action.payload.get("decision_checks", []),
            })
        return {
            **run, "review_decisions": decisions, "skipped_steps": _skipped_steps(run),
        }

    def require_approved_run(run_id: str, request: Request) -> None:
        run = _runtime(request).store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Workflow run not found")
        if run["status"] != "succeeded" or not any(
            step["metadata"].get("approval_status") == "approved"
            for step in run["steps"]
        ):
            raise HTTPException(
                status_code=409,
                detail="Only successful, approved runs support handoff.",
            )

    @router.post("/{run_id}/share-to-brain")
    def share_to_brain(run_id: str, payload: WorkflowHandoff, request: Request) -> dict:
        require_approved_run(run_id, request)
        summary = payload.summary.strip()
        if not summary:
            raise HTTPException(status_code=422, detail="Enter a handoff summary.")
        try:
            return {"added": append_workflow_handoff(run_id, summary)}
        except SharedBriefConflict as exc:
            raise HTTPException(
                status_code=409, detail="The brief changed. Try sharing again."
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/{run_id}/workstation-follow-ups")
    def workstation_follow_ups(run_id: str, request: Request) -> dict:
        require_approved_run(run_id, request)
        manager = getattr(request.app.state, "agent_manager", None)
        if manager is None:
            raise HTTPException(
                status_code=503, detail="Managed agents are unavailable."
            )
        return {"follow_ups": manager.list_workflow_handoffs(run_id)}

    @router.post("/{run_id}/assign-workstation")
    def assign_workstation(
        run_id: str, payload: WorkflowAgentHandoff, request: Request
    ) -> dict:
        require_approved_run(run_id, request)
        instruction = payload.instruction.strip()
        if not instruction:
            raise HTTPException(
                status_code=422, detail="Enter a follow-up instruction."
            )
        manager = getattr(request.app.state, "agent_manager", None)
        if manager is None:
            raise HTTPException(
                status_code=503, detail="Managed agents are unavailable."
            )
        try:
            route = payload.reporting_route
            queued = manager.queue_workflow_handoff(
                payload.agent_id, run_id, instruction,
                route=route.model_dump() if route else None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"queued": queued}

    @router.patch("/{run_id}/schedule")
    def reschedule_run(
        run_id: str, payload: RescheduleWorkflowRun, request: Request
    ) -> dict:
        if payload.scheduled_at <= time.time():
            raise HTTPException(status_code=422, detail="Choose a future start time.")
        try:
            return _runtime(request).reschedule(
                run_id, payload.scheduled_at, payload.expected_scheduled_at
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Workflow run not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except WorkflowRuntimeStopping as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
    async def cancel_run(run_id: str, request: Request) -> dict:
        runtime = _runtime(request)
        if runtime.store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Workflow run not found")
        if not runtime.cancel(run_id):
            raise HTTPException(
                status_code=409, detail="Workflow run is not cancellable"
            )
        return {"id": run_id, "cancel_requested": True}

    @router.post("/{run_id}/retry", status_code=status.HTTP_202_ACCEPTED)
    @router.post("/{run_id}/retry-with-input", status_code=status.HTTP_202_ACCEPTED)
    async def retry_run(
        run_id: str,
        request: Request,
        payload: RetryWorkflowInput | None = None,
        launch_key: str | None = Header(
            None, alias="Idempotency-Key", min_length=1, max_length=128
        ),
    ) -> dict:
        try:
            return _runtime(request).retry(
                run_id,
                initial_input=payload.initial_input if payload else None,
                launch_key=launch_key,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Workflow run not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except WorkflowRuntimeStopping as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/{run_id}/resume", status_code=status.HTTP_202_ACCEPTED)
    async def resume_run(run_id: str, request: Request) -> dict:
        try:
            return _runtime(request).resume(run_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Workflow run not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except WorkflowRuntimeStopping as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @root.post("/definitions", status_code=status.HTTP_201_CREATED)
    def save_definition(payload: WorkflowDefinition, request: Request) -> dict:
        try:
            graph = graph_from_dict(payload.model_dump())
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _runtime(request).store.save_definition(graph_to_dict(graph))

    @root.put("/definitions/{definition_id}")
    def update_definition(
        definition_id: str, payload: WorkflowDefinitionUpdate, request: Request
    ) -> dict:
        try:
            graph = graph_from_dict(payload.model_dump())
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            saved = _runtime(request).store.update_definition(
                definition_id,
                graph_to_dict(graph),
                expected_revision=payload.expected_revision,
            )
        except WorkflowDefinitionConflict as exc:
            raise HTTPException(
                status_code=409,
                detail=f"{exc} Reload the saved workflow or use Save as copy.",
            ) from exc
        if saved is None:
            raise HTTPException(status_code=404, detail="Workflow definition not found")
        return saved

    @root.get("/definitions")
    def list_definitions(
        request: Request,
        limit: int = Query(50, ge=1, le=200),
        before: str = Query("", max_length=128),
        search: str = Query("", max_length=200),
    ) -> dict:
        items = _runtime(request).store.list_definitions(
            limit + 1, before=before, search=search.strip()
        )
        definitions = items[:limit]
        return {
            "definitions": definitions,
            "count": len(definitions),
            "next_before": definitions[-1]["id"] if len(items) > limit else None,
        }

    @root.get("/definitions/{definition_id}")
    def get_definition(definition_id: str, request: Request) -> dict:
        definition = _runtime(request).store.get_definition(definition_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="Workflow definition not found")
        return definition

    @root.post("/definitions/{definition_id}/runs", status_code=202)
    def run_definition(
        definition_id: str,
        payload: SavedWorkflowInputs,
        request: Request,
        launch_key: str | None = Header(
            None, alias="Idempotency-Key", min_length=1, max_length=128
        ),
    ) -> dict:
        if getattr(request.state, "scoped_workflow_launch", False):
            if not launch_key or not payload.expected_revision or payload.context:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Use a retry key and expected revision. Omit workflow context."
                    ),
                )
            result = launch_definition(
                definition_id, payload, request, "scoped:" + launch_key
            )
            return {"id": result["id"], "status": result["status"]}
        return launch_definition(definition_id, payload, request, launch_key)

    @root.post("/definitions/{definition_id}/schedule", status_code=202)
    def schedule_definition(
        definition_id: str,
        payload: ScheduledWorkflowInputs,
        request: Request,
        launch_key: str | None = Header(
            None, alias="Idempotency-Key", min_length=1, max_length=128
        ),
    ) -> dict:
        return launch_definition(
            definition_id, payload, request, launch_key, payload.scheduled_at
        )

    @root.get("/recurrences/upcoming")
    def upcoming_recurrences(
        request: Request, limit: int = Query(default=10, ge=1, le=50)
    ) -> dict:
        return {"recurrences": _runtime(request).store.upcoming_recurrences(limit)}

    @root.get("/definitions/{definition_id}/recurrences")
    def list_recurrences(definition_id: str, request: Request) -> dict:
        return {"recurrences": _runtime(request).store.list_recurrences(definition_id)}

    @root.post("/definitions/{definition_id}/recurrences", status_code=201)
    def create_recurrence(
        definition_id: str, payload: RecurringWorkflowInputs, request: Request
    ) -> dict:
        return save_recurrence(definition_id, payload, request)

    @root.post("/definitions/{definition_id}/recurrences/pinned", status_code=201)
    def create_pinned_recurrence(
        definition_id: str, payload: PinnedRecurringWorkflowInputs, request: Request
    ) -> dict:
        return save_recurrence(
            definition_id, payload, request,
            definition_revision=payload.definition_revision,
        )

    def save_recurrence(
        definition_id: str, payload: RecurringWorkflowInputs, request: Request,
        *, definition_revision: str | None = None,
    ) -> dict:
        if payload.first_due_at <= time.time():
            raise HTTPException(status_code=400, detail="Choose a future start time")
        runtime = _runtime(request)
        try:
            recurrence = runtime.store.save_recurrence(
                definition_id, payload.initial_input,
                payload.first_due_at, payload.interval_seconds,
                definition_revision=definition_revision,
            )
        except WorkflowDefinitionConflict as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Workflow definition not found"
            ) from exc
        runtime.start_scheduling()
        return recurrence

    @root.put("/definitions/{definition_id}/recurrences/{recurrence_id}")
    def edit_recurrence(
        definition_id: str, recurrence_id: str,
        payload: RecurringWorkflowEdit, request: Request,
    ) -> dict:
        if payload.first_due_at <= time.time():
            raise HTTPException(status_code=400, detail="Choose a future start time")
        runtime = _runtime(request)
        try:
            recurrence = runtime.store.update_recurrence(
                definition_id, recurrence_id, initial_input=payload.initial_input,
                next_due_at=payload.first_due_at,
                interval_seconds=payload.interval_seconds,
                expected_revision=payload.expected_revision,
            )
        except WorkflowDefinitionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if recurrence is None:
            raise HTTPException(status_code=404, detail="Recurring schedule not found")
        if not recurrence["paused"]:
            runtime.start_scheduling()
        return recurrence

    @root.patch("/definitions/{definition_id}/recurrences/{recurrence_id}")
    def update_recurrence_status(
        definition_id: str, recurrence_id: str,
        payload: RecurringWorkflowStatus, request: Request,
    ) -> dict:
        runtime = _runtime(request)
        recurrence = runtime.store.set_recurrence_paused(
            definition_id, recurrence_id, paused=payload.paused, now=time.time(),
        )
        if recurrence is None:
            raise HTTPException(status_code=404, detail="Recurring schedule not found")
        if not payload.paused:
            runtime.start_scheduling()
        return recurrence

    @root.delete(
        "/definitions/{definition_id}/recurrences/{recurrence_id}", status_code=204
    )
    def delete_recurrence(
        definition_id: str, recurrence_id: str, request: Request
    ) -> Response:
        if not _runtime(request).store.delete_recurrence(definition_id, recurrence_id):
            raise HTTPException(status_code=404, detail="Recurring schedule not found")
        return Response(status_code=204)

    def launch_definition(
        definition_id: str,
        payload: SavedWorkflowInputs,
        request: Request,
        launch_key: str | None,
        scheduled_at: float | None = None,
    ) -> dict:
        try:
            return _runtime(request).submit_saved(
                definition_id,
                initial_input=payload.initial_input,
                context=payload.context,
                launch_key=launch_key,
                scheduled_at=scheduled_at,
                expected_revision=payload.expected_revision,
            )
        except WorkflowDefinitionConflict as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        except WorkflowLaunchConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Workflow definition not found"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Saved workflow needs repair. {exc}",
            ) from exc
        except WorkflowRuntimeStopping as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    root.include_router(router)
    return root


__all__ = ["WorkflowRunRequest", "create_workflow_runs_router"]
