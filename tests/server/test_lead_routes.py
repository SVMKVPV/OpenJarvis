from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from openjarvis.server.app import create_app


def test_lead_register_persists_and_counts_distinct_records(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    headers = {"Authorization": "Bearer fixture-lead-key"}

    def session():
        return TestClient(create_app(MagicMock(), "test", api_key="fixture-lead-key"))

    lead = {"organization": "Northwind", "source_reference": "Event referral #42"}
    with session() as client:
        assert client.get("/v1/leads/summary").status_code == 401
        assert client.post("/v1/leads", json=lead).status_code == 401
        result = client.post("/v1/leads", json=lead, headers=headers)
        assert result.status_code == 201
        record = result.json()
        duplicate = client.post(
            "/v1/leads", json={**lead, "organization": " northwind "}, headers=headers
        )
        assert duplicate.status_code == 409

    with session() as restarted:
        listed = restarted.get("/v1/leads", headers=headers)
        assert listed.headers["Cache-Control"] == "no-store"
        assert listed.json() == {"leads": [record]}
        summary = restarted.get("/v1/leads/summary", headers=headers)
        assert summary.json() == {"count": 1}
