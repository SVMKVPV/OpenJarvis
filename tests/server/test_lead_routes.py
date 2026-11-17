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


def test_reviewed_leads_keep_deduplicated_pairs_from_approved_evidence(
    tmp_path,
    monkeypatch,
):
    import json

    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    runtime = MagicMock()
    runtime.store.get_run.return_value = {
        "status": "succeeded",
        "graph": {
            "nodes": [
                {
                    "id": "lead-review",
                    "config": {"payload": {"candidate_format": "json_v1"}},
                },
            ]
        },
        "steps": [
            {
                "node_id": "lead-source",
                "success": True,
                "output": "Northwind Ref-1 and Fabrikam Ref-2",
                "metadata": {},
            },
            {
                "node_id": "lead-candidates",
                "success": True,
                "output": json.dumps(
                    {
                        "candidates": [
                            {"organization": "Northwind", "source_reference": "Ref-1"},
                            {"organization": "NORTHWIND", "source_reference": "Ref-1"},
                            {"organization": "Fabrikam", "source_reference": "Ref-2"},
                            {"organization": "Unknown", "source_reference": "Ref-3"},
                        ]
                    }
                ),
                "metadata": {},
            },
            {
                "node_id": "lead-review",
                "success": True,
                "output": "",
                "metadata": {"approval_status": "approved"},
            },
        ],
    }
    monkeypatch.setattr(
        "openjarvis.server.lead_routes.get_workflow_runtime", lambda _: runtime
    )
    with TestClient(create_app(MagicMock(), "test")) as client:
        listed = client.get("/v1/leads/reviewed-candidates/test-run")
        assert listed.status_code == 200
        assert listed.json()["candidates"] == [
            {"organization": "Northwind", "source_reference": "Ref-1"},
            {"organization": "Fabrikam", "source_reference": "Ref-2"},
        ]
        fields = {"organization": "Northwind", "workflow_run_id": "test-run"}
        bad = client.post("/v1/leads", json={**fields, "source_reference": "Ref-2"})
        assert bad.status_code == 400
        good = client.post("/v1/leads", json={**fields, "source_reference": "Ref-1"})
        assert good.status_code == 201
