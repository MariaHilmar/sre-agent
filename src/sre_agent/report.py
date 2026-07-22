"""Renderiza o relatório no terminal e gera um resumo textual.

`summarize()` é intencionalmente baseado em regras nesta fase — não se coloca
um LLM onde um template resolve. Ele é o ponto de extensão da Fase 1: ali o
resumo passa a incluir causa raiz assistida por LLM (RCA).
"""

from __future__ import annotations

import sys
from functools import lru_cache

from rich.console import Console
from rich.table import Table

from .models import (
    Advisory,
    AdvisoryLevel,
    ChangeEvent,
    ChangeKind,
    HealthReport,
    HealthStatus,
)

_console = Console()

_COLOR = {
    HealthStatus.HEALTHY: "green",
    HealthStatus.DEGRADED: "yellow",
    HealthStatus.DOWN: "red",
    HealthStatus.UNKNOWN: "white",
}

# Fallback ASCII para terminais que não codificam emoji (ex.: console legado
# Windows em cp1252). Mantém o agente utilizável em qualquer ambiente.
_ASCII_MARK = {
    HealthStatus.HEALTHY: "[ OK ]",
    HealthStatus.DEGRADED: "[WARN]",
    HealthStatus.DOWN: "[DOWN]",
    HealthStatus.UNKNOWN: "[ ?? ]",
}


@lru_cache(maxsize=1)
def _emoji_ok() -> bool:
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "🔴".encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _icon(status: HealthStatus) -> str:
    return status.emoji if _emoji_ok() else _ASCII_MARK[status]


def _marker(status: HealthStatus) -> str:
    return f"{_icon(status)} {status.value}"


def render_table(report: HealthReport) -> None:
    table = Table(title="sre-agent · saúde dos serviços")
    table.add_column("Estado")
    table.add_column("Serviço", style="bold")
    table.add_column("Plataforma")
    table.add_column("Latência", justify="right")
    table.add_column("Detalhe")

    for s in report.services:
        latency = f"{s.latency_ms} ms" if s.latency_ms is not None else "—"
        table.add_row(
            _marker(s.status),
            s.name,
            s.platform,
            latency,
            s.detail,
        )
    _console.print(table)


def summarize(report: HealthReport) -> str:
    total = len(report.services)
    healthy = report.count(HealthStatus.HEALTHY)
    down = [s for s in report.services if s.status is HealthStatus.DOWN]
    degraded = [s for s in report.services if s.status is HealthStatus.DEGRADED]

    lines = [f"{healthy}/{total} serviços saudáveis (verificados em {report.duration_ms} ms)."]
    if down:
        lines.append("FORA DO AR: " + ", ".join(f"{s.name} ({s.detail})" for s in down))
    if degraded:
        lines.append("DEGRADADOS: " + ", ".join(f"{s.name} ({s.detail})" for s in degraded))
    if not down and not degraded:
        lines.append("Nenhuma falha detectada.")
    return "\n".join(lines)


def _change_label(event: ChangeEvent) -> str:
    emoji = _emoji_ok()
    if event.kind is ChangeKind.MERGE:
        return "🔀 merge" if emoji else "merge"
    if event.ok:
        return "🚀 deploy" if emoji else "deploy ok"
    return "💥 deploy" if emoji else "deploy FALHOU"


def render_timeline(events: list[ChangeEvent]) -> None:
    table = Table(title="sre-agent · linha do tempo de mudanças")
    table.add_column("Quando")
    table.add_column("Tipo")
    table.add_column("Repo")
    table.add_column("Mudança", style="bold")
    table.add_column("Autor")

    for e in events:
        row_style = "red" if e.is_failed_deploy else None
        table.add_row(
            e.timestamp.strftime("%d/%m %H:%M"),
            _change_label(e),
            e.repo,
            e.title,
            e.author,
            style=row_style,
        )
    _console.print(table)


def summarize_changes(events: list[ChangeEvent]) -> str:
    deploys = [e for e in events if e.kind is ChangeKind.DEPLOY]
    merges = [e for e in events if e.kind is ChangeKind.MERGE]
    failed = [e for e in events if e.is_failed_deploy]

    lines = [f"{len(events)} mudanças: {len(deploys)} deploys, {len(merges)} merges."]
    if failed:
        lines.append(
            "DEPLOYS QUE FALHARAM: "
            + ", ".join(f"{e.repo} ({e.title})" for e in failed)
        )
    else:
        lines.append("Nenhum deploy com falha na janela.")
    return "\n".join(lines)


def print_changes_summary(events: list[ChangeEvent]) -> None:
    failed = [e for e in events if e.is_failed_deploy]
    color = "red" if failed else "green"
    _console.print()
    _console.print(f"[bold {color}]{summarize_changes(events).splitlines()[0]}[/]")
    for line in summarize_changes(events).splitlines()[1:]:
        _console.print(line)


_ADVISORY_COLOR = {
    AdvisoryLevel.ERROR: "red",
    AdvisoryLevel.WARN: "yellow",
    AdvisoryLevel.INFO: "white",
}


def render_advisories(advisories: list[Advisory]) -> None:
    table = Table(title="sre-agent · advisors do banco (Supabase)")
    table.add_column("Nível")
    table.add_column("Categoria")
    table.add_column("Projeto")
    table.add_column("Advisory", style="bold")

    for a in advisories:
        table.add_row(
            f"[{_ADVISORY_COLOR[a.level]}]{a.level.value}[/]",
            a.category,
            a.project,
            a.title,
        )
    _console.print(table)


def summarize_advisories(advisories: list[Advisory]) -> str:
    errors = [a for a in advisories if a.level.is_alertable]
    total = len(advisories)
    lines = [f"{total} advisors ({len(errors)} de nível ERROR)."]
    if errors:
        lines.append(
            "ERROS: " + ", ".join(f"{a.project}/{a.name}" for a in errors)
        )
    else:
        lines.append("Nenhum advisor de nível ERROR.")
    return "\n".join(lines)


def print_advisories_summary(advisories: list[Advisory]) -> None:
    errors = [a for a in advisories if a.level.is_alertable]
    color = "red" if errors else "green"
    summary = summarize_advisories(advisories)
    _console.print()
    _console.print(f"[bold {color}]{summary.splitlines()[0]}[/]")
    for line in summary.splitlines()[1:]:
        _console.print(line)


def print_summary(report: HealthReport) -> None:
    color = _COLOR[report.overall]
    _console.print()
    _console.print(
        f"[bold {color}]{_icon(report.overall)} "
        f"Estado geral: {report.overall.value.upper()}[/]"
    )
    _console.print(summarize(report))
