"""Memória de incidentes — armazenamento local em SQLite (stdlib, zero deps).

Guarda o histórico de incidentes e suas causas raiz. Serve de contexto para o
RCA: ao diagnosticar, o agente recupera incidentes passados do mesmo serviço.

SQLite é o default por ser zero-config e rodar em qualquer máquina. Trocar por
Supabase/Postgres depois é substituir esta classe, sem mexer no resto.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from .models import Incident

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT    NOT NULL,
    service    TEXT    NOT NULL,
    status     TEXT    NOT NULL,
    summary    TEXT    NOT NULL,
    root_cause TEXT    NOT NULL DEFAULT '',
    resolved   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_incidents_service ON incidents(service);
"""


class IncidentStore:
    def __init__(self, path: str | Path = "incidents.db") -> None:
        self._path = str(path)
        if self._path != ":memory:":
            parent = Path(self._path).parent
            if parent and not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def record(self, incident: Incident) -> Incident:
        cur = self._conn.execute(
            "INSERT INTO incidents "
            "(created_at, service, status, summary, root_cause, resolved) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                incident.created_at.isoformat(),
                incident.service,
                incident.status,
                incident.summary,
                incident.root_cause,
                int(incident.resolved),
            ),
        )
        self._conn.commit()
        incident.id = cur.lastrowid
        return incident

    def recent(self, limit: int = 10) -> list[Incident]:
        rows = self._conn.execute(
            "SELECT * FROM incidents ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._to_incident(r) for r in rows]

    def similar(self, service: str, limit: int = 5) -> list[Incident]:
        """Incidentes passados do mesmo serviço — contexto para o RCA."""
        rows = self._conn.execute(
            "SELECT * FROM incidents WHERE service = ? ORDER BY created_at DESC LIMIT ?",
            (service, limit),
        ).fetchall()
        return [self._to_incident(r) for r in rows]

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _to_incident(row: sqlite3.Row) -> Incident:
        return Incident(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            service=row["service"],
            status=row["status"],
            summary=row["summary"],
            root_cause=row["root_cause"],
            resolved=bool(row["resolved"]),
        )
