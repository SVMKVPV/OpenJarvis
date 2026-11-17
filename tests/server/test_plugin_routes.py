from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.plugin_routes import router  # noqa: E402


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_plugin_catalog_route_filters_by_kind() -> None:
    response = _client().get("/v1/plugins", params={"kind": "connector"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] > 0
    assert payload["kinds"] == ["connector"]
    assert all(item["kind"] == "connector" for item in payload["plugins"])


def test_plugin_detail_and_not_found() -> None:
    client = _client()

    found = client.get("/v1/plugins/connector/gmail")
    assert found.status_code == 200
    assert found.json()["auth_type"] == "oauth"

    missing = client.get("/v1/plugins/connector/does-not-exist")
    assert missing.status_code == 404


def test_mcp_catalog_reports_configuration_without_credentials(monkeypatch) -> None:
    import json

    from openjarvis.core.config import JarvisConfig

    config = JarvisConfig()
    config.tools.mcp.enabled = False
    config.tools.mcp.servers = json.dumps([{
        "name": "n8n-mcp",
        "url": "https://internal.invalid/mcp",
        "token": "test-secret-token",
    }])
    monkeypatch.setattr("openjarvis.core.config.load_config", lambda: config)
    client = _client()
    response = client.get("/v1/plugins", params={"kind": "mcp"})

    assert response.status_code == 200
    assert "test-secret-token" not in response.text
    assert "internal.invalid" not in response.text
    item, = response.json()["plugins"]
    assert item["name"] == "n8n-mcp"
    assert item["source"] == "configuration"
    assert item["enabled"] is False
    assert client.get("/v1/plugins/mcp/" + item["id"]).json() == item


def test_mcp_discovery_is_explicit_and_returns_tool_names(monkeypatch) -> None:
    from unittest.mock import Mock

    discover = Mock(return_value=([], {"search_nodes": object(), "get_node": object()}))
    monkeypatch.setattr(
        "openjarvis.server.agent_manager_routes._get_mcp_tools", discover
    )
    client = _client()
    assert client.get("/v1/plugins", params={"kind": "mcp"}).status_code == 200
    discover.assert_not_called()

    result = client.post("/v1/plugins/mcp/discover")
    assert result.status_code == 200
    assert result.json() == {
        "tool_count": 2, "tool_names": ["get_node", "search_nodes"],
    }
    discover.assert_called_once()
