"""Agrega a linha do tempo de mudanças de todas as fontes configuradas.

Junta deploys e merges do GitHub, Vercel e Railway numa única lista ordenada.
Só consulta as fontes que estiverem configuradas.
"""

from __future__ import annotations

import asyncio

from ..config import Config
from ..models import ChangeEvent
from .github import GitHubAdapter
from .railway import RailwayAdapter
from .vercel import VercelAdapter


async def gather_changes(config: Config) -> list[ChangeEvent]:
    tasks = []
    if config.github and config.github.repos:
        tasks.append(GitHubAdapter(config.github).fetch_changes())
    if config.vercel and config.vercel.projects:
        tasks.append(VercelAdapter(config.vercel).fetch_changes())
    if config.railway and config.railway.services:
        tasks.append(RailwayAdapter(config.railway).fetch_changes())

    results = await asyncio.gather(*tasks) if tasks else []
    events = [event for batch in results for event in batch]
    events.sort(key=lambda e: e.timestamp, reverse=True)
    return events


def has_change_source(config: Config) -> bool:
    return bool(
        (config.github and config.github.repos)
        or (config.vercel and config.vercel.projects)
        or (config.railway and config.railway.services)
    )
