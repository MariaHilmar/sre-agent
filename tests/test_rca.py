from datetime import datetime, timezone

from sre_agent.models import (
    Advisory,
    AdvisoryLevel,
    ChangeEvent,
    ChangeKind,
    HealthStatus,
    Incident,
    ServiceHealth,
)
from sre_agent.rca import Evidence, build_prompt, diagnose, evidence_summary


class FakeLLM:
    """Cliente LLM falso: devolve o prompt recebido, para inspeção nos testes."""

    def __init__(self) -> None:
        self.last_system = ""
        self.last_prompt = ""

    def complete(self, system: str, prompt: str) -> str:
        self.last_system = system
        self.last_prompt = prompt
        return "Causa raiz: deploy #142 saturou o pool. Próximo passo: rollback."


def _evidence() -> Evidence:
    return Evidence(
        service=ServiceHealth(
            name="sj-fast-api", platform="railway", url="https://x/health",
            status=HealthStatus.DOWN, detail="HTTP 503", http_status=503,
        ),
        changes=[
            ChangeEvent(
                kind=ChangeKind.MERGE, repo="acme/api", title="#142 refatora pool",
                author="dev", url="", timestamp=datetime.now(timezone.utc),
            ),
            ChangeEvent(
                kind=ChangeKind.DEPLOY, repo="acme/api", title="deploy",
                author="dev", url="", timestamp=datetime.now(timezone.utc), ok=False,
            ),
        ],
        advisories=[
            Advisory(project="p", level=AdvisoryLevel.ERROR, category="performance",
                     name="pool_exhausted", title="pool saturado"),
        ],
        past_incidents=[
            Incident(service="sj-fast-api", status="down", summary="503", root_cause="pool"),
        ],
    )


def test_build_prompt_includes_all_evidence():
    _system, prompt = build_prompt(_evidence())
    assert "sj-fast-api" in prompt
    assert "HTTP 503" in prompt
    assert "#142 refatora pool" in prompt
    assert "[FALHOU]" in prompt          # deploy que falhou destacado
    assert "pool saturado" in prompt     # advisor
    assert "INCIDENTES PASSADOS" in prompt


def test_diagnose_calls_llm_and_returns_text():
    llm = FakeLLM()
    result = diagnose(_evidence(), llm)
    assert "Causa raiz" in result
    assert llm.last_prompt  # o prompt foi montado e passado


def test_evidence_summary_is_deterministic():
    summary = evidence_summary(_evidence())
    assert "HTTP 503" in summary
    assert "1 deploy(s) com falha" in summary
    assert "1 advisor(es) ERROR" in summary
