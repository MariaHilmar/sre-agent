"""CLI do sre-agent."""

from __future__ import annotations

import asyncio
import json as _json
from pathlib import Path

import click

from . import __version__
from .agent import run_checks, triage
from .approvals import ActionStore
from .config import Config
from .llm import build_llm
from .memory import IncidentStore
from .models import Action, Incident
from .notify import build_notifier
from .rca import diagnose, evidence_summary, gather_evidence
from .report import (
    print_advisories_summary,
    print_changes_summary,
    print_summary,
    render_actions,
    render_advisories,
    render_table,
    render_timeline,
    render_triage,
    summarize,
    summarize_triage,
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
@click.option("--notify", is_flag=True, help="Notificar (Slack) se houver falha.")
def check(config_path: Path, as_json: bool, notify: bool) -> None:
    """Verifica a saúde de todos os serviços configurados.

    Sai com código 1 se qualquer serviço estiver DOWN ou DEGRADED — pronto
    para usar em CI ou cron.
    """
    config = Config.load(config_path)
    if not config.targets:
        click.echo("Nenhum target configurado em " + str(config_path), err=True)
        raise SystemExit(2)

    report = asyncio.run(run_checks(config))

    if notify and report.has_failures:
        notifier = build_notifier(config.notify)
        if notifier is not None:
            notifier.send(
                f"{report.overall.value.upper()} · saúde dos serviços",
                summarize(report),
            )

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
@click.option(
    "--propose", "propose_kind", default=None, metavar="TIPO",
    help="Propor uma ação (ex.: rollback) na fila de aprovação para cada falha.",
)
def diagnose_cmd(config_path: Path, record: bool, propose_kind: str | None) -> None:
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
    actions = ActionStore(config.memory.path) if propose_kind else None
    try:
        evidences = asyncio.run(gather_evidence(config, report, store))
        try:
            llm = build_llm(config.llm)
        except RuntimeError as exc:
            click.echo(str(exc), err=True)
            raise SystemExit(2) from exc

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
            if actions is not None:
                proposed = actions.propose(
                    Action(service=ev.service.name, kind=propose_kind, description=root_cause)
                )
                click.echo(f"-> ação #{proposed.id} proposta ({propose_kind}); aguarda aprovação")
    finally:
        store.close()
        if actions is not None:
            actions.close()

    raise SystemExit(1)


@main.command("triage")
@_CONFIG_OPTION
@click.option("--json", "as_json", is_flag=True, help="Saída em JSON (para CI/painel).")
@click.option("--notify", is_flag=True, help="Notificar (Slack) se houver falha.")
@click.option(
    "--propose", "propose_kind", default="runbook", show_default=True, metavar="TIPO",
    help="Tipo da ação proposta automaticamente para cada falha.",
)
@click.option("--no-propose", is_flag=True, help="Não propor ações automaticamente.")
@click.option(
    "--record/--no-record", default=True,
    help="Registrar os incidentes diagnosticados na memória (default: sim).",
)
def triage_cmd(
    config_path: Path, as_json: bool, notify: bool,
    propose_kind: str, no_propose: bool, record: bool,
) -> None:
    """Roda o ciclo completo do agente: coleta, RCA e proposta.

    Verifica a saúde; para cada serviço DOWN/DEGRADED, reúne a evidência,
    diagnostica com o LLM, registra o incidente e enfileira uma ação (dedup) para
    aprovação. Nunca executa nada. Sai com código 1 se houver falha — pronto para
    cron. Degrada com elegância sem LLM ou sem fontes de contexto.
    """
    config = Config.load(config_path)
    if not config.targets:
        click.echo("Nenhum target configurado em " + str(config_path), err=True)
        raise SystemExit(2)

    # LLM opcional: sem chave/pacote, o ciclo segue sem RCA (não quebra a CLI).
    try:
        llm = build_llm(config.llm)
    except Exception:  # noqa: BLE001 - degrada graciosamente sem LLM
        llm = None

    kind = None if no_propose else propose_kind
    incidents = IncidentStore(config.memory.path)
    actions = ActionStore(config.memory.path)
    try:
        result = asyncio.run(
            triage(
                config, llm=llm, incidents=incidents, actions=actions,
                propose_kind=kind, record=record,
            )
        )
    finally:
        incidents.close()
        actions.close()

    if notify and result.has_failures:
        notifier = build_notifier(config.notify)
        if notifier is not None:
            notifier.send(
                f"{result.report.overall.value.upper()} · triage",
                summarize_triage(result),
            )

    if as_json:
        payload = {
            "overall": result.report.overall.value,
            "diagnosed": result.diagnosed,
            "notes": result.notes,
            "outcomes": [
                {
                    "service": o.service.name,
                    "status": o.service.status.value,
                    "root_cause": o.root_cause,
                    "action_id": o.action.id if o.action else None,
                    "action_kind": o.action.kind if o.action else None,
                    "action_is_new": o.action_is_new if o.action else None,
                }
                for o in result.outcomes
            ],
        }
        click.echo(_json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        render_triage(result)

    raise SystemExit(1 if result.has_failures else 0)


@main.command("propose")
@_CONFIG_OPTION
@click.option("--service", required=True, help="Serviço alvo.")
@click.option("--kind", required=True, help="Tipo da ação (ex.: rollback, restart).")
@click.option("--description", required=True, help="O que será feito / por quê.")
def propose_cmd(config_path: Path, service: str, kind: str, description: str) -> None:
    """Propõe uma ação na fila de aprovação (fica pendente até decisão humana)."""
    config = Config.load(config_path)
    store = ActionStore(config.memory.path)
    try:
        action = store.propose(Action(service=service, kind=kind, description=description))
        click.echo(f"Ação #{action.id} proposta (pendente).")
    finally:
        store.close()


@main.command("actions")
@_CONFIG_OPTION
@click.option("--all", "show_all", is_flag=True, help="Mostrar todas (não só pendentes).")
def actions_cmd(config_path: Path, show_all: bool) -> None:
    """Lista as ações na fila de aprovação."""
    config = Config.load(config_path)
    store = ActionStore(config.memory.path)
    try:
        render_actions(store.all() if show_all else store.pending())
    finally:
        store.close()


@main.command("approve")
@_CONFIG_OPTION
@click.argument("action_id", type=int)
def approve_cmd(config_path: Path, action_id: int) -> None:
    """Aprova uma ação pendente (não a executa — apenas libera)."""
    _decide(config_path, action_id, approve=True)


@main.command("reject")
@_CONFIG_OPTION
@click.argument("action_id", type=int)
def reject_cmd(config_path: Path, action_id: int) -> None:
    """Rejeita uma ação pendente."""
    _decide(config_path, action_id, approve=False)


def _decide(config_path: Path, action_id: int, approve: bool) -> None:
    config = Config.load(config_path)
    store = ActionStore(config.memory.path)
    try:
        action = store.approve(action_id) if approve else store.reject(action_id)
        if action is None:
            click.echo(f"Ação #{action_id} não encontrada ou já decidida.", err=True)
            raise SystemExit(2)
        click.echo(f"Ação #{action_id} -> {action.status.value}.")
    finally:
        store.close()
