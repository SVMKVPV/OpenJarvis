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
                CREATE TABLE IF NOT EXISTS workflow_recurrences (
                    id TEXT PRIMARY KEY,
                    definition_id TEXT NOT NULL REFERENCES workflow_definitions(id),
                    initial_input TEXT NOT NULL,
                    next_due_at REAL NOT NULL,
                    interval_seconds INTEGER NOT NULL,
                    skipped_while_active INTEGER NOT NULL DEFAULT 0,
                    paused INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_workflow_recurrences_due
                    ON workflow_recurrences(next_due_at);
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
            columns = {row["name"] for row in self._conn.execute(
                "PRAGMA table_info(workflow_runs)"
            )}
            if "scheduled_at" not in columns:
                self._conn.execute(
                    "ALTER TABLE workflow_runs ADD COLUMN scheduled_at REAL"
                )
            if "recurrence_id" not in columns:
                self._conn.execute(
                    "ALTER TABLE workflow_runs ADD COLUMN recurrence_id TEXT"
                )
            recurrence_columns = {row["name"] for row in self._conn.execute(
                "PRAGMA table_info(workflow_recurrences)"
            )}
            if "skipped_while_active" not in recurrence_columns:
                self._conn.execute(
                    "ALTER TABLE workflow_recurrences ADD COLUMN "
                    "skipped_while_active INTEGER NOT NULL DEFAULT 0"
                )
            if "paused" not in recurrence_columns:
                self._conn.execute(
                    "ALTER TABLE workflow_recurrences ADD COLUMN "
                    "paused INTEGER NOT NULL DEFAULT 0"
                )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_workflow_runs_recurrence "
                "ON workflow_runs(recurrence_id, status) "
                "WHERE recurrence_id IS NOT NULL"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_workflow_runs_due "
                "ON workflow_runs(status, scheduled_at)"
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
        scheduled_at: float | None = None,
    ) -> tuple[dict[str, Any], bool]:
        run_id = uuid.uuid4().hex
        now = time.time()
        with self._lock, self._conn:
            if launch is not None:
                launch_inputs = [initial_input, dict(context)]
                if scheduled_at is not None:
                    launch_inputs.append(scheduled_at)
                input_data = json.dumps(launch_inputs, sort_keys=True)
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
                "context_json, parent_run_id, created_at, scheduled_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    workflow_name,
                    "scheduled" if scheduled_at is not None else "queued",
                    json.dumps(graph),
                    initial_input,
                    json.dumps(dict(context)),
                    parent_run_id,
                    now,
                    scheduled_at,
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

    def save_recurrence(
        self, definition_id: str, initial_input: str,
        next_due_at: float, interval_seconds: int,
    ) -> dict[str, Any]:
        recurrence = {
            "id": uuid.uuid4().hex,
            "definition_id": definition_id,
            "initial_input": initial_input,
            "next_due_at": next_due_at,
            "interval_seconds": interval_seconds,
            "skipped_while_active": 0,
            "paused": False,
        }
        with self._lock, self._conn:
            if self.get_definition(definition_id) is None:
                raise KeyError(definition_id)
            self._conn.execute(
                "INSERT INTO workflow_recurrences "
                "(id, definition_id, initial_input, next_due_at, interval_seconds) "
                "VALUES (:id, :definition_id, :initial_input, :next_due_at, "
                ":interval_seconds)",
                recurrence,
            )
        return recurrence

    def list_recurrences(self, definition_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM workflow_recurrences WHERE definition_id = ? "
                "ORDER BY next_due_at, id",
                (definition_id,),
            ).fetchall()
        return [dict(row) | {"paused": bool(row["paused"])} for row in rows]

    def upcoming_recurrences(self, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT recurrence.id, recurrence.definition_id, "
                "recurrence.next_due_at, "
                "recurrence.interval_seconds, "
                "COALESCE(json_extract(definition.graph_json, '$.name'), 'workflow') "
                "AS workflow_name "
                "FROM workflow_recurrences AS recurrence "
                "JOIN workflow_definitions AS definition "
                "ON definition.id = recurrence.definition_id "
                "WHERE recurrence.paused = 0 "
                "ORDER BY recurrence.next_due_at, recurrence.id "
                "LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_recurrence_paused(
        self, definition_id: str, recurrence_id: str, *, paused: bool, now: float
    ) -> dict[str, Any] | None:
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            row = self._conn.execute(
                "SELECT * FROM workflow_recurrences WHERE definition_id = ? AND id = ?",
                (definition_id, recurrence_id),
            ).fetchone()
            if row is None:
                return None
            next_due = row["next_due_at"]
            if row["paused"] and not paused and next_due <= now:
                interval = row["interval_seconds"]
                next_due += (int((now - next_due) // interval) + 1) * interval
            self._conn.execute(
                "UPDATE workflow_recurrences SET paused = ?, next_due_at = ? "
                "WHERE definition_id = ? AND id = ?",
                (paused, next_due, definition_id, recurrence_id),
            )
        return dict(row) | {"paused": paused, "next_due_at": next_due}

    def delete_recurrence(self, definition_id: str, recurrence_id: str) -> bool:
        with self._lock, self._conn:
            result = self._conn.execute(
                "DELETE FROM workflow_recurrences WHERE definition_id = ? AND id = ?",
                (definition_id, recurrence_id),
            )
        return bool(result.rowcount)

    def enqueue_due_recurrences(self, now: float, limit: int = 20) -> None:
        with self._lock, self._conn:
            if self._conn.execute(
                "SELECT 1 FROM workflow_recurrences "
                "WHERE paused = 0 AND next_due_at <= ? LIMIT 1",
                (now,),
            ).fetchone() is None:
                return
            self._conn.execute("BEGIN IMMEDIATE")
            rows = self._conn.execute(
                "SELECT recurrence.*, definition.graph_json, EXISTS ("
                "SELECT 1 FROM workflow_runs WHERE recurrence_id = recurrence.id "
                "AND status IN ('scheduled', 'queued', 'running', 'waiting_approval')"
                ") AS has_active_run "
                "FROM workflow_recurrences AS recurrence JOIN workflow_definitions "
                "AS definition ON definition.id = recurrence.definition_id "
                "WHERE recurrence.paused = 0 AND next_due_at <= ? "
                "ORDER BY next_due_at, recurrence.id LIMIT ?",
                (now, limit),
            ).fetchall()
            for row in rows:
                interval = row["interval_seconds"]
                elapsed_intervals = int((now - row["next_due_at"]) // interval)
                due_at = row["next_due_at"] + elapsed_intervals * interval
                self._conn.execute(
                    "UPDATE workflow_recurrences SET next_due_at = ?, "
                    "skipped_while_active = skipped_while_active + ? WHERE id = ?",
                    (due_at + interval, row["has_active_run"], row["id"]),
                )
                if row["has_active_run"]:
                    continue
                graph = json.loads(row["graph_json"])
                self._conn.execute(
                    "INSERT INTO workflow_runs (id, workflow_name, status, graph_json, "
                    "initial_input, context_json, created_at, scheduled_at, "
                    "recurrence_id) "
                    "VALUES (?, ?, 'scheduled', ?, ?, '{}', ?, ?, ?)",
                    (
                        uuid.uuid4().hex, str(graph.get("name", "workflow")),
                        row["graph_json"], row["initial_input"], now, due_at, row["id"],
                    ),
                )

    def due_runs(self, now: float, limit: int = 20) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM workflow_runs "
                "WHERE status = 'scheduled' AND scheduled_at <= ? "
                "ORDER BY scheduled_at, created_at LIMIT ?",
                (now, limit),
            ).fetchall()
        return [row["id"] for row in rows]

    def claim_scheduled_run(self, run_id: str, now: float) -> bool:
        with self._lock, self._conn:
            result = self._conn.execute(
                "UPDATE workflow_runs SET status = 'queued' "
                "WHERE id = ? AND status = 'scheduled' AND scheduled_at <= ?",
                (run_id, now),
            )
        return bool(result.rowcount)

    def reschedule_run(
        self, run_id: str, scheduled_at: float, expected_scheduled_at: float
    ) -> bool:
        with self._lock, self._conn:
            result = self._conn.execute(
                "UPDATE workflow_runs SET scheduled_at = ? "
                "WHERE id = ? AND status = 'scheduled' AND scheduled_at = ?",
                (scheduled_at, run_id, expected_scheduled_at),
            )
        return bool(result.rowcount)

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
                "UPDATE workflow_runs SET cancel_requested = 1, "
                "finished_at = CASE WHEN status = 'scheduled' THEN ? "
                "ELSE finished_at END, "
                "status = CASE WHEN status = 'scheduled' THEN 'cancelled' "
                "ELSE status END "
                "WHERE id = ? AND status IN "
                "('scheduled', 'queued', 'running', 'waiting_approval')",
                (time.time(), run_id),
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

    def list_runs(
        self,
        *,
        status: str = "",
        limit: int = 50,
        before: str = "",
        recent: bool = False,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        filters: list[str] = []
        params: list[Any] = []
        if status:
            filters.append("status = ?")
            params.append(status)
        if before:
            filters.append(
                "(created_at, id) < "
                "(SELECT created_at, id FROM workflow_runs WHERE id = ?)"
            )
            params.append(before)
        query = "SELECT * FROM workflow_runs"
        if filters:
            query += " WHERE " + " AND ".join(filters)
        if status == "scheduled" and not recent:
            query += " ORDER BY scheduled_at, created_at, id LIMIT ?"
        else:
            query += " ORDER BY created_at DESC, id DESC LIMIT ?"
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
            "scheduled_at": row["scheduled_at"],
            "recurrence_id": row["recurrence_id"],
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
