"""Profile-scoped, revisioned storage for the Shared Brain brief."""

from __future__ import annotations

import sqlite3
from contextlib import closing

from openjarvis.core.paths import get_config_dir
from openjarvis.security.file_utils import secure_create

MAX_BRIEF_LENGTH = 4000


class SharedBriefConflict(ValueError):
    """A different client has updated the brief since the caller read it."""


def _connect() -> sqlite3.Connection:
    path = secure_create(get_config_dir() / "shared_brain.db")
    return sqlite3.connect(path)


def _initialize(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS shared_brief ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), "
        "context TEXT NOT NULL, revision INTEGER NOT NULL)"
    )


def load_brief() -> tuple[str, int]:
    with closing(_connect()) as conn:
        _initialize(conn)
        row = conn.execute(
            "SELECT context, revision FROM shared_brief WHERE id = 1"
        ).fetchone()
    if row is None:
        return "", 0
    return row[0], row[1]


def update_brief(context: str, revision: int) -> int:
    with closing(_connect()) as conn, conn:
        _initialize(conn)
        conn.execute(
            "INSERT OR IGNORE INTO shared_brief (id, context, revision) "
            "VALUES (1, '', 0)"
        )
        result = conn.execute(
            "UPDATE shared_brief SET context = ?, revision = revision + 1 "
            "WHERE id = 1 AND revision = ?",
            (context, revision),
        )
        if not result.rowcount:
            raise SharedBriefConflict("The Shared Brain brief has changed.")
    return revision + 1


def append_workflow_handoff(run_id: str, summary: str) -> bool:
    """Append one published summary per run while preserving the current brief."""
    context, revision = load_brief()
    heading = f"[Approved workflow {run_id}]"
    if heading in context.splitlines():
        return False
    entry = f"{heading}\n{summary}"
    next_context = "\n\n".join(filter(None, (context, entry)))
    if len(next_context) > MAX_BRIEF_LENGTH:
        raise ValueError("The Shared Brain brief is full. Shorten it before sharing.")
    update_brief(next_context, revision)
    return True
