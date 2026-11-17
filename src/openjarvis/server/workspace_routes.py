"""Save Software Engineering project folder names in the backend profile."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, StringConstraints

from openjarvis.core.paths import get_config_dir
from openjarvis.security.file_utils import secure_create

router = APIRouter(prefix="/v1/workspace", tags=["workspace"])


class ProjectFolder(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")


def _folders(name: str | None = None) -> list[str]:
    path = secure_create(get_config_dir() / "workspace.db")
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS project_folders (name TEXT PRIMARY KEY)"
        )
        if name is not None:
            conn.execute(
                "INSERT OR IGNORE INTO project_folders (name) VALUES (?)", (name,)
            )
        return [
            row[0]
            for row in conn.execute("SELECT name FROM project_folders ORDER BY name")
        ]


@router.get("/folders")
def list_folders(response: Response) -> dict[str, list[str]]:
    response.headers["Cache-Control"] = "no-store"
    return {"folders": _folders()}


@router.post("/folders")
def add_folder(folder: ProjectFolder) -> dict[str, list[str]]:
    return {"folders": _folders(folder.name)}


FolderName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
TaskTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
]


class ProjectTaskInput(BaseModel):
    id: UUID
    title: TaskTitle


StationId = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class ProjectTaskUpdate(BaseModel):
    completed: bool | None = None
    station_id: StationId | None = None


class ProjectTask(ProjectTaskInput):
    completed: bool
    station_id: StationId | None = None


class StationProjectTask(ProjectTask):
    folder: FolderName


def _task_db() -> sqlite3.Connection:
    conn = sqlite3.connect(secure_create(get_config_dir() / "workspace.db"))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS project_tasks ("
            "id TEXT PRIMARY KEY, folder TEXT NOT NULL, title TEXT NOT NULL, "
            "completed INTEGER NOT NULL DEFAULT 0, station_id TEXT)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS project_tasks_folder ON project_tasks(folder)"
        )
        if not _has_station_column(conn):
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                if not _has_station_column(conn):
                    conn.execute("ALTER TABLE project_tasks ADD COLUMN station_id TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS project_tasks_station "
            "ON project_tasks(station_id, completed)"
        )
    except sqlite3.Error:
        conn.close()
        raise
    return conn


def _has_station_column(conn: sqlite3.Connection) -> bool:
    return any(
        row["name"] == "station_id"
        for row in conn.execute("PRAGMA table_info(project_tasks)")
    )


@router.get("/folders/{folder}/tasks")
def list_tasks(folder: FolderName, response: Response) -> list[ProjectTask]:
    response.headers["Cache-Control"] = "no-store"
    with closing(_task_db()) as conn:
        rows = conn.execute(
            "SELECT id, title, completed, station_id FROM project_tasks "
            "WHERE folder = ? ORDER BY completed, rowid DESC",
            (folder,),
        )
        return [ProjectTask(**dict(row)) for row in rows]


@router.post("/folders/{folder}/tasks")
def add_task(folder: FolderName, task: ProjectTaskInput) -> ProjectTask:
    with closing(_task_db()) as conn, conn:
        conn.execute(
            "INSERT INTO project_tasks (id, folder, title) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO NOTHING",
            (str(task.id), folder, task.title),
        )
        row = conn.execute(
            "SELECT folder, id, title, completed, station_id "
            "FROM project_tasks WHERE id = ?",
            (str(task.id),),
        ).fetchone()
        if row["folder"] != folder or row["title"] != task.title:
            raise HTTPException(409, "This task ID is already in use.")
        return ProjectTask(**dict(row))


@router.patch("/folders/{folder}/tasks/{task_id}")
def update_task(
    folder: FolderName, task_id: UUID, changes: ProjectTaskUpdate
) -> ProjectTask:
    with closing(_task_db()) as conn, conn:
        row = conn.execute(
            "UPDATE project_tasks SET completed = COALESCE(?, completed), "
            "station_id = CASE WHEN ? THEN ? ELSE station_id END "
            "WHERE id = ? AND folder = ? RETURNING id, title, completed, station_id",
            (
                changes.completed,
                "station_id" in changes.model_fields_set,
                changes.station_id,
                str(task_id),
                folder,
            ),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Project task was not found.")
        return ProjectTask(**dict(row))


@router.get("/stations/{station_id}/tasks")
def list_station_tasks(
    station_id: StationId,
    response: Response,
) -> list[StationProjectTask]:
    response.headers["Cache-Control"] = "no-store"
    with closing(_task_db()) as conn:
        rows = conn.execute(
            "SELECT id, title, completed, station_id, folder FROM project_tasks "
            "WHERE station_id = ? ORDER BY completed, rowid DESC LIMIT 20",
            (station_id,),
        )
        return [StationProjectTask(**dict(row)) for row in rows]
