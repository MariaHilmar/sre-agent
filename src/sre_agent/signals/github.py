"""Adapter GitHub — a linha do tempo de mudanças ("o que mudou").

Coleta dois sinais, seguindo a divisão alerta/contexto:
  - DEPLOY (runs do Actions): um deploy que falhou é ALERTÁVEL.
  - MERGE (PRs mergeados): CONTEXTO para o RCA — registrado, não alerta.

Read-only: usa um token com escopo de leitura. A Fase 0 não precisa dele;
ele entra aqui para o agente enxergar deploys e merges.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from ..config import GitHubConfig
from ..models import ChangeEvent, ChangeKind

_API = "https://api.github.com"


def _parse_iso(value: str) -> datetime:
    # GitHub devolve "2026-07-22T14:02:00Z"; normaliza para fromisoformat (3.10+).
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GitHubAdapter:
    def __init__(self, config: GitHubConfig, base_url: str = _API) -> None:
        self._config = config
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if config.token:
            self._headers["Authorization"] = f"Bearer {config.token}"

    async def fetch_changes(self) -> list[ChangeEvent]:
        """Linha do tempo de mudanças de todos os repos, mais recente primeiro."""
        since = datetime.now(timezone.utc) - timedelta(hours=self._config.lookback_hours)
        async with httpx.AsyncClient(
            base_url=self._base_url, headers=self._headers,
            timeout=15, follow_redirects=True,
        ) as client:
            per_repo = await asyncio.gather(
                *(self._fetch_repo(repo, since, client) for repo in self._config.repos)
            )
        events = [event for repo_events in per_repo for event in repo_events]
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events

    async def _fetch_repo(
        self, repo: str, since: datetime, client: httpx.AsyncClient
    ) -> list[ChangeEvent]:
        deploys, merges = await asyncio.gather(
            self._fetch_runs(repo, since, client),
            self._fetch_merges(repo, since, client),
        )
        return deploys + merges

    async def _fetch_runs(
        self, repo: str, since: datetime, client: httpx.AsyncClient
    ) -> list[ChangeEvent]:
        resp = await client.get(f"/repos/{repo}/actions/runs", params={"per_page": 30})
        resp.raise_for_status()
        events: list[ChangeEvent] = []
        for run in resp.json().get("workflow_runs", []):
            if run.get("status") != "completed":
                continue  # em andamento — ainda não é um deploy concluído
            ts = _parse_iso(run["created_at"])
            if ts < since:
                continue
            events.append(
                ChangeEvent(
                    kind=ChangeKind.DEPLOY,
                    repo=repo,
                    title=run.get("name") or run.get("display_title") or "workflow",
                    author=(run.get("actor") or {}).get("login", "?"),
                    url=run.get("html_url", ""),
                    timestamp=ts,
                    ok=run.get("conclusion") == "success",
                    ref=run.get("head_branch", ""),
                )
            )
        return events

    async def _fetch_merges(
        self, repo: str, since: datetime, client: httpx.AsyncClient
    ) -> list[ChangeEvent]:
        resp = await client.get(
            f"/repos/{repo}/pulls",
            params={"state": "closed", "sort": "updated", "direction": "desc", "per_page": 30},
        )
        resp.raise_for_status()
        events: list[ChangeEvent] = []
        for pr in resp.json():
            merged_at = pr.get("merged_at")
            if not merged_at:
                continue  # fechado sem merge — não é uma mudança
            ts = _parse_iso(merged_at)
            if ts < since:
                continue
            events.append(
                ChangeEvent(
                    kind=ChangeKind.MERGE,
                    repo=repo,
                    title=f"#{pr['number']} {pr['title']}",
                    author=(pr.get("user") or {}).get("login", "?"),
                    url=pr.get("html_url", ""),
                    timestamp=ts,
                    ref=(pr.get("base") or {}).get("ref", ""),
                )
            )
        return events
