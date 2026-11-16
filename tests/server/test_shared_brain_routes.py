from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.app import create_app  # noqa: E402


def test_shared_brief_is_authenticated_persistent_and_revisioned(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "openjarvis.server.shared_brain_routes.get_config_dir", lambda: tmp_path
    )
    path = "/v1/shared-brain/brief"
    headers = {"Authorization": "Bearer test-shared-brain-key"}

    def client() -> TestClient:
        return TestClient(
            create_app(MagicMock(), "test", api_key="test-shared-brain-key")
        )

    with client() as original:
        assert original.get(path).status_code == 401
        assert (
            original.put(path, json={"context": "", "revision": 0}).status_code == 401
        )
        assert original.get(path, headers=headers).json() == {
            "context": "",
            "revision": 0,
        }

        def save(text):
            return original.put(
                path, json={"context": text, "revision": 0}, headers=headers
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(save, value) for value in ("First", "Second")]
            results = [future.result() for future in futures]
        assert sorted(response.status_code for response in results) == [200, 409]
        winner = next(
            response.json() for response in results if response.status_code == 200
        )
        assert winner["revision"] == 1

    with client() as restarted:
        assert restarted.get(path, headers=headers).json() == winner
        too_long = restarted.put(
            path, json={"context": "x" * 4001, "revision": 1}, headers=headers
        )
        assert too_long.status_code == 422
        assert restarted.get(path, headers=headers).json() == winner
