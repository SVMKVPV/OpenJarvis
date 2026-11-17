from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.finance_revenue_routes import router  # noqa: E402


def test_revenue_keeps_precision_and_newest_report(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    path = "/v1/finance/revenue"
    report = {
        "as_of": "2026-11-15",
        "currency": "AUD",
        "amount": "154.2001",
        "source_reference": "Reviewed settlement report",
    }
    with TestClient(app) as client:
        assert client.get(path, params={"month": "2026-11"}).json()["records"] == []
        assert client.put(path, json=report).status_code == 200
        assert client.put(
            path, json={**report, "currency": "USD", "amount": "0.00"},
        ).status_code == 200
        assert client.put(
            path, json={**report, "as_of": "2026-11-14"},
        ).status_code == 409
        assert client.put(path, json={**report, "amount": 154.2}).status_code == 422

    with TestClient(app) as client:
        assert client.get(path, params={"month": "2026-10"}).json()["records"] == []
        records = client.get(path, params={"month": "2026-11"}).json()["records"]
        assert [(row["currency"], row["amount"]) for row in records] == [
            ("AUD", "154.2001"), ("USD", "0.00"),
        ]
        assert records[0]["source_reference"] == report["source_reference"]


def test_revenue_history_records_changes_only(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    path = "/v1/finance/revenue"
    first = {
        "as_of": "2026-11-15", "currency": "AUD",
        "amount": "11.00", "source_reference": "Initial report",
    }
    corrected = {**first, "amount": "10.99", "source_reference": "Adjusted report"}
    with TestClient(app) as client:
        assert client.put(path, json=first).status_code == 200
        assert client.put(path, json=corrected).status_code == 200
        assert client.put(path, json=corrected).status_code == 200
        older = client.put(path, json={**first, "as_of": "2026-11-14"})
        assert older.status_code == 409
        params = {"month": "2026-11", "include_history": True}
        result = client.get(path, params=params).json()
        assert result["records"] == [{
            **corrected, "month": "2026-11", "revision": result["history"][0]["id"],
        }]
        assert [row["source_reference"] for row in result["history"]] == [
            "Adjusted report", "Initial report",
        ]
        assert all(row["recorded_at"] for row in result["history"])
        assert "history" not in client.get(path, params={"month": "2026-11"}).json()

def test_revenue_history_keeps_total_from_older_database(tmp_path, monkeypatch):
    import sqlite3
    from contextlib import closing

    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    with closing(sqlite3.connect(tmp_path / "finance-revenue.db")) as db, db:
        db.execute(
            "CREATE TABLE revenue (month TEXT, currency TEXT, as_of TEXT, "
            "amount TEXT, source_reference TEXT, PRIMARY KEY (month, currency))"
        )
        db.execute(
            "INSERT INTO revenue VALUES (?, ?, ?, ?, ?)",
            ("2026-11", "AUD", "2026-11-15", "100.00", "Original statement"),
        )
    app = FastAPI()
    app.include_router(router)
    path = "/v1/finance/revenue"
    with TestClient(app) as client:
        assert client.put(path, json={
            "as_of": "2026-11-16", "currency": "AUD",
            "amount": "110.00", "source_reference": "Updated statement",
        }).status_code == 200
        result = client.get(path, params={
            "month": "2026-11", "include_history": True,
        }).json()
        current, baseline = result["history"]
        assert current["amount"] == "110.00"
        assert baseline["amount"] == "100.00"
        assert baseline["recorded_at"] is None


def test_revenue_rejects_stale_edits_and_accepts_identical_retries(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    path = "/v1/finance/revenue"
    original = {
        "as_of": "2026-11-15",
        "currency": "AUD",
        "amount": "100.00",
        "source_reference": "Reviewed report",
    }
    with TestClient(app) as client:
        initial = client.put(path, json={**original, "expected_revision": None})
        assert initial.status_code == 200
        revision = initial.json()["revision"]
        saved = client.put(path, json={**original, "amount": "120.00", "expected_revision": revision})
        assert saved.status_code == 200
        assert saved.json()["revision"] > revision
        stale = client.put(path, json={**original, "amount": "130.00", "expected_revision": revision})
        assert stale.status_code == 409
        create = client.put(path, json={**original, "expected_revision": None})
        assert create.status_code == 409
        retry = client.put(path, json={**original, "amount": "120.00", "expected_revision": revision})
        assert retry.json() == saved.json()
        result = client.get(path, params={"month": "2026-11", "include_history": True}).json()
        assert result["records"] == [saved.json()]
        assert [row["amount"] for row in result["history"]] == ["120.00", "100.00"]
