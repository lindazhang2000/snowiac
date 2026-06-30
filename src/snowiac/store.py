"""Persistent ticket / spec / event store.

Backends:
* SQLite (default; local dev). Pass ``db_path``.
* PostgreSQL (Azure Database for PostgreSQL). Pass ``database_url`` like
  ``postgresql://user:pass@host:5432/snowiac?sslmode=require``.

Both implementations expose the same API used by ``workflow.py`` and
``server.py``.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from typing import Any, Protocol

from .models import ServiceNowTicket

log = logging.getLogger(__name__)


# ─── Interface ────────────────────────────────────────────────────────────────
class TicketStore(Protocol):
    def put(self, ticket: ServiceNowTicket) -> None: ...
    def get(self, ticket_id: str) -> ServiceNowTicket | None: ...
    def put_spec(self, ticket_id: str, spec: dict[str, Any]) -> None: ...
    def get_spec(self, ticket_id: str) -> dict[str, Any] | None: ...
    def log_event(
        self,
        ticket_id: str,
        stage: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None: ...
    def get_events(self, ticket_id: str) -> list[dict[str, Any]]: ...
    def list_tickets(self) -> list[dict[str, Any]]: ...
    def set_state(self, ticket_id: str, stage: str, status: str) -> None: ...
    def get_state(self, ticket_id: str) -> dict[str, Any] | None: ...
    def mark_run_processed(self, run_id: str, ticket_id: str | None = None) -> bool: ...
    def unmark_run_processed(self, run_id: str) -> None: ...


def _summarise(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        t = json.loads(r["payload"])
        out.append(
            {
                "ticket_id": r["ticket_id"],
                "short_description": t.get("ShortDescription"),
                "catalog": t.get("Catalog"),
                "requested_for": t.get("RequestedFor"),
                "manager": t.get("Manager"),
                "last_stage": r["last_stage"],
                "last_message": r["last_message"],
                "last_event_at": r["last_event_at"] or r["updated"],
            }
        )
    return out


# ─── SQLite ───────────────────────────────────────────────────────────────────
class SQLiteTicketStore:
    """Single-file SQLite store; thread-safe via a process-local lock."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS tickets (
        ticket_id TEXT PRIMARY KEY,
        payload   TEXT NOT NULL,
        updated   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS specs (
        ticket_id TEXT PRIMARY KEY,
        spec      TEXT NOT NULL,
        updated   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS events (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id  TEXT NOT NULL,
        stage      TEXT NOT NULL,
        message    TEXT NOT NULL,
        payload    TEXT,
        created    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS events_ticket_idx ON events(ticket_id, id);
    CREATE TABLE IF NOT EXISTS workflow_state (
        ticket_id TEXT PRIMARY KEY,
        stage     TEXT NOT NULL,
        status    TEXT NOT NULL,
        attempts  INTEGER NOT NULL DEFAULT 0,
        updated   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS processed_runs (
        run_id    TEXT PRIMARY KEY,
        ticket_id TEXT,
        created   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(self._SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def put(self, ticket: ServiceNowTicket) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO tickets(ticket_id, payload) VALUES(?, ?) "
                "ON CONFLICT(ticket_id) DO UPDATE SET "
                "payload=excluded.payload, updated=CURRENT_TIMESTAMP",
                (ticket.RITM, ticket.model_dump_json()),
            )

    def get(self, ticket_id: str) -> ServiceNowTicket | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM tickets WHERE ticket_id = ?", (ticket_id,)
            ).fetchone()
        return ServiceNowTicket.model_validate_json(row["payload"]) if row else None

    def put_spec(self, ticket_id: str, spec: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO specs(ticket_id, spec) VALUES(?, ?) "
                "ON CONFLICT(ticket_id) DO UPDATE SET "
                "spec=excluded.spec, updated=CURRENT_TIMESTAMP",
                (ticket_id, json.dumps(spec)),
            )

    def get_spec(self, ticket_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT spec FROM specs WHERE ticket_id = ?", (ticket_id,)
            ).fetchone()
        return json.loads(row["spec"]) if row else None

    def log_event(
        self,
        ticket_id: str,
        stage: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO events(ticket_id, stage, message, payload) VALUES(?,?,?,?)",
                (ticket_id, stage, message, json.dumps(payload) if payload else None),
            )

    def get_events(self, ticket_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT stage, message, payload, created FROM events "
                "WHERE ticket_id = ? ORDER BY id ASC",
                (ticket_id,),
            ).fetchall()
        return [
            {
                "stage": r["stage"],
                "message": r["message"],
                "payload": json.loads(r["payload"]) if r["payload"] else None,
                "created": r["created"],
            }
            for r in rows
        ]

    def list_tickets(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT t.ticket_id,
                       t.payload,
                       t.updated,
                       (SELECT stage   FROM events e WHERE e.ticket_id=t.ticket_id ORDER BY id DESC LIMIT 1) AS last_stage,
                       (SELECT message FROM events e WHERE e.ticket_id=t.ticket_id ORDER BY id DESC LIMIT 1) AS last_message,
                       (SELECT created FROM events e WHERE e.ticket_id=t.ticket_id ORDER BY id DESC LIMIT 1) AS last_event_at
                FROM tickets t
                ORDER BY COALESCE(
                    (SELECT created FROM events e WHERE e.ticket_id=t.ticket_id ORDER BY id DESC LIMIT 1),
                    t.updated
                ) DESC
                """
            ).fetchall()
        return _summarise([dict(r) for r in rows])

    def set_state(self, ticket_id: str, stage: str, status: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO workflow_state(ticket_id, stage, status, attempts) "
                "VALUES(?,?,?,1) ON CONFLICT(ticket_id) DO UPDATE SET "
                "stage=excluded.stage, status=excluded.status, "
                "attempts=workflow_state.attempts+1, updated=CURRENT_TIMESTAMP",
                (ticket_id, stage, status),
            )

    def get_state(self, ticket_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT stage, status, attempts, updated FROM workflow_state "
                "WHERE ticket_id = ?",
                (ticket_id,),
            ).fetchone()
        return dict(row) if row else None

    def mark_run_processed(self, run_id: str, ticket_id: str | None = None) -> bool:
        """Returns True if this run_id is new (caller should process it),
        False if it was already seen (caller should skip — idempotent)."""
        if not run_id:
            return True  # nothing to dedupe on; treat as new
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO processed_runs(run_id, ticket_id) VALUES(?,?)",
                (run_id, ticket_id),
            )
            return cur.rowcount == 1

    def unmark_run_processed(self, run_id: str) -> None:
        """Release a run_id so a retried delivery can be processed again — used
        when the post-deploy flow failed after marking the run."""
        if not run_id:
            return
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM processed_runs WHERE run_id = ?", (run_id,))


# ─── PostgreSQL ───────────────────────────────────────────────────────────────
class PostgresTicketStore:
    """psycopg[binary] v3 backed store. Uses a connection pool."""

    _SCHEMA = [
        """
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id TEXT PRIMARY KEY,
            payload   TEXT NOT NULL,
            updated   TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS specs (
            ticket_id TEXT PRIMARY KEY,
            spec      TEXT NOT NULL,
            updated   TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS events (
            id         BIGSERIAL PRIMARY KEY,
            ticket_id  TEXT NOT NULL,
            stage      TEXT NOT NULL,
            message    TEXT NOT NULL,
            payload    TEXT,
            created    TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS events_ticket_idx ON events(ticket_id, id)",
        """
        CREATE TABLE IF NOT EXISTS workflow_state (
            ticket_id TEXT PRIMARY KEY,
            stage     TEXT NOT NULL,
            status    TEXT NOT NULL,
            attempts  INTEGER NOT NULL DEFAULT 0,
            updated   TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS processed_runs (
            run_id    TEXT PRIMARY KEY,
            ticket_id TEXT,
            created   TIMESTAMPTZ DEFAULT NOW()
        )
        """,
    ]

    def __init__(self, database_url: str) -> None:
        # Local imports so SQLite-only deployments don't need psycopg installed.
        import psycopg
        from psycopg_pool import ConnectionPool

        self._psycopg = psycopg
        self._pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=5,
            kwargs={"autocommit": True},
            open=True,
        )
        with self._pool.connection() as conn, conn.cursor() as cur:
            for stmt in self._SCHEMA:
                cur.execute(stmt)
        log.info("Postgres ticket store initialised")

    def _rows(self, cur) -> list[dict[str, Any]]:
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def put(self, ticket: ServiceNowTicket) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tickets(ticket_id, payload) VALUES(%s, %s) "
                "ON CONFLICT(ticket_id) DO UPDATE SET "
                "payload=EXCLUDED.payload, updated=NOW()",
                (ticket.RITM, ticket.model_dump_json()),
            )

    def get(self, ticket_id: str) -> ServiceNowTicket | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT payload FROM tickets WHERE ticket_id = %s", (ticket_id,))
            row = cur.fetchone()
        return ServiceNowTicket.model_validate_json(row[0]) if row else None

    def put_spec(self, ticket_id: str, spec: dict[str, Any]) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO specs(ticket_id, spec) VALUES(%s, %s) "
                "ON CONFLICT(ticket_id) DO UPDATE SET "
                "spec=EXCLUDED.spec, updated=NOW()",
                (ticket_id, json.dumps(spec)),
            )

    def get_spec(self, ticket_id: str) -> dict[str, Any] | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT spec FROM specs WHERE ticket_id = %s", (ticket_id,))
            row = cur.fetchone()
        return json.loads(row[0]) if row else None

    def log_event(
        self,
        ticket_id: str,
        stage: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO events(ticket_id, stage, message, payload) "
                "VALUES(%s, %s, %s, %s)",
                (ticket_id, stage, message, json.dumps(payload) if payload else None),
            )

    def get_events(self, ticket_id: str) -> list[dict[str, Any]]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT stage, message, payload, created FROM events "
                "WHERE ticket_id = %s ORDER BY id ASC",
                (ticket_id,),
            )
            rows = self._rows(cur)
        for r in rows:
            r["payload"] = json.loads(r["payload"]) if r["payload"] else None
            r["created"] = r["created"].isoformat() if r["created"] else None
        return rows

    def list_tickets(self) -> list[dict[str, Any]]:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.ticket_id,
                       t.payload,
                       t.updated,
                       (SELECT stage   FROM events e WHERE e.ticket_id=t.ticket_id ORDER BY id DESC LIMIT 1) AS last_stage,
                       (SELECT message FROM events e WHERE e.ticket_id=t.ticket_id ORDER BY id DESC LIMIT 1) AS last_message,
                       (SELECT created FROM events e WHERE e.ticket_id=t.ticket_id ORDER BY id DESC LIMIT 1) AS last_event_at
                FROM tickets t
                ORDER BY COALESCE(
                    (SELECT created FROM events e WHERE e.ticket_id=t.ticket_id ORDER BY id DESC LIMIT 1),
                    t.updated
                ) DESC
                """
            )
            rows = self._rows(cur)
        for r in rows:
            for k in ("updated", "last_event_at"):
                if r.get(k) is not None:
                    r[k] = r[k].isoformat()
        return _summarise(rows)

    def set_state(self, ticket_id: str, stage: str, status: str) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workflow_state(ticket_id, stage, status, attempts) "
                "VALUES(%s,%s,%s,1) ON CONFLICT(ticket_id) DO UPDATE SET "
                "stage=EXCLUDED.stage, status=EXCLUDED.status, "
                "attempts=workflow_state.attempts+1, updated=NOW()",
                (ticket_id, stage, status),
            )

    def get_state(self, ticket_id: str) -> dict[str, Any] | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT stage, status, attempts, updated FROM workflow_state "
                "WHERE ticket_id = %s",
                (ticket_id,),
            )
            rows = self._rows(cur)
        if not rows:
            return None
        r = rows[0]
        if r.get("updated") is not None:
            r["updated"] = r["updated"].isoformat()
        return r

    def mark_run_processed(self, run_id: str, ticket_id: str | None = None) -> bool:
        """Returns True if this run_id is new (caller should process it),
        False if it was already seen (caller should skip — idempotent)."""
        if not run_id:
            return True
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO processed_runs(run_id, ticket_id) VALUES(%s,%s) "
                "ON CONFLICT(run_id) DO NOTHING",
                (run_id, ticket_id),
            )
            return cur.rowcount == 1

    def unmark_run_processed(self, run_id: str) -> None:
        """Release a run_id so a retried delivery can be processed again — used
        when the post-deploy flow failed after marking the run."""
        if not run_id:
            return
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM processed_runs WHERE run_id = %s", (run_id,))


# ─── Factory ──────────────────────────────────────────────────────────────────
def make_store(database_url: str | None, sqlite_path: str) -> TicketStore:
    if database_url and database_url.startswith(("postgres://", "postgresql://")):
        log.info("Using PostgreSQL ticket store")
        return PostgresTicketStore(database_url)
    log.info("Using SQLite ticket store at %s", sqlite_path)
    return SQLiteTicketStore(sqlite_path)
