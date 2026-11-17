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
    import sqlite3
    from contextlib import closing
    from uuid import uuid4

    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
    app = FastAPI()
    app.include_router(router)
    endpoint = "/v1/workspace/folders/05-backend/tasks"
    task = {"id": str(uuid4()), "title": "Review delivery"}
    existing = {"id": str(uuid4()), "title": "Existing task", "completed": True}
    with closing(sqlite3.connect(tmp_path / "workspace.db")) as conn, conn:
        conn.execute(
            "CREATE TABLE project_tasks ("
            "id TEXT PRIMARY KEY, folder TEXT NOT NULL, title TEXT NOT NULL, "
            "completed INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO project_tasks (id, folder, title, completed) "
            "VALUES (?, ?, ?, 1)",
            (existing["id"], "07-releases", existing["title"]),
        )
    with TestClient(app) as client:
        result = client.post(endpoint, json=task)
        assert result.status_code == 200
        assert result.json() == {**task, "completed": False, "station_id": None}
        assert client.post(endpoint, json=task).json() == result.json()
        assert (
            client.post(endpoint, json={**task, "title": "Different"}).status_code
            == 409
        )
        task_path = f"{endpoint}/{task['id']}"
        assert client.patch(
            task_path, json={"station_id": "operations-manager"}
        ).json() == {
            **task,
            "completed": False,
            "station_id": "operations-manager",
        }
        assert client.patch(task_path, json={"completed": True}).json() == {
            **task,
            "completed": True,
            "station_id": "operations-manager",
        }
    with TestClient(app) as client:
        assert client.get(endpoint).json() == [
            {**task, "completed": True, "station_id": "operations-manager"},
        ]
        assert client.get("/v1/workspace/folders/07-releases/tasks").json() == [
            {**existing, "station_id": None},
        ]
        station_tasks = "/v1/workspace/stations/operations-manager/tasks"
        assert client.get(station_tasks).json() == [
            {
                **task,
                "completed": True,
                "station_id": "operations-manager",
                "folder": "05-backend",
            },
        ]
        assert client.get("/v1/workspace/stations/research/tasks").json() == []
        assert client.patch(task_path, json={"station_id": None}).json() == {
            **task,
            "completed": True,
            "station_id": None,
        }
        assert client.get(station_tasks).json() == []
        other_endpoint = "/v1/workspace/folders/06-tests/tasks"
        assert client.get(other_endpoint).json() == []
        assert (
            client.patch(
                f"{other_endpoint}/{task['id']}", json={"completed": False}
            ).status_code
            == 404
        )
