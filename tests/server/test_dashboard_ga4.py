import json

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.connectors import ga4_report
from openjarvis.server.dashboard import dashboard_router


def test_ga4_dashboard_reads_views_only_after_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    monkeypatch.delenv("OPENJARVIS_GA4_PROPERTY_ID", raising=False)
    app = FastAPI()
    app.include_router(dashboard_router)
    route = "/v1/dashboard/ga4-views"
    calls = []

    def report(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "metricHeaders": [{"name": "screenPageViews"}],
                "rows": [{"metricValues": [{"value": "319"}]}],
            },
        )

    monkeypatch.setattr(ga4_report.httpx, "post", report)
    with TestClient(app) as client:
        assert client.get(route).json() == {"status": "unconfigured", "views": None}
        monkeypatch.setenv("OPENJARVIS_GA4_PROPERTY_ID", "https://example.test")
        assert client.get(route).json()["status"] == "invalid_property"
        monkeypatch.setenv("OPENJARVIS_GA4_PROPERTY_ID", "123456789")
        assert client.get(route).json()["status"] == "authorization_required"
        assert not calls
        credentials = tmp_path / "connectors" / "ga4.json"
        credentials.parent.mkdir()
        credentials.write_text(json.dumps({"access_token": "fixture-token"}))
        response = client.get(route)
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json() == {"status": "live", "views": 319}
    url, options = calls[0]
    assert url == (
        "https://analyticsdata.googleapis.com/v1beta/properties/123456789:runReport"
    )
    assert options["json"] == {
        "metrics": [{"name": "screenPageViews"}],
        "dateRanges": [{"startDate": "28daysAgo", "endDate": "yesterday"}],
    }

def test_ga4_property_persists_without_overriding_backend_environment(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    monkeypatch.delenv("OPENJARVIS_GA4_PROPERTY_ID", raising=False)
    app = FastAPI()
    app.include_router(dashboard_router)
    path = "/v1/dashboard/ga4-settings"
    with TestClient(app) as client:
        assert client.put(path, json={"property_id": "non-numeric"}).status_code == 400
        assert client.put(path, json={"property_id": "123"}).json() == {
            "property_id": "123",
            "environment_override": False,
        }
        assert client.get(path).json()["property_id"] == "123"
        assert client.get("/v1/dashboard/ga4-views").json() == {
            "status": "authorization_required",
            "views": None,
        }
        monkeypatch.setenv("OPENJARVIS_GA4_PROPERTY_ID", "456")
        assert client.get(path).json()["environment_override"] is True
        assert client.put(path, json={"property_id": "789"}).status_code == 400
        assert client.get(path).json()["property_id"] == "456"
        monkeypatch.delenv("OPENJARVIS_GA4_PROPERTY_ID")
        assert client.get(path).json()["property_id"] == "123"
        assert client.put(path, json={"property_id": ""}).json()["property_id"] == ""
