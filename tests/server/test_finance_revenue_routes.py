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
