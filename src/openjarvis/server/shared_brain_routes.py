"""Shared Brain brief for clients using the same backend profile."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from openjarvis.core.shared_brain import SharedBriefConflict, load_brief, update_brief

router = APIRouter(prefix="/v1/shared-brain", tags=["shared-brain"])


class SharedBrief(BaseModel):
    context: str = Field(max_length=4000)
    revision: int = Field(ge=0)


@router.get("/brief")
def get_brief(response: Response) -> SharedBrief:
    response.headers["Cache-Control"] = "no-store"
    context, revision = load_brief()
    return SharedBrief(context=context, revision=revision)


@router.put("/brief")
def save_brief(brief: SharedBrief) -> SharedBrief:
    try:
        revision = update_brief(brief.context, brief.revision)
    except SharedBriefConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SharedBrief(context=brief.context, revision=revision)
