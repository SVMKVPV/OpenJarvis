import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
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

def test_ga4_authorization_uses_readonly_scope_and_separate_tokens(
    tmp_path, monkeypatch
):
    module = pytest.importorskip("google_auth_oauthlib.flow")
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    client_file = tmp_path / "desktop-client.json"
    client_file.write_text(json.dumps({"installed": {
        "client_id": "fixture.apps.googleusercontent.com",
        "client_secret": "fixture-admin-secret",
        "token_uri": "https://should-not-be-used.example.test",
    }}), encoding="utf-8")
    local_server = MagicMock(return_value=SimpleNamespace(
        token="fixture-access", refresh_token="fixture-refresh"
    ))
    flow = MagicMock(run_local_server=local_server)
    from_config = MagicMock(return_value=flow)
    monkeypatch.setattr(module.InstalledAppFlow, "from_client_config", from_config)
    from click.testing import CliRunner

    from openjarvis.cli.connect_cmd import connect

    result = CliRunner().invoke(connect, ["--path", str(client_file), "ga4"])
    assert result.exit_code == 0, result.output
    local_server.assert_called_once_with(
        host="127.0.0.1", port=0, timeout_seconds=120, prompt="consent"
    )
    args, options = from_config.call_args
    assert args[0]["installed"]["token_uri"] == "https://oauth2.googleapis.com/token"
    assert options == {
        "scopes": ["https://www.googleapis.com/auth/analytics.readonly"],
        "autogenerate_code_verifier": True,
    }
    saved = tmp_path / "connectors" / "ga4.json"
    tokens = json.loads(saved.read_text(encoding="utf-8"))
    assert tokens["refresh_token"] == "fixture-refresh"
    assert not (saved.parent / "google.json").exists()
    assert "fixture-admin-secret" not in result.output
