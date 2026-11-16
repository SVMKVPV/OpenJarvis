"""Local lead register with source references."""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import closing

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from openjarvis.core.paths import get_config_dir
from openjarvis.security.file_utils import secure_create
from openjarvis.server.workflow_routes import get_workflow_runtime

router = APIRouter(prefix="/v1/leads", tags=["leads"])


class LeadInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    organization: str = Field(min_length=1, max_length=160)
    source_reference: str = Field(min_length=1, max_length=1000)
    workflow_run_id: str | None = Field(default=None, min_length=1, max_length=128)


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

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lead_workflow_provenance (
            lead_id TEXT PRIMARY KEY REFERENCES leads(id),
            workflow_run_id TEXT NOT NULL
        )
        """
    )


@router.get("")
def list_leads(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    with closing(_connect()) as conn:
        _initialize(conn)
        rows = conn.execute(
            """
            SELECT leads.*, lead_workflow_provenance.workflow_run_id
            FROM leads LEFT JOIN lead_workflow_provenance ON lead_id = leads.id
            ORDER BY created_at DESC, leads.id LIMIT 20
            """
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
def add_lead(fields: LeadInput, request: Request) -> dict:
    if fields.workflow_run_id:
        run = get_workflow_runtime(request).store.get_run(fields.workflow_run_id)
        if run is None:
            raise HTTPException(404, "Workflow run not found")
        approved = run["status"] == "succeeded" and any(
            step["node_id"] == "lead-review"
            and step["metadata"].get("approval_status") == "approved"
            for step in run["steps"]
        )
        if not approved:
            raise HTTPException(409, "The lead discovery workflow needs approval")
        candidate = next(
            (step["output"] for step in reversed(run["steps"])
             if step["node_id"] == "lead-candidates" and step["success"]),
            "",
        )
        if any(
            value.casefold() not in candidate.casefold()
            for value in (fields.organization, fields.source_reference)
        ):
            raise HTTPException(400, "Use the organization and source from the review")

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
        if fields.workflow_run_id:
            conn.execute(
                "INSERT INTO lead_workflow_provenance VALUES (?, ?)",
                (lead["id"], fields.workflow_run_id),
            )
    return lead
