"""Adapter Vercel — status dos deploys do front-end (REST API).

Cada deploy vira um ChangeEvent do tipo DEPLOY: estado ERROR é alertável;
READY é contexto. Deploys em andamento (BUILDING/QUEUED) são ignorados.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from ..config import VercelConfig
from ..models import ChangeEvent, ChangeKind

_API = "https://api.vercel.com"

# Estados terminais do Vercel → sucesso do deploy.
_TERMINAL = {"READY": True, "ERROR": False, "CANCELED": False}


class VercelAdapter:
    def __init__(self, config: VercelConfig, base_url: str = _API) -> None:
        self._config = config
        self._base_url = base_url.rstrip("/")
        self._headers = {"Accept": "application/json"}
        if config.token:
            self._headers["Authorization"] = f"Bearer {config.token}"

    async def fetch_changes(self) -> list[ChangeEvent]:
        async with httpx.AsyncClient(
            base_url=self._base_url, headers=self._headers,
            timeout=15, follow_redirects=True,
        ) as client:
            results = await asyncio.gather(
                *(self._fetch_project(project, client) for project in self._config.projects)
            )
        return [event for batch in results for event in batch]

    async def _fetch_project(
        self, project: str, client: httpx.AsyncClient
    ) -> list[ChangeEvent]:
        params = {"projectId": project, "limit": 10}
        if self._config.team_id:
            params["teamId"] = self._config.team_id
        resp = await client.get("/v6/deployments", params=params)
        resp.raise_for_status()

        events: list[ChangeEvent] = []
        for dep in resp.json().get("deployments", []):
            state = str(dep.get("state") or dep.get("readyState") or "").upper()
            if state not in _TERMINAL:
                continue  # em andamento
            created_ms = dep.get("created") or dep.get("createdAt") or 0
            events.append(
                ChangeEvent(
                    kind=ChangeKind.DEPLOY,
                    repo=dep.get("name", project),
                    title=f"deploy {state.lower()}",
                    author=(dep.get("creator") or {}).get("username", "?"),
                    url=f"https://{dep['url']}" if dep.get("url") else "",
                    timestamp=datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc),
                    ok=_TERMINAL[state],
                    ref="vercel",
                )
            )
        return events
