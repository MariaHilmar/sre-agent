"""Modelos de domínio do sre-agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class HealthStatus(str, Enum):
    """Estado de saúde de um serviço, do pior ao melhor."""

    DOWN = "down"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    HEALTHY = "healthy"

    @property
    def emoji(self) -> str:
        return {
            HealthStatus.HEALTHY: "🟢",
            HealthStatus.DEGRADED: "🟡",
            HealthStatus.DOWN: "🔴",
            HealthStatus.UNKNOWN: "⚪",
        }[self]

    @property
    def severity(self) -> int:
        """Ordena falhas primeiro (0 = mais grave)."""
        return {
            HealthStatus.DOWN: 0,
            HealthStatus.DEGRADED: 1,
            HealthStatus.UNKNOWN: 2,
            HealthStatus.HEALTHY: 3,
        }[self]


@dataclass
class ServiceHealth:
    """Resultado da verificação de um único serviço."""

    name: str
    platform: str
    url: str
    status: HealthStatus
    detail: str = ""
    http_status: int | None = None
    latency_ms: int | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class HealthReport:
    """Snapshot da saúde de todos os serviços verificados numa execução."""

    services: list[ServiceHealth]
    started_at: datetime
    finished_at: datetime

    @property
    def duration_ms(self) -> int:
        return int((self.finished_at - self.started_at).total_seconds() * 1000)

    def count(self, status: HealthStatus) -> int:
        return sum(1 for s in self.services if s.status is status)

    @property
    def overall(self) -> HealthStatus:
        if self.count(HealthStatus.DOWN):
            return HealthStatus.DOWN
        if self.count(HealthStatus.DEGRADED):
            return HealthStatus.DEGRADED
        if self.services and all(s.status is HealthStatus.HEALTHY for s in self.services):
            return HealthStatus.HEALTHY
        return HealthStatus.UNKNOWN

    @property
    def has_failures(self) -> bool:
        return self.overall in (HealthStatus.DOWN, HealthStatus.DEGRADED)


class ChangeKind(str, Enum):
    """Tipo de evento na linha do tempo de mudanças."""

    DEPLOY = "deploy"  # run do Actions — pode ser ALERTÁVEL (se falhou)
    MERGE = "merge"    # PR mergeado — CONTEXTO para o RCA


@dataclass
class ChangeEvent:
    """Um evento de mudança no sistema (deploy, merge). O "o que mudou" do RCA."""

    kind: ChangeKind
    repo: str
    title: str
    author: str
    url: str
    timestamp: datetime
    ok: bool | None = None  # deploy: sucesso? | merge: None (não se aplica)
    ref: str = ""           # branch ou base do PR

    @property
    def is_failed_deploy(self) -> bool:
        """Único caso alertável: um deploy que falhou."""
        return self.kind is ChangeKind.DEPLOY and self.ok is False


class AdvisoryLevel(str, Enum):
    """Severidade de um advisory (lint) do Supabase."""

    ERROR = "error"
    WARN = "warn"
    INFO = "info"

    @property
    def is_alertable(self) -> bool:
        return self is AdvisoryLevel.ERROR


@dataclass
class Advisory:
    """Um alerta de saúde do banco (segurança ou performance) do Supabase."""

    project: str
    level: AdvisoryLevel
    category: str  # "security" | "performance"
    name: str
    title: str
    detail: str = ""
    url: str = ""


@dataclass
class Incident:
    """Um incidente registrado na memória do agente (base do RCA histórico)."""

    service: str
    status: str        # "down" | "degraded"
    summary: str       # evidência resumida no momento do incidente
    root_cause: str = ""  # hipótese de causa raiz (do RCA)
    resolved: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: int | None = None


@dataclass
class TriageOutcome:
    """Resultado do triage para um único serviço com falha (Fase 3.1)."""

    service: ServiceHealth
    root_cause: str = ""          # vazio quando o RCA não rodou (sem LLM)
    action: Action | None = None  # ação enfileirada (ou reaproveitada por dedup)
    action_is_new: bool = True    # False = reaproveitou ação pendente existente


class ActionStatus(str, Enum):
    """Estado de uma ação proposta na fila de aprovação (human-in-the-loop)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class Action:
    """Uma ação proposta pelo agente, que aguarda decisão humana.

    O agente NUNCA executa sozinho: propõe, e um humano aprova ou rejeita.
    """

    service: str
    kind: str          # ex.: "rollback", "restart", "runbook"
    description: str   # o que será feito / por quê
    status: ActionStatus = ActionStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    decided_at: datetime | None = None
    id: int | None = None


@dataclass
class TriageResult:
    """Resultado de um ciclo completo do agente (Fase 3.1).

    O orquestrador `triage` compõe coleta → RCA → proposta num só resultado
    estruturado — a base do painel (3.4) e da saída `--json`.
    """

    report: HealthReport
    outcomes: list[TriageOutcome] = field(default_factory=list)
    diagnosed: bool = False       # houve RCA por LLM? (False = tudo ok ou sem LLM)
    notes: list[str] = field(default_factory=list)  # avisos (ex.: fonte ausente)

    @property
    def has_failures(self) -> bool:
        return self.report.has_failures
