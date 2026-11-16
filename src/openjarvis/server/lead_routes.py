"""Local lead register with source references."""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import closing

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from openjarvis.core.paths import get_config_dir
from openjarvis.security.file_utils import secure_create

router = APIRouter(prefix="/v1/leads", tags=["leads"])


class LeadInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    organization: str = Field(min_length=1, max_length=160)
    source_reference: str = Field(min_length=1, max_length=1000)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(secure_create(get_config_dir() / "leads.db"))
    conn.row_factory = sqlite3.Row
    return conn


def _initialize(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY,
            organization TEXT NOT NULL COLLATE NOCASE,
            source_reference TEXT NOT NULL,
            created_at REAL NOT NULL,
            UNIQUE(organization, source_reference)
        )
        """
    )


@router.get("")
def list_leads(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    with closing(_connect()) as conn:
        _initialize(conn)
        rows = conn.execute(
            "SELECT * FROM leads ORDER BY created_at DESC, id LIMIT 20"
        ).fetchall()
    return {"leads": [dict(row) for row in rows]}


@router.get("/summary")
def lead_summary(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    with closing(_connect()) as conn:
        _initialize(conn)
        count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    return {"count": count}


@router.post("", status_code=201)
def add_lead(fields: LeadInput) -> dict:
    lead = {"id": uuid.uuid4().hex, **fields.model_dump(), "created_at": time.time()}
    with closing(_connect()) as conn, conn:
        _initialize(conn)
        inserted = conn.execute(
            """
            INSERT INTO leads (id, organization, source_reference, created_at)
            VALUES (:id, :organization, :source_reference, :created_at)
            ON CONFLICT(organization, source_reference) DO NOTHING
            """,
            lead,
        )
        if not inserted.rowcount:
            raise HTTPException(409, "This organization and source are already saved")
    return lead
