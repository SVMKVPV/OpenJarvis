"""Shared Brain brief for clients using the same backend profile."""

from __future__ import annotations

import sqlite3
from contextlib import closing

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from openjarvis.core.paths import get_config_dir
from openjarvis.security.file_utils import secure_create

router = APIRouter(prefix="/v1/shared-brain", tags=["shared-brain"])


class SharedBrief(BaseModel):
    context: str = Field(max_length=4000)
    revision: int = Field(ge=0)


def _connect() -> sqlite3.Connection:
    path = secure_create(get_config_dir() / "shared_brain.db")
    return sqlite3.connect(path)


def _initialize(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS shared_brief ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), "
        "context TEXT NOT NULL, revision INTEGER NOT NULL)"
    )


@router.get("/brief")
def get_brief(response: Response) -> SharedBrief:
    response.headers["Cache-Control"] = "no-store"
    with closing(_connect()) as conn:
        _initialize(conn)
        row = conn.execute(
            "SELECT context, revision FROM shared_brief WHERE id = 1"
        ).fetchone()
    if row is None:
        return SharedBrief(context="", revision=0)
    return SharedBrief(context=row[0], revision=row[1])


@router.put("/brief")
def save_brief(brief: SharedBrief) -> SharedBrief:
    with closing(_connect()) as conn, conn:
        _initialize(conn)
        conn.execute(
            "INSERT OR IGNORE INTO shared_brief (id, context, revision) "
            "VALUES (1, '', 0)"
        )
        result = conn.execute(
            "UPDATE shared_brief SET context = ?, revision = revision + 1 "
            "WHERE id = 1 AND revision = ?",
            (brief.context, brief.revision),
        )
        if not result.rowcount:
            raise HTTPException(
                status_code=409, detail="The Shared Brain brief has changed."
            )
    return SharedBrief(context=brief.context, revision=brief.revision + 1)
