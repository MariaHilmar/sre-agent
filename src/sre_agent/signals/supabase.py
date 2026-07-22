"""Adapter Supabase — saúde do banco via advisors (Management API).

Os advisors são os "lints" de segurança e performance que o Supabase expõe
(ex.: RLS desabilitado, índice faltando, pooler saturado). Um advisor de
nível ERROR é ALERTÁVEL; WARN/INFO são contexto para o RCA.

Read-only: usa um Personal Access Token do Supabase. Endpoint alvo é a
Management API (api.supabase.com); ajuste `base_url` se necessário.
"""

from __future__ import annotations

import asyncio

import httpx

from ..config import SupabaseConfig
from ..models import Advisory, AdvisoryLevel

_CATEGORIES = ("security", "performance")

# Mapeia o nível textual do Supabase para o nosso enum.
_LEVEL_MAP = {
    "ERROR": AdvisoryLevel.ERROR,
    "WARN": AdvisoryLevel.WARN,
    "WARNING": AdvisoryLevel.WARN,
    "INFO": AdvisoryLevel.INFO,
}


class SupabaseAdapter:
    def __init__(self, config: SupabaseConfig) -> None:
        self._config = config
        self._base_url = config.base_url.rstrip("/")
        self._headers = {"Accept": "application/json"}
        if config.access_token:
            self._headers["Authorization"] = f"Bearer {config.access_token}"

    async def fetch_advisories(self) -> list[Advisory]:
        async with httpx.AsyncClient(
            base_url=self._base_url, headers=self._headers,
            timeout=15, follow_redirects=True,
        ) as client:
            results = await asyncio.gather(
                *(
                    self._fetch(project, category, client)
                    for project in self._config.projects
                    for category in _CATEGORIES
                )
            )
        advisories = [a for batch in results for a in batch]
        # Ordena por severidade: ERROR primeiro.
        order = {AdvisoryLevel.ERROR: 0, AdvisoryLevel.WARN: 1, AdvisoryLevel.INFO: 2}
        advisories.sort(key=lambda a: order[a.level])
        return advisories

    async def _fetch(
        self, project: str, category: str, client: httpx.AsyncClient
    ) -> list[Advisory]:
        resp = await client.get(f"/v1/projects/{project}/advisors/{category}")
        resp.raise_for_status()
        lints = resp.json().get("lints", [])
        advisories: list[Advisory] = []
        for lint in lints:
            level = _LEVEL_MAP.get(str(lint.get("level", "")).upper(), AdvisoryLevel.INFO)
            advisories.append(
                Advisory(
                    project=project,
                    level=level,
                    category=category,
                    name=lint.get("name", ""),
                    title=lint.get("title") or lint.get("name", ""),
                    detail=lint.get("detail", ""),
                    url=(lint.get("remediation") or ""),
                )
            )
        return advisories
