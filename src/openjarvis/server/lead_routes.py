"""Local lead register with source references."""

from __future__ import annotations

import json
import re
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


def _approved_lead_review(run_id: str, request: Request) -> tuple[str, list | None]:
    run = get_workflow_runtime(request).store.get_run(run_id, include_graph=True)
    if run is None:
        raise HTTPException(404, "Workflow run not found")
    if run["status"] != "succeeded" or not any(
        step["node_id"] == "lead-review"
        and step["metadata"].get("approval_status") == "approved"
        for step in run["steps"]
    ):
        raise HTTPException(409, "The lead discovery workflow needs approval")

    outputs = {
        step["node_id"]: step["output"] for step in run["steps"] if step["success"]
    }
    candidate = outputs.get("lead-candidates", "")
    review_node = next(
        (node for node in run["graph"]["nodes"] if node["id"] == "lead-review"),
        {},
    )
    payload = review_node.get("config", {}).get("payload")
    structured = (
        isinstance(payload, dict) and payload.get("candidate_format") == "json_v1"
    )
    if not structured:
        return candidate, None
    return candidate, _reviewed_candidates(candidate, outputs.get("lead-source", ""))


def _reviewed_candidates(text: str, source: str) -> list[dict[str, str]]:
    text = text.strip()
    fence = re.fullmatch(r"```(?:json)?\s+(.*?)\s*```", text, re.I | re.S)
    try:
        result = json.loads(fence.group(1) if fence else text)
    except (ValueError, RecursionError):
        return []
    candidates = result.get("candidates") if isinstance(result, dict) else None
    if not isinstance(candidates, list):
        return []
    seen = set()
    evidence = source.casefold()
    rows = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        org, ref = item.get("organization"), item.get("source_reference")
        if not isinstance(org, str) or not isinstance(ref, str):
            continue
        org, ref = org.strip(), ref.strip()
        if not (0 < len(org) <= 160 and 0 < len(ref) <= 1000):
            continue
        key = org.casefold()
        if key in seen or key not in evidence or ref.casefold() not in evidence:
            continue
        seen.add(key)
        rows.append({"organization": org, "source_reference": ref})
    return rows


@router.get("/reviewed-candidates/{run_id}")
def get_reviewed_candidates(run_id: str, request: Request, response: Response) -> dict:
    _, candidates = _approved_lead_review(run_id, request)
    response.headers["Cache-Control"] = "no-store"
    return {"candidates": candidates}


@router.post("", status_code=201)
def add_lead(fields: LeadInput, request: Request, response: Response) -> dict:
    if fields.workflow_run_id:
        original, candidates = _approved_lead_review(fields.workflow_run_id, request)
        pair = {
            "organization": fields.organization,
            "source_reference": fields.source_reference,
        }
        if candidates is None:
            matches = all(
                value.casefold() in original.casefold() for value in pair.values()
            )
        else:
            matches = pair in candidates
        if not matches:
            raise HTTPException(
                400, "Use an organization and source pair from the review"
            )

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
            if fields.workflow_run_id:
                existing = conn.execute(
                    """
                    SELECT leads.*, provenance.workflow_run_id
                    FROM leads
                    JOIN lead_workflow_provenance AS provenance
                        ON provenance.lead_id = leads.id
                    WHERE organization = ? AND source_reference = ?
                        AND workflow_run_id = ?
                    """,
                    (
                        fields.organization,
                        fields.source_reference,
                        fields.workflow_run_id,
                    ),
                ).fetchone()
                if existing is not None:
                    response.status_code = 200
                    return dict(existing)
            raise HTTPException(409, "This organization and source are already saved")
        if fields.workflow_run_id:
            conn.execute(
                "INSERT INTO lead_workflow_provenance VALUES (?, ?)",
                (lead["id"], fields.workflow_run_id),
            )
    return lead
