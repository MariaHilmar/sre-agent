"""CLI do sre-agent."""

from __future__ import annotations

import asyncio
import json as _json
from pathlib import Path

import click

from . import __version__
from .agent import run_checks
from .config import Config
from .llm import build_llm
from .memory import IncidentStore
from .models import Incident
from .rca import diagnose, evidence_summary, gather_evidence
from .report import (
    print_advisories_summary,
    print_changes_summary,
    print_summary,
    render_advisories,
    render_table,
    render_timeline,
    summarize,
)
from .signals.supabase import SupabaseAdapter
from .signals.timeline import gather_changes, has_change_source

_CONFIG_OPTION = click.option(
    "--config", "config_path",
    default="config.yaml", show_default=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Caminho do arquivo de configuração.",
)


@click.group()
@click.version_option(__version__)
def main() -> None:
    """Agente de SRE — monitor de saúde contínuo do seu stack."""


@main.command()
@_CONFIG_OPTION
@click.option("--json", "as_json", is_flag=True, help="Saída em JSON (para CI/automação).")
def check(config_path: Path, as_json: bool) -> None:
    """Verifica a saúde de todos os serviços configurados.

    Sai com código 1 se qualquer serviço estiver DOWN ou DEGRADED — pronto
    para usar em CI ou cron.
    """
    config = Config.load(config_path)
    if not config.targets:
        click.echo("Nenhum target configurado em " + str(config_path), err=True)
        raise SystemExit(2)

    report = asyncio.run(run_checks(config))

    if as_json:
        payload = {
            "overall": report.overall.value,
            "duration_ms": report.duration_ms,
            "summary": summarize(report),
            "services": [
                {
                    "name": s.name,
                    "platform": s.platform,
                    "status": s.status.value,
                    "http_status": s.http_status,
                    "latency_ms": s.latency_ms,
                    "detail": s.detail,
                    "url": s.url,
                }
                for s in report.services
            ],
        }
        click.echo(_json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        render_table(report)
        print_summary(report)

    raise SystemExit(1 if report.has_failures else 0)


@main.command()
@_CONFIG_OPTION
def changes(config_path: Path) -> None:
    """Mostra a linha do tempo de mudanças (deploys e merges) via GitHub.

    Sai com código 1 se houver deploy com falha na janela configurada.
    """
    config = Config.load(config_path)
    if not has_change_source(config):
        click.echo(
            "Configure ao menos uma fonte de mudanças (github, vercel ou railway) em "
            + str(config_path),
            err=True,
        )
        raise SystemExit(2)

    events = asyncio.run(gather_changes(config))
    render_timeline(events)
    print_changes_summary(events)

    failed = any(e.is_failed_deploy for e in events)
    raise SystemExit(1 if failed else 0)


@main.command()
@_CONFIG_OPTION
def advisors(config_path: Path) -> None:
    """Mostra os advisors de saúde do banco (Supabase).

    Sai com código 1 se houver advisor de nível ERROR.
    """
    config = Config.load(config_path)
    if not config.supabase or not config.supabase.projects:
        click.echo(
            "Configure a seção 'supabase' (access_token + projects) em " + str(config_path),
            err=True,
        )
        raise SystemExit(2)

    advisories = asyncio.run(SupabaseAdapter(config.supabase).fetch_advisories())
    render_advisories(advisories)
    print_advisories_summary(advisories)

    has_error = any(a.level.is_alertable for a in advisories)
    raise SystemExit(1 if has_error else 0)


@main.command("diagnose")
@_CONFIG_OPTION
@click.option(
    "--record/--no-record", default=True,
    help="Registrar os incidentes diagnosticados na memória (default: sim).",
)
def diagnose_cmd(config_path: Path, record: bool) -> None:
    """Diagnostica a causa raiz dos serviços com falha (RCA assistido por LLM).

    Roda o health check; para cada serviço DOWN/DEGRADED, reúne a evidência
    (mudanças, advisors, incidentes passados) e pede ao LLM a causa raiz.
    """
    config = Config.load(config_path)
    if not config.targets:
        click.echo("Nenhum target configurado em " + str(config_path), err=True)
        raise SystemExit(2)

    report = asyncio.run(run_checks(config))
    if not report.has_failures:
        click.echo("Tudo saudável — nada a diagnosticar.")
        raise SystemExit(0)

    store = IncidentStore(config.memory.path)
    try:
        evidences = asyncio.run(gather_evidence(config, report, store))
        try:
            llm = build_llm(config.llm)
        except RuntimeError as exc:
            click.echo(str(exc), err=True)
            raise SystemExit(2)

        for ev in evidences:
            click.echo(f"\n=== RCA · {ev.service.name} ({ev.service.status.value}) ===")
            root_cause = diagnose(ev, llm)
            click.echo(root_cause)
            if record:
                store.record(
                    Incident(
                        service=ev.service.name,
                        status=ev.service.status.value,
                        summary=evidence_summary(ev),
                        root_cause=root_cause,
                    )
                )
    finally:
        store.close()

    raise SystemExit(1)
