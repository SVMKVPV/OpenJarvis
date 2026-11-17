"""Save Software Engineering project folder names in the backend profile."""

from __future__ import annotations

import sqlite3
from contextlib import closing

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

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
