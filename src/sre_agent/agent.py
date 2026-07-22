"""Orquestra os checks de saúde de todos os serviços, em paralelo.

Este é o loop do agente na Fase 0: coletar. Nas próximas fases, quando um
serviço aparece DOWN/DEGRADED, o agente encadeia a etapa de RCA (correlacionar
deploys do GitHub/Vercel/Railway + logs/advisors do Supabase).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from .checks.http import check_http
from .config import Config
from .models import HealthReport


async def run_checks(config: Config) -> HealthReport:
    started = datetime.now(timezone.utc)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        results = await asyncio.gather(
            *(check_http(t, config, client) for t in config.targets)
        )
    finished = datetime.now(timezone.utc)

    results = sorted(results, key=lambda s: s.status.severity)
    return HealthReport(services=list(results), started_at=started, finished_at=finished)
