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
        "tool_count": 2, "tool_names": ["get_node", "search_nodes"], "servers": [],
    }
    discover.assert_called_once()


def test_mcp_discovery_reports_partial_failure_without_connection_details(
    monkeypatch, tmp_path
) -> None:
    import json
    from unittest.mock import MagicMock

    from openjarvis.core.config import JarvisConfig

    config = JarvisConfig()
    config._config_dir = tmp_path
    config.tools.mcp.enabled = True
    config.tools.mcp.servers = json.dumps([
        {"name": "Unavailable", "command": "unavailable-server"},
        {"name": "Empty", "command": "empty-server"},
        {"name": "Documentation", "command": "docs-server"},
    ])
    monkeypatch.setattr("openjarvis.core.config.load_config", lambda: config)
    unavailable, empty, docs = (MagicMock() for _ in range(3))
    unavailable.initialize.side_effect = RuntimeError("private connection details")
    monkeypatch.setattr("openjarvis.mcp.transport.StdioTransport", MagicMock())
    monkeypatch.setattr(
        "openjarvis.mcp.client.MCPClient",
        MagicMock(side_effect=[unavailable, empty, docs]),
    )
    tool = MagicMock()
    tool.spec.name = "search_nodes"

    def provider(client, *, server_name):
        instance = MagicMock()
        instance.discover.return_value = [tool] if client is docs else []
        return instance

    monkeypatch.setattr("openjarvis.tools.mcp_adapter.MCPToolProvider", provider)
    with _client() as client:
        result = client.post("/v1/plugins/mcp/discover")
        assert result.status_code == 200
        assert result.json() == {
            "tool_count": 1,
            "tool_names": ["search_nodes"],
            "servers": [
                {"name": "Unavailable", "status": "failed", "tool_count": 0},
                {"name": "Empty", "status": "no_tools", "tool_count": 0},
                {"name": "Documentation", "status": "available", "tool_count": 1},
            ],
        }
