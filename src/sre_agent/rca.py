"""RCA — análise de causa raiz assistida por LLM (Etapa 1.4).

O loop tem duas partes, deliberadamente separadas:

  1. gather_evidence() — DETERMINÍSTICO: junta os sinais (serviço com falha,
     linha do tempo de mudanças, advisors do banco, incidentes passados).
  2. diagnose() — RACIOCÍNIO: entrega a evidência a um LLM que propõe a causa
     raiz mais provável. O LLM fica atrás de uma interface (LLMClient), então
     o núcleo não depende de fornecedor e os testes usam um cliente falso.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .config import Config
from .memory import IncidentStore
from .models import (
    Advisory,
    ChangeEvent,
    HealthReport,
    HealthStatus,
    Incident,
    ServiceHealth,
)
from .signals.supabase import SupabaseAdapter
from .signals.timeline import gather_changes, has_change_source


@dataclass
class Evidence:
    """Todo o contexto reunido para diagnosticar um serviço com falha."""

    service: ServiceHealth
    changes: list[ChangeEvent]
    advisories: list[Advisory]
    past_incidents: list[Incident]


@runtime_checkable
class LLMClient(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...


async def gather_evidence(
    config: Config, report: HealthReport, store: IncidentStore | None = None
) -> list[Evidence]:
    """Reúne a evidência para cada serviço DOWN/DEGRADED do relatório."""
    failing = [
        s for s in report.services
        if s.status in (HealthStatus.DOWN, HealthStatus.DEGRADED)
    ]
    if not failing:
        return []

    changes = await gather_changes(config) if has_change_source(config) else []
    advisories = (
        await SupabaseAdapter(config.supabase).fetch_advisories()
        if config.supabase and config.supabase.projects
        else []
    )

    evidences: list[Evidence] = []
    for service in failing:
        past = store.similar(service.name) if store else []
        evidences.append(
            Evidence(
                service=service,
                changes=changes,
                advisories=advisories,
                past_incidents=past,
            )
        )
    return evidences


_SYSTEM = (
    "Você é um engenheiro de SRE sênior fazendo análise de causa raiz (RCA). "
    "Recebe um incidente e o contexto (mudanças recentes, advisors do banco, "
    "incidentes passados). Responda em português, de forma concisa, com: "
    "(1) a causa raiz MAIS PROVÁVEL, citando a evidência que a sustenta; "
    "(2) um próximo passo acionável. Se a evidência for insuficiente, diga o "
    "que falta investigar. Não invente causas sem evidência."
)


def build_prompt(evidence: Evidence) -> tuple[str, str]:
    s = evidence.service
    parts = [
        f"INCIDENTE: serviço '{s.name}' ({s.platform}) está {s.status.value.upper()}.",
        f"Detalhe: {s.detail}" + (f" · HTTP {s.http_status}" if s.http_status else ""),
        "",
        "MUDANÇAS RECENTES (deploys e merges):",
    ]
    if evidence.changes:
        for e in evidence.changes[:15]:
            flag = " [FALHOU]" if e.is_failed_deploy else ""
            parts.append(
                f"  - {e.timestamp:%d/%m %H:%M} · {e.kind.value}{flag} · "
                f"{e.repo}: {e.title} ({e.author})"
            )
    else:
        parts.append("  (nenhuma)")

    parts.append("")
    parts.append("ADVISORS DO BANCO:")
    if evidence.advisories:
        for a in evidence.advisories[:10]:
            parts.append(f"  - [{a.level.value}] {a.category} · {a.project}: {a.title}")
    else:
        parts.append("  (nenhum)")

    parts.append("")
    parts.append("INCIDENTES PASSADOS DESTE SERVIÇO:")
    if evidence.past_incidents:
        for inc in evidence.past_incidents:
            parts.append(
                f"  - {inc.created_at:%d/%m} · {inc.status}: {inc.root_cause or inc.summary}"
            )
    else:
        parts.append("  (nenhum registrado)")

    return _SYSTEM, "\n".join(parts)


def diagnose(evidence: Evidence, llm: LLMClient) -> str:
    system, prompt = build_prompt(evidence)
    return llm.complete(system, prompt).strip()


def evidence_summary(evidence: Evidence) -> str:
    """Resumo determinístico da evidência (para gravar na memória)."""
    failed_deploys = [e for e in evidence.changes if e.is_failed_deploy]
    error_advisories = [a for a in evidence.advisories if a.level.is_alertable]
    bits = [f"{evidence.service.detail}"]
    if failed_deploys:
        bits.append(f"{len(failed_deploys)} deploy(s) com falha")
    if error_advisories:
        bits.append(f"{len(error_advisories)} advisor(es) ERROR")
    return "; ".join(bits)
