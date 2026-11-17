"""Reviewed month-to-date revenue records for the Finance workstation."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from openjarvis.core.paths import get_config_dir
from openjarvis.security.file_utils import secure_create

router = APIRouter(prefix="/v1/finance/revenue", tags=["finance"])
_MONTH = r"^[0-9]{4}-(0[1-9]|1[0-2])$"


class RevenueInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    as_of: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount: str = Field(pattern=r"^-?[0-9]{1,12}(\.[0-9]{1,4})?$")
    source_reference: str = Field(min_length=1, max_length=240)


def _connect() -> sqlite3.Connection:
    db = sqlite3.connect(secure_create(get_config_dir() / "finance-revenue.db"))
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE IF NOT EXISTS revenue (
               month TEXT NOT NULL, currency TEXT NOT NULL, as_of TEXT NOT NULL,
               amount TEXT NOT NULL, source_reference TEXT NOT NULL,
               PRIMARY KEY (month, currency)
           )"""
    )
    return db


@router.get("")
def list_revenue(month: str = Query(pattern=_MONTH)) -> dict:
    with closing(_connect()) as db:
        records = db.execute(
            "SELECT * FROM revenue WHERE month = ? ORDER BY currency", (month,)
        ).fetchall()
    return {"month": month, "records": [dict(row) for row in records]}


@router.put("")
def save_revenue(payload: RevenueInput) -> dict:
    as_of = payload.as_of.isoformat()
    record = payload.model_dump(mode="json") | {"month": as_of[:7]}
    with closing(_connect()) as db, db:
        result = db.execute(
            """INSERT INTO revenue (month, currency, as_of, amount, source_reference)
               VALUES (:month, :currency, :as_of, :amount, :source_reference)
               ON CONFLICT(month, currency) DO UPDATE SET
                   as_of = excluded.as_of, amount = excluded.amount,
                   source_reference = excluded.source_reference
               WHERE excluded.as_of >= revenue.as_of""",
            record,
        )
        if not result.rowcount:
            raise HTTPException(
                status_code=409,
                detail="A newer revenue total is already saved for this currency.",
            )
    return record
