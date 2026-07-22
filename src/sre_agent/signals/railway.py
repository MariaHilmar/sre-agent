"""Adapter Railway — status dos deploys do backend (GraphQL API).

Cada deployment vira um ChangeEvent do tipo DEPLOY: FAILED/CRASHED é alertável;
SUCCESS é contexto. Estados intermediários (DEPLOYING/BUILDING) são ignorados.

Nota: a Railway expõe uma API GraphQL. A query abaixo busca os deployments
recentes de um serviço; ajuste os campos se o schema evoluir.
"""

from __future__ import annotations

import asyncio

import httpx

from ..config import RailwayConfig
from ..models import ChangeEvent, ChangeKind

_QUERY = """
query Deployments($serviceId: String!) {
  deployments(first: 5, input: { serviceId: $serviceId }) {
    edges {
      node {
        id
        status
        createdAt
        staticUrl
        service { name }
      }
    }
  }
}
"""

# Estados terminais da Railway → sucesso do deploy.
_TERMINAL = {"SUCCESS": True, "FAILED": False, "CRASHED": False}


def _parse_iso(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class RailwayAdapter:
    def __init__(self, config: RailwayConfig) -> None:
        self._config = config
        self._url = config.base_url
        self._headers = {"Content-Type": "application/json"}
        if config.token:
            self._headers["Authorization"] = f"Bearer {config.token}"

    async def fetch_changes(self) -> list[ChangeEvent]:
        async with httpx.AsyncClient(
            headers=self._headers, timeout=15, follow_redirects=True
        ) as client:
            results = await asyncio.gather(
                *(self._fetch_service(service, client) for service in self._config.services)
            )
        return [event for batch in results for event in batch]

    async def _fetch_service(
        self, service_id: str, client: httpx.AsyncClient
    ) -> list[ChangeEvent]:
        resp = await client.post(
            self._url,
            json={"query": _QUERY, "variables": {"serviceId": service_id}},
        )
        resp.raise_for_status()
        edges = (
            resp.json()
            .get("data", {})
            .get("deployments", {})
            .get("edges", [])
        )

        events: list[ChangeEvent] = []
        for edge in edges:
            node = edge.get("node", {})
            status = str(node.get("status", "")).upper()
            if status not in _TERMINAL:
                continue  # em andamento
            events.append(
                ChangeEvent(
                    kind=ChangeKind.DEPLOY,
                    repo=(node.get("service") or {}).get("name", service_id),
                    title=f"deploy {status.lower()}",
                    author="railway",
                    url=node.get("staticUrl", ""),
                    timestamp=_parse_iso(node["createdAt"]),
                    ok=_TERMINAL[status],
                    ref="railway",
                )
            )
        return events
