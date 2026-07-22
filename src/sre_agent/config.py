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
class Config:
    targets: list[Target]
    default_timeout: int = 10
    default_health_path: str = "/health"
    github: GitHubConfig | None = None

    @classmethod
    def load(cls, path: str | Path) -> "Config":
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

        return cls(
            targets=targets,
            default_timeout=defaults.get("timeout_seconds", 10),
            default_health_path=defaults.get("health_path", "/health"),
            github=github,
        )
