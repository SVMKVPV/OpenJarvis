from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.workspace_routes import router


def test_workspace_folders_survive_a_new_client_and_deduplicate(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))

    def create_client():
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    endpoint = "/v1/workspace/folders"
    with create_client() as client:
        assert client.get(endpoint).json() == {"folders": []}
        assert client.post(endpoint, json={"name": "../escape"}).status_code == 422
        response = client.post(endpoint, json={"name": "client-project"})
        assert response.status_code == 200
        assert response.json() == {"folders": ["client-project"]}

    with create_client() as client:
        assert client.get(endpoint).json() == {"folders": ["client-project"]}
        assert client.post(endpoint, json={"name": "client-project"}).json() == {
            "folders": ["client-project"],
        }
