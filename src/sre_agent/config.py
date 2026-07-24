"""Carrega o arquivo de configuração e expande variáveis de ambiente.

Segredos NUNCA ficam no YAML versionado: use `${VAR}` e defina em `.env`
(gitignored). O motor é público; a configuração real é privada.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env(value):
    """Substitui ${VAR} pelo valor do ambiente, recursivamente."""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


@dataclass
class Expect:
    """Critério de sucesso de um health check."""

    status: int = 200
    json: dict = field(default_factory=dict)


@dataclass
class Target:
    """Um serviço a ser monitorado."""

    name: str
    url: str
    platform: str = "generic"
    health_path: str | None = None
    timeout_seconds: int | None = None
    expect: Expect = field(default_factory=Expect)


@dataclass
class GitHubConfig:
    """Configuração do adapter GitHub (Fase 1)."""

    token: str = ""
    repos: list[str] = field(default_factory=list)  # ex.: ["owner/repo"]
    lookback_hours: int = 24


@dataclass
class SupabaseConfig:
    """Configuração do adapter Supabase (Fase 1)."""

    access_token: str = ""
    projects: list[str] = field(default_factory=list)  # project refs
    base_url: str = "https://api.supabase.com"


@dataclass
class VercelConfig:
    """Configuração do adapter Vercel (Fase 1)."""

    token: str = ""
    projects: list[str] = field(default_factory=list)  # project ids ou nomes
    team_id: str = ""


@dataclass
class RailwayConfig:
    """Configuração do adapter Railway (Fase 1)."""

    token: str = ""
    services: list[str] = field(default_factory=list)  # service ids
    base_url: str = "https://backboard.railway.com/graphql/v2"


@dataclass
class LLMConfig:
    """Configuração do motor de RCA (Fase 1)."""

    provider: str = "anthropic"
    model: str = "claude-sonnet-5"
    api_key: str = ""  # vazio = SDK lê ANTHROPIC_API_KEY do ambiente


@dataclass
class MemoryConfig:
    """Configuração da memória de incidentes (Fase 1)."""

    path: str = "incidents.db"


@dataclass
class NotifyConfig:
    """Configuração de notificação (Fase 2)."""

    enabled: bool = False
    slack_webhook: str = ""  # via ${SLACK_WEBHOOK_URL}


@dataclass
class Config:
    targets: list[Target]
    default_timeout: int = 10
    default_health_path: str = "/health"
    github: GitHubConfig | None = None
    supabase: SupabaseConfig | None = None
    vercel: VercelConfig | None = None
    railway: RailwayConfig | None = None
    llm: LLMConfig = field(default_factory=LLMConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)

    @classmethod
    def load(cls, path: str | Path) -> Config:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        raw = _expand_env(raw)
        defaults = raw.get("defaults") or {}

        targets: list[Target] = []
        for t in raw.get("targets") or []:
            exp = t.get("expect") or {}
            targets.append(
                Target(
                    name=t["name"],
                    url=str(t["url"]).rstrip("/"),
                    platform=t.get("platform", "generic"),
                    health_path=t.get("health_path"),
                    timeout_seconds=t.get("timeout_seconds"),
                    expect=Expect(status=exp.get("status", 200), json=exp.get("json") or {}),
                )
            )

        github = None
        gh_raw = raw.get("github")
        if gh_raw:
            github = GitHubConfig(
                token=gh_raw.get("token", ""),
                repos=list(gh_raw.get("repos") or []),
                lookback_hours=gh_raw.get("lookback_hours", 24),
            )

        supabase = None
        sb_raw = raw.get("supabase")
        if sb_raw:
            supabase = SupabaseConfig(
                access_token=sb_raw.get("access_token", ""),
                projects=list(sb_raw.get("projects") or []),
                base_url=sb_raw.get("base_url", "https://api.supabase.com"),
            )

        vercel = None
        vc_raw = raw.get("vercel")
        if vc_raw:
            vercel = VercelConfig(
                token=vc_raw.get("token", ""),
                projects=list(vc_raw.get("projects") or []),
                team_id=vc_raw.get("team_id", ""),
            )

        railway = None
        rw_raw = raw.get("railway")
        if rw_raw:
            railway = RailwayConfig(
                token=rw_raw.get("token", ""),
                services=list(rw_raw.get("services") or []),
                base_url=rw_raw.get("base_url", "https://backboard.railway.com/graphql/v2"),
            )

        llm_raw = raw.get("llm") or {}
        llm = LLMConfig(
            provider=llm_raw.get("provider", "anthropic"),
            model=llm_raw.get("model", "claude-sonnet-5"),
            api_key=llm_raw.get("api_key", ""),
        )

        mem_raw = raw.get("memory") or {}
        memory = MemoryConfig(path=mem_raw.get("path", "incidents.db"))

        notify_raw = raw.get("notify") or {}
        notify = NotifyConfig(
            enabled=bool(notify_raw.get("enabled", False)),
            slack_webhook=notify_raw.get("slack_webhook", ""),
        )

        return cls(
            targets=targets,
            default_timeout=defaults.get("timeout_seconds", 10),
            default_health_path=defaults.get("health_path", "/health"),
            github=github,
            supabase=supabase,
            vercel=vercel,
            railway=railway,
            llm=llm,
            memory=memory,
            notify=notify,
        )
