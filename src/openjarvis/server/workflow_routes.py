"""Durable workflow run API for the command center."""

from __future__ import annotations

import os
import threading
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from openjarvis.server.approval_routes import get_approval_store
from openjarvis.workflow.runtime import WorkflowRuntime
from openjarvis.workflow.serialization import graph_from_dict
from openjarvis.workflow.store import WorkflowRunStore


class WorkflowRunRequest(BaseModel):
    name: str = "workflow"
    nodes: list[Dict[str, Any]] = Field(min_length=1)
    edges: list[Dict[str, Any]] = Field(default_factory=list)
    initial_input: str = ""
    context: Dict[str, Any] = Field(default_factory=dict)


def create_workflow_runs_router() -> APIRouter:
    router = APIRouter(prefix="/v1/workflows/runs", tags=["workflow-runs"])
    creation_lock = threading.Lock()

    def _runtime(request: Request) -> WorkflowRuntime:
        runtime = getattr(request.app.state, "workflow_runtime", None)
        if runtime is not None:
            return runtime
        with creation_lock:
            runtime = getattr(request.app.state, "workflow_runtime", None)
            if runtime is None:
                db_path = os.environ.get("OPENJARVIS_WORKFLOW_DB", "")
                store = WorkflowRunStore(db_path=db_path)
                runtime = WorkflowRuntime(
                    system=request.app.state.workflow_system,
                    store=store,
                    approval_store=get_approval_store(),
                    bus=getattr(request.app.state, "bus", None),
                )
                request.app.state.workflow_runtime = runtime
        return runtime

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

    return router


__all__ = ["WorkflowRunRequest", "create_workflow_runs_router"]
