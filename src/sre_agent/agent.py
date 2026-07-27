"""Orquestra o ciclo do agente.

`run_checks` é o loop da Fase 0: coletar a saúde de todos os serviços em paralelo.

`triage` é o orquestrador da Fase 3.1: encadeia coleta → RCA → proposta num só
ciclo. Compõe as peças já existentes (checks, evidência, diagnóstico, memória,
fila de aprovação) — não reescreve nenhuma. Preserva o human-in-the-loop: propõe
ações, nunca as executa. Degrada com elegância quando falta LLM ou fontes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from .approvals import ActionStore
from .checks.http import check_http
from .config import Config
from .memory import IncidentStore
from .models import Action, HealthReport, Incident, TriageOutcome, TriageResult
from .rca import LLMClient, diagnose, evidence_summary, gather_evidence
from .signals.timeline import has_change_source


async def run_checks(config: Config) -> HealthReport:
    started = datetime.now(timezone.utc)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        results = await asyncio.gather(
            *(check_http(t, config, client) for t in config.targets)
        )
    finished = datetime.now(timezone.utc)

    results = sorted(results, key=lambda s: s.status.severity)
    return HealthReport(services=list(results), started_at=started, finished_at=finished)


async def triage(
    config: Config,
    *,
    llm: LLMClient | None = None,
    incidents: IncidentStore | None = None,
    actions: ActionStore | None = None,
    propose_kind: str | None = "runbook",
    record: bool = True,
) -> TriageResult:
    """Roda o ciclo completo do agente e devolve um resultado estruturado.

    Coleta a saúde; se algo caiu, reúne a evidência e diagnostica com o LLM,
    registra o incidente na memória e enfileira uma ação (deduplicada) para
    aprovação humana. Sem falhas, retorna cedo — sem tocar LLM nem banco.

    Os stores e o LLM são injetados pelo chamador (a CLI os cria e fecha; os
    testes passam falsos), mantendo `triage` puro e testável.
    """
    report = await run_checks(config)
    result = TriageResult(report=report)
    if not report.has_failures:
        return result

    # Há falha: avisa sobre fontes de contexto ausentes, para não mascarar
    # configuração incompleta (o RCA fica mais pobre sem elas).
    if not has_change_source(config):
        result.notes.append("Nenhuma fonte de mudanças (github/vercel/railway) configurada.")
    if not (config.supabase and config.supabase.projects):
        result.notes.append("Nenhum projeto Supabase configurado — advisors não coletados.")

    evidences = await gather_evidence(config, report, incidents)

    if llm is None:
        result.notes.append("Sem LLM disponível — RCA pulado (defina ANTHROPIC_API_KEY).")
        result.outcomes = [TriageOutcome(service=ev.service) for ev in evidences]
        return result

    result.diagnosed = True
    for ev in evidences:
        root_cause = diagnose(ev, llm)
        if record and incidents is not None:
            incidents.record(
                Incident(
                    service=ev.service.name,
                    status=ev.service.status.value,
                    summary=evidence_summary(ev),
                    root_cause=root_cause,
                )
            )
        action = None
        action_is_new = True
        if propose_kind and actions is not None:
            action, action_is_new = actions.propose_unique(
                Action(service=ev.service.name, kind=propose_kind, description=root_cause)
            )
        result.outcomes.append(
            TriageOutcome(
                service=ev.service,
                root_cause=root_cause,
                action=action,
                action_is_new=action_is_new,
            )
        )
    return result
