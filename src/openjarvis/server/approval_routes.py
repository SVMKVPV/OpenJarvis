"""REST endpoints for the proactive-agent approval queue."""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from openjarvis.tools.approval_store import (
    STATUS_APPROVED,
    STATUS_DENIED,
    ApprovalStore,
    PendingAction,
)

try:
    from fastapi import APIRouter, HTTPException, Request
except ImportError:
    raise ImportError("fastapi is required for approval routes")

logger = logging.getLogger(__name__)

router = APIRouter()

# Singleton that shares the same DB file as ProactiveAgent (WAL mode is safe)
_store: Optional[ApprovalStore] = None


def get_approval_store() -> ApprovalStore:
    global _store
    if _store is None:
        _store = ApprovalStore()
    return _store


_get_store = get_approval_store


def _workflow_runtime(request: Request):
    runtime = getattr(request.app.state, "workflow_runtime", None)
    if runtime is None and hasattr(request.app.state, "workflow_system"):
        from openjarvis.server.workflow_routes import get_workflow_runtime

        runtime = get_workflow_runtime(request)
    return runtime


def _serialize(action: PendingAction) -> Dict[str, Any]:
    return {
        "id": action.id,
        "action_type": action.action_type,
        "description": action.description,
        "payload": action.payload,
        "permission_key": action.permission_key,
        "tier": action.tier,
        "status": action.status,
        "created_at": action.created_at,
        "expires_at": action.expires_at,
    }


@router.get("/v1/approvals/pending")
async def list_pending_approvals(request: Request) -> Dict[str, Any]:
    store = _get_store()
    store.expire_stale()
    actions = []
    for action in store.list_pending():
        if "workflow_node_id" in action.payload:
            runtime = _workflow_runtime(request)
            if runtime is None or not runtime.is_waiting_for(action):
                continue
        actions.append(_serialize(action))
    return {"actions": actions, "count": len(actions)}


def _decide(
    action_id: str, request: Request, decision: str, *, note: str = "",
    checked_items: tuple[int, ...] = (),
) -> Dict[str, Any]:
    store = _get_store()
    action = store.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    if "workflow_node_id" in action.payload:
        raw_items = action.payload.get("review_checklist")
        items = (
            [item for item in raw_items if isinstance(item, str) and item.strip()]
            if isinstance(raw_items, list) else []
        )
        if any(index < 0 or index >= len(items) for index in checked_items):
            raise HTTPException(
                status_code=422, detail="Invalid reviewer checklist item"
            )
        checks = [items[index] for index in sorted(set(checked_items))]
        runtime = _workflow_runtime(request)
        decided = runtime is not None and runtime.decide_approval(
            action, decision, note=note, checks=checks
        )
    elif note or checked_items:
        raise HTTPException(400, "Review details require a workflow approval")
    else:
        decided = store.decide_pending(action_id, decision)
    if not decided:
        raise HTTPException(status_code=409, detail="Action is no longer pending")
    logger.info("Action %s %s via UI", action_id, decision)
    return {"status": decision, "id": action_id}


@router.post("/v1/approvals/{action_id}/approve")
async def approve_action(action_id: str, request: Request) -> Dict[str, Any]:
    return _decide(action_id, request, STATUS_APPROVED)


@router.post("/v1/approvals/{action_id}/deny")
async def deny_action(action_id: str, request: Request) -> Dict[str, Any]:
    return _decide(action_id, request, STATUS_DENIED)


class WorkflowDecisionNote(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    decision: Literal["approve", "deny"]
    note: str = Field(default="", max_length=2000)
    checked_items: tuple[StrictInt, ...] = Field(default=(), max_length=4000)


@router.post("/v1/approvals/{action_id}/decide-with-note")
async def decide_workflow_with_note(
    action_id: str, request: Request, payload: WorkflowDecisionNote
) -> Dict[str, Any]:
    decision = STATUS_APPROVED if payload.decision == "approve" else STATUS_DENIED
    if not payload.note and not payload.checked_items:
        raise HTTPException(422, "Enter a note or select a reviewer checklist item")
    return _decide(
        action_id, request, decision, note=payload.note,
        checked_items=payload.checked_items,
    )


__all__ = ["get_approval_store", "router"]
