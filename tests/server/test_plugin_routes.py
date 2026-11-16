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
