"""Persistent marketing drafts and human review decisions."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import closing
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from openjarvis.core.paths import get_config_dir
from openjarvis.security.file_utils import secure_create

router = APIRouter(prefix="/v1/social-content", tags=["social-content"])

Channel = Literal[
    "instagram",
    "facebook",
    "linkedin",
    "x",
    "tiktok",
    "youtube",
    "pinterest",
    "threads",
]


class DraftFields(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    caption: str = Field(min_length=1, max_length=8000)
    channels: list[Channel] = Field(min_length=1, max_length=8)

    @field_validator("title", "caption", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("channels")
    @classmethod
    def unique_channels(cls, channels: list[Channel]) -> list[Channel]:
        if len(channels) != len(set(channels)):
            raise ValueError("Choose each channel once")
        return channels


class DraftRevision(BaseModel):
    revision: int = Field(ge=1)


class DraftEdit(DraftFields, DraftRevision):
    pass


class DraftAction(DraftRevision):
    action: Literal["submit_review", "return_to_draft", "approve", "plan"]
    scheduled_at: float | None = Field(default=None, gt=0, allow_inf_nan=False)


def _connect() -> sqlite3.Connection:
    path = secure_create(get_config_dir() / "social_content.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _initialize(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS social_drafts (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            caption TEXT NOT NULL,
            channels TEXT NOT NULL,
            state TEXT NOT NULL,
            scheduled_at REAL,
            revision INTEGER NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )


def _draft(conn: sqlite3.Connection, draft_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM social_drafts WHERE id = ?", (draft_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Content draft not found")
    return _serialize(row)


def _serialize(row: sqlite3.Row) -> dict:
    return {**dict(row), "channels": json.loads(row["channels"])}


@router.get("/summary")
def summarize_drafts(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    with closing(_connect()) as conn:
        _initialize(conn)
        rows = conn.execute(
            """
            SELECT id, title, channels, state, scheduled_at,
                   (SELECT COUNT(*) FROM social_drafts WHERE state = 'review')
                       AS review_count
            FROM social_drafts
            ORDER BY CASE state WHEN 'review' THEN 0 WHEN 'planned' THEN 1 ELSE 2 END,
                     updated_at DESC, id
            LIMIT 4
            """
        ).fetchall()
    items = [_serialize(row) for row in rows]
    review_count = rows[0]["review_count"] if rows else 0
    for item in items:
        del item["review_count"]
    return {"review_count": review_count, "items": items}


@router.get("/drafts")
def list_drafts(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    with closing(_connect()) as conn:
        _initialize(conn)
        rows = conn.execute(
            "SELECT * FROM social_drafts ORDER BY updated_at DESC, id LIMIT 100"
        ).fetchall()
        return {"drafts": [_serialize(row) for row in rows]}


@router.post("/drafts", status_code=201)
def create_draft(fields: DraftFields) -> dict:
    now = time.time()
    draft_id = uuid.uuid4().hex
    with closing(_connect()) as conn, conn:
        _initialize(conn)
        conn.execute(
            "INSERT INTO social_drafts VALUES (?, ?, ?, ?, 'draft', NULL, 1, ?, ?)",
            (
                draft_id,
                fields.title,
                fields.caption,
                json.dumps(fields.channels),
                now,
                now,
            ),
        )
        return _draft(conn, draft_id)


@router.put("/drafts/{draft_id}")
def edit_draft(draft_id: str, fields: DraftEdit) -> dict:
    with closing(_connect()) as conn, conn:
        _initialize(conn)
        result = conn.execute(
            "UPDATE social_drafts SET title = ?, caption = ?, channels = ?, "
            "revision = revision + 1, updated_at = ? "
            "WHERE id = ? AND revision = ? AND state = 'draft'",
            (
                fields.title,
                fields.caption,
                json.dumps(fields.channels),
                time.time(),
                draft_id,
                fields.revision,
            ),
        )
        draft = _draft(conn, draft_id)
        if not result.rowcount:
            raise HTTPException(
                status_code=409,
                detail="Refresh the draft or return it to draft to edit.",
            )
        return draft


@router.post("/drafts/{draft_id}/actions")
def transition_draft(draft_id: str, decision: DraftAction) -> dict:
    transitions = {
        "submit_review": (("draft",), "review"),
        "return_to_draft": (("review", "approved", "planned"), "draft"),
        "approve": (("review",), "approved"),
        "plan": (("approved", "planned"), "planned"),
    }
    previous, new_state = transitions[decision.action]
    now = time.time()
    start = decision.scheduled_at if decision.action == "plan" else None
    if decision.action == "plan" and (start is None or start <= now):
        raise HTTPException(status_code=422, detail="Choose a future planning time.")
    progress_filter = ", ".join("?" for _ in previous)
    with closing(_connect()) as conn, conn:
        _initialize(conn)
        result = conn.execute(
            "UPDATE social_drafts SET state = ?, scheduled_at = ?, "
            "revision = revision + 1, updated_at = ? "
            f"WHERE id = ? AND revision = ? AND state IN ({progress_filter})",
            (new_state, start, now, draft_id, decision.revision, *previous),
        )
        draft = _draft(conn, draft_id)
        if not result.rowcount:
            raise HTTPException(
                status_code=409,
                detail="The draft changed or this decision is unavailable.",
            )
        return draft
