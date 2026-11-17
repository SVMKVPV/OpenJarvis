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


def test_project_task_status_persists_and_retries_keep_one_task(tmp_path, monkeypatch):
    from uuid import uuid4

    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    endpoint = "/v1/workspace/folders/05-backend/tasks"
    task = {"id": str(uuid4()), "title": "Review delivery"}
    with TestClient(app) as client:
        result = client.post(endpoint, json=task)
        assert result.status_code == 200
        assert result.json() == {**task, "completed": False}
        assert client.post(endpoint, json=task).json() == result.json()
        assert (
            client.post(endpoint, json={**task, "title": "Different"}).status_code
            == 409
        )
        task_path = f"{endpoint}/{task['id']}"
        assert client.patch(task_path, json={"completed": True}).json() == {
            **task,
            "completed": True,
        }
    with TestClient(app) as client:
        assert client.get(endpoint).json() == [{**task, "completed": True}]
        other_endpoint = "/v1/workspace/folders/06-tests/tasks"
        assert client.get(other_endpoint).json() == []
        assert (
            client.patch(
                f"{other_endpoint}/{task['id']}", json={"completed": False}
            ).status_code
            == 404
        )
