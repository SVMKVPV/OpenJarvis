"""Durable SQLite ledger for workflow runs and node attempts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from openjarvis.core.paths import get_config_dir
from openjarvis.workflow.types import WorkflowStepResult

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


class WorkflowDefinitionConflict(ValueError):
    """The saved definition changed after an editor loaded it."""


class WorkflowLaunchConflict(ValueError):
    """The same launch key was used for different workflow inputs."""


class WorkflowRunStore:
    def __init__(self, db_path: str = "") -> None:
        path = Path(db_path) if db_path else get_config_dir() / "workflow_runs.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        self._create_tables()

    def _create_tables(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflow_definitions (
                    id TEXT PRIMARY KEY,
                    graph_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    id TEXT PRIMARY KEY,
                    workflow_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    graph_json TEXT NOT NULL,
                    initial_input TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    final_output TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    parent_run_id TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_workflow_runs_created
                    ON workflow_runs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_workflow_runs_status
                    ON workflow_runs(status);

                CREATE TABLE IF NOT EXISTS workflow_launch_keys (
                    definition_id TEXT NOT NULL,
                    launch_key TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES workflow_runs(id),
                    PRIMARY KEY (definition_id, launch_key)
                );

                CREATE TABLE IF NOT EXISTS workflow_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    output TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES workflow_runs(id)
                );
                CREATE INDEX IF NOT EXISTS idx_workflow_steps_run
                    ON workflow_steps(run_id, id);
                """
            )
            # A process that disappeared cannot still own a running thread.
            self._conn.execute(
                "UPDATE workflow_runs SET status = 'interrupted', "
                "error = 'Runtime stopped before completion' "
                "WHERE status IN ('queued', 'running')"
            )
            self._conn.commit()

    def save_definition(self, graph: Mapping[str, Any]) -> dict[str, Any]:
        definition_id = uuid.uuid4().hex
        created_at = time.time()
        source = json.dumps(dict(graph))
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO workflow_definitions VALUES (?, ?, ?)",
                (definition_id, source, created_at),
            )
        return {
            "id": definition_id,
            "graph": dict(graph),
            "created_at": created_at,
            "revision": hashlib.sha256(source.encode()).hexdigest(),
        }

    def update_definition(
        self,
        definition_id: str,
        graph: Mapping[str, Any],
        *,
        expected_revision: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock, self._conn:
            current = self._conn.execute(
                "SELECT graph_json FROM workflow_definitions WHERE id = ?",
                (definition_id,),
            ).fetchone()
            if current is None:
                return None
            source = current["graph_json"]
            revision = hashlib.sha256(source.encode()).hexdigest()
            if expected_revision is not None and revision != expected_revision:
                raise WorkflowDefinitionConflict("The saved workflow has changed.")
            updated = self._conn.execute(
                "UPDATE workflow_definitions SET graph_json = ? "
                "WHERE id = ? AND graph_json = ?",
                (json.dumps(dict(graph)), definition_id, source),
            )
            if not updated.rowcount:
                raise WorkflowDefinitionConflict("The saved workflow has changed.")
            return self.get_definition(definition_id)

    def get_definition(self, definition_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM workflow_definitions WHERE id = ?", (definition_id,)
            ).fetchone()
        return self._definition(row) if row is not None else None

    def list_definitions(self, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM workflow_definitions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._definition(row) for row in rows]

    @staticmethod
    def _definition(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "graph": json.loads(row["graph_json"]),
            "created_at": row["created_at"],
            "revision": hashlib.sha256(row["graph_json"].encode()).hexdigest(),
        }

    def create_run(
        self,
        *,
        workflow_name: str,
        graph: Mapping[str, Any],
        initial_input: str,
        context: Mapping[str, Any],
        parent_run_id: str | None = None,
    ) -> dict[str, Any]:
        run, _ = self.create_run_once(
            workflow_name=workflow_name,
            graph=graph,
            initial_input=initial_input,
            context=context,
            parent_run_id=parent_run_id,
        )
        return run

    def create_run_once(
        self,
        *,
        workflow_name: str,
        graph: Mapping[str, Any],
        initial_input: str,
        context: Mapping[str, Any],
        parent_run_id: str | None = None,
        launch: tuple[str, str] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        run_id = uuid.uuid4().hex
        now = time.time()
        with self._lock, self._conn:
            if launch is not None:
                input_data = json.dumps([initial_input, dict(context)], sort_keys=True)
                input_hash = hashlib.sha256(input_data.encode()).hexdigest()
                self._conn.execute("BEGIN IMMEDIATE")
                existing = self._conn.execute(
                    "SELECT input_hash, run_id FROM workflow_launch_keys "
                    "WHERE definition_id = ? AND launch_key = ?",
                    launch,
                ).fetchone()
                if existing is not None:
                    if existing["input_hash"] != input_hash:
                        raise WorkflowLaunchConflict(
                            "This launch key was already used with different inputs."
                        )
                    run = self.get_run(existing["run_id"])
                    assert run is not None
                    return run, False

            self._conn.execute(
                "INSERT INTO workflow_runs "
                "(id, workflow_name, status, graph_json, initial_input, "
                "context_json, parent_run_id, created_at) "
                "VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)",
                (
                    run_id,
                    workflow_name,
                    json.dumps(graph),
                    initial_input,
                    json.dumps(dict(context)),
                    parent_run_id,
                    now,
                ),
            )
            if launch is not None:
                self._conn.execute(
                    "INSERT INTO workflow_launch_keys VALUES (?, ?, ?, ?)",
                    (*launch, input_hash, run_id),
                )
        run = self.get_run(run_id)
        assert run is not None
        return run, True

    def mark_running(self, run_id: str) -> None:
        self._update(
            run_id,
            status="running",
            started_at=time.time(),
            finished_at=None,
            error="",
        )

    def pause(self, run_id: str, *, context: Mapping[str, Any]) -> None:
        """Persist resumable state while a run waits for human approval."""
        self._update(
            run_id,
            status="waiting_approval",
            context_json=json.dumps(dict(context)),
            error="",
            finished_at=None,
        )

    def finish(
        self,
        run_id: str,
        *,
        status: str,
        final_output: str = "",
        error: str = "",
    ) -> None:
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"Invalid terminal workflow status: {status}")
        self._update(
            run_id,
            status=status,
            final_output=final_output,
            error=error,
            finished_at=time.time(),
        )

    def add_step(self, run_id: str, step: WorkflowStepResult) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(attempt), 0) FROM workflow_steps "
                "WHERE run_id = ? AND node_id = ?",
                (run_id, step.node_id),
            ).fetchone()
            attempt = int(row[0]) + 1
            self._conn.execute(
                "INSERT INTO workflow_steps "
                "(run_id, node_id, attempt, success, output, duration_seconds, "
                "metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    step.node_id,
                    attempt,
                    int(step.success),
                    step.output,
                    step.duration_seconds,
                    json.dumps(step.metadata),
                    time.time(),
                ),
            )
            self._conn.commit()

    def request_cancel(self, run_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE workflow_runs SET cancel_requested = 1 "
                "WHERE id = ? AND status IN ('queued', 'running', 'waiting_approval')",
                (run_id,),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def is_cancel_requested(self, run_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT cancel_requested FROM workflow_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return bool(row and row[0])

    def get_run(
        self, run_id: str, *, include_graph: bool = False
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM workflow_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            step_rows = self._conn.execute(
                "SELECT * FROM workflow_steps WHERE run_id = ? ORDER BY id", (run_id,)
            ).fetchall()
        return self._serialize_run(row, step_rows, include_graph=include_graph)

    def list_runs(self, *, status: str = "", limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        query = "SELECT * FROM workflow_runs"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._serialize_run(row, [], include_graph=False) for row in rows]

    def _update(self, run_id: str, **values: Any) -> None:
        if not values:
            return
        assignments = ", ".join(f"{column} = ?" for column in values)
        with self._lock:
            self._conn.execute(
                f"UPDATE workflow_runs SET {assignments} WHERE id = ?",
                [*values.values(), run_id],
            )
            self._conn.commit()

    @staticmethod
    def _serialize_run(
        row: sqlite3.Row,
        step_rows: list[sqlite3.Row],
        *,
        include_graph: bool,
    ) -> dict[str, Any]:
        item = {
            "id": row["id"],
            "workflow_name": row["workflow_name"],
            "status": row["status"],
            "initial_input": row["initial_input"],
            "context": json.loads(row["context_json"] or "{}"),
            "final_output": row["final_output"],
            "error": row["error"],
            "parent_run_id": row["parent_run_id"],
            "cancel_requested": bool(row["cancel_requested"]),
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "steps": [
                {
                    "node_id": step["node_id"],
                    "attempt": step["attempt"],
                    "success": bool(step["success"]),
                    "output": step["output"],
                    "duration_seconds": step["duration_seconds"],
                    "metadata": json.loads(step["metadata_json"] or "{}"),
                    "created_at": step["created_at"],
                }
                for step in step_rows
            ],
        }
        if include_graph:
            item["graph"] = json.loads(row["graph_json"])
        return item

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = ["TERMINAL_STATUSES", "WorkflowRunStore"]
