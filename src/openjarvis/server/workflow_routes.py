"""Durable workflow run API for the command center."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from openjarvis.core.paths import get_config_dir
from openjarvis.server.approval_routes import get_approval_store
from openjarvis.workflow.runtime import WorkflowRuntime, WorkflowRuntimeStopping
from openjarvis.workflow.serialization import graph_from_dict, graph_to_dict
from openjarvis.workflow.store import (
    WorkflowDefinitionConflict,
    WorkflowLaunchConflict,
    WorkflowRunStore,
)


class WorkflowDefinition(BaseModel):
    name: str = "workflow"
    nodes: list[Dict[str, Any]] = Field(min_length=1)
    edges: list[Dict[str, Any]] = Field(default_factory=list)


class WorkflowInputs(BaseModel):
    initial_input: str = ""
    context: Dict[str, Any] = Field(default_factory=dict)


class ScheduledWorkflowInputs(WorkflowInputs):
    scheduled_at: float = Field(gt=0, allow_inf_nan=False)


class RescheduleWorkflowRun(BaseModel):
    scheduled_at: float = Field(gt=0, allow_inf_nan=False)
    expected_scheduled_at: float = Field(gt=0, allow_inf_nan=False)


class WorkflowDefinitionUpdate(WorkflowDefinition):
    expected_revision: str | None = None


class WorkflowRunRequest(WorkflowDefinition, WorkflowInputs):
    pass


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


def create_workflow_runs_router() -> APIRouter:
    root = APIRouter(prefix="/v1/workflows", tags=["workflows"])
    router = APIRouter(prefix="/runs")
    _runtime = get_workflow_runtime

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
    ) -> dict:
        runs = _runtime(request).store.list_runs(status=run_status, limit=limit)
        return {"runs": runs, "count": len(runs)}

    @router.get("/{run_id}")
    async def get_run(run_id: str, request: Request) -> dict:
        run = _runtime(request).store.get_run(run_id, include_graph=True)
        if run is None:
            raise HTTPException(status_code=404, detail="Workflow run not found")
        return run

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
    async def retry_run(run_id: str, request: Request) -> dict:
        try:
            return _runtime(request).retry(run_id)
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
        request: Request, limit: int = Query(50, ge=1, le=200)
    ) -> dict:
        definitions = _runtime(request).store.list_definitions(limit)
        return {"definitions": definitions, "count": len(definitions)}

    @root.get("/definitions/{definition_id}")
    def get_definition(definition_id: str, request: Request) -> dict:
        definition = _runtime(request).store.get_definition(definition_id)
        if definition is None:
            raise HTTPException(status_code=404, detail="Workflow definition not found")
        return definition

    @root.post("/definitions/{definition_id}/runs", status_code=202)
    def run_definition(
        definition_id: str,
        payload: WorkflowInputs,
        request: Request,
        launch_key: str | None = Header(
            None, alias="Idempotency-Key", min_length=1, max_length=128
        ),
    ) -> dict:
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

    def launch_definition(
        definition_id: str,
        payload: WorkflowInputs,
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
            )
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
