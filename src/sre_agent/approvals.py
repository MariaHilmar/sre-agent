"""Fila de aprovação — human-in-the-loop (Etapa 2.3).

O agente propõe ações (ex.: rollback), que ficam PENDING até um humano aprovar
ou rejeitar. Nada é executado automaticamente: aprovar apenas muda o estado;
a execução em si é uma decisão explícita (e fica para a Fase 3).

Armazenado em SQLite (mesmo arquivo da memória de incidentes), zero deps.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Action, ActionStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    service     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    description TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    decided_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status);
"""


class ActionStore:
    def __init__(self, path: str | Path = "incidents.db") -> None:
        self._path = str(path)
        if self._path != ":memory:":
            parent = Path(self._path).parent
            if parent and not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def propose(self, action: Action) -> Action:
        cur = self._conn.execute(
            "INSERT INTO actions (created_at, service, kind, description, status) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                action.created_at.isoformat(),
                action.service,
                action.kind,
                action.description,
                action.status.value,
            ),
        )
        self._conn.commit()
        action.id = cur.lastrowid
        return action

    def pending(self) -> list[Action]:
        rows = self._conn.execute(
            "SELECT * FROM actions WHERE status = ? ORDER BY created_at",
            (ActionStatus.PENDING.value,),
        ).fetchall()
        return [self._to_action(r) for r in rows]

    def all(self, limit: int = 50) -> list[Action]:
        rows = self._conn.execute(
            "SELECT * FROM actions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._to_action(r) for r in rows]

    def get(self, action_id: int) -> Action | None:
        row = self._conn.execute(
            "SELECT * FROM actions WHERE id = ?", (action_id,)
        ).fetchone()
        return self._to_action(row) if row else None

    def _decide(self, action_id: int, status: ActionStatus) -> Action | None:
        action = self.get(action_id)
        if action is None or action.status is not ActionStatus.PENDING:
            return None
        decided_at = datetime.now(timezone.utc)
        self._conn.execute(
            "UPDATE actions SET status = ?, decided_at = ? WHERE id = ?",
            (status.value, decided_at.isoformat(), action_id),
        )
        self._conn.commit()
        action.status = status
        action.decided_at = decided_at
        return action

    def approve(self, action_id: int) -> Action | None:
        return self._decide(action_id, ActionStatus.APPROVED)

    def reject(self, action_id: int) -> Action | None:
        return self._decide(action_id, ActionStatus.REJECTED)

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _to_action(row: sqlite3.Row) -> Action:
        return Action(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            service=row["service"],
            kind=row["kind"],
            description=row["description"],
            status=ActionStatus(row["status"]),
            decided_at=(
                datetime.fromisoformat(row["decided_at"]) if row["decided_at"] else None
            ),
        )
