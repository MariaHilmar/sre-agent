import asyncio

import httpx
import respx
from click.testing import CliRunner

from sre_agent.agent import triage
from sre_agent.approvals import ActionStore
from sre_agent.cli import main
from sre_agent.config import Config, Expect, MemoryConfig, Target
from sre_agent.memory import IncidentStore
from sre_agent.models import Action


class FakeLLM:
    """LLM falso — devolve uma causa raiz fixa e conta as chamadas."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system: str, prompt: str) -> str:
        self.calls += 1
        return "Causa raiz: deploy recente saturou o pool. Próximo passo: rollback."


def _config(target_url: str) -> Config:
    return Config(
        targets=[Target(name="api", url=target_url, platform="railway", expect=Expect(status=200))],
        memory=MemoryConfig(path=":memory:"),
    )


def test_triage_all_healthy_skips_llm():
    with respx.mock:
        respx.get("https://ok.test/health").mock(return_value=httpx.Response(200))
        llm = FakeLLM()
        result = asyncio.run(triage(_config("https://ok.test"), llm=llm))
    assert not result.has_failures
    assert result.outcomes == []
    assert result.diagnosed is False
    assert llm.calls == 0  # tudo saudável: LLM nunca é tocado


def test_triage_failure_diagnoses_records_and_proposes():
    incidents = IncidentStore(":memory:")
    actions = ActionStore(":memory:")
    llm = FakeLLM()
    with respx.mock:
        respx.get("https://down.test/health").mock(return_value=httpx.Response(503))
        result = asyncio.run(
            triage(
                _config("https://down.test"),
                llm=llm, incidents=incidents, actions=actions, propose_kind="runbook",
            )
        )
    assert result.has_failures
    assert result.diagnosed is True
    assert llm.calls == 1
    assert len(result.outcomes) == 1
    o = result.outcomes[0]
    assert "Causa raiz" in o.root_cause
    assert o.action is not None
    assert o.action_is_new is True
    # incidente gravado e ação pendente
    assert incidents.similar("api")
    assert actions.pending()[0].kind == "runbook"
    incidents.close()
    actions.close()


def test_triage_dedups_open_action_on_repeat():
    actions = ActionStore(":memory:")
    llm = FakeLLM()
    cfg = _config("https://down.test")
    with respx.mock:
        respx.get("https://down.test/health").mock(return_value=httpx.Response(503))
        first = asyncio.run(triage(cfg, llm=llm, actions=actions, record=False))
        second = asyncio.run(triage(cfg, llm=llm, actions=actions, record=False))
    assert first.outcomes[0].action_is_new is True
    assert second.outcomes[0].action_is_new is False  # reaproveitou a pendente
    assert second.outcomes[0].action.id == first.outcomes[0].action.id
    assert len(actions.pending()) == 1  # não duplicou
    actions.close()


def test_triage_without_llm_degrades_gracefully():
    with respx.mock:
        respx.get("https://down.test/health").mock(return_value=httpx.Response(503))
        result = asyncio.run(triage(_config("https://down.test"), llm=None))
    assert result.has_failures
    assert result.diagnosed is False
    assert len(result.outcomes) == 1
    assert result.outcomes[0].root_cause == ""
    assert any("Sem LLM" in n for n in result.notes)


def test_propose_unique_reuses_pending():
    store = ActionStore(":memory:")
    a, new1 = store.propose_unique(Action(service="s", kind="runbook", description="x"))
    b, new2 = store.propose_unique(Action(service="s", kind="runbook", description="y"))
    assert new1 is True
    assert new2 is False
    assert a.id == b.id
    # tipo diferente cria nova ação
    _c, new3 = store.propose_unique(Action(service="s", kind="rollback", description="z"))
    assert new3 is True
    assert len(store.pending()) == 2
    store.close()


def test_cli_triage_exit_code_on_failure_without_llm(tmp_path):
    db = str(tmp_path / "t.db").replace("\\", "/")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "targets:\n  - name: x\n    url: https://x.test\n    expect:\n      status: 200\n"
        f"memory:\n  path: {db}\n",
        encoding="utf-8",
    )
    with respx.mock:
        respx.get("https://x.test/health").mock(return_value=httpx.Response(500))
        r = CliRunner().invoke(main, ["triage", "--config", str(cfg), "--no-propose"])
    assert r.exit_code == 1  # falha detectada
    # sem ANTHROPIC_API_KEY o RCA é pulado, mas a CLI não quebra
    assert "RCA" in r.output or "Sem LLM" in r.output


def test_cli_triage_json_output_on_failure(tmp_path):
    import json as _json

    db = str(tmp_path / "t.db").replace("\\", "/")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "targets:\n  - name: x\n    url: https://x.test\n    expect:\n      status: 200\n"
        f"memory:\n  path: {db}\n",
        encoding="utf-8",
    )
    with respx.mock:
        respx.get("https://x.test/health").mock(return_value=httpx.Response(500))
        r = CliRunner().invoke(main, ["triage", "--config", str(cfg), "--json", "--no-propose"])
    assert r.exit_code == 1
    payload = _json.loads(r.output)
    assert payload["overall"] == "down"
    assert payload["diagnosed"] is False  # sem chave: RCA pulado
    assert isinstance(payload["notes"], list)
    assert payload["outcomes"][0]["service"] == "x"


def test_cli_triage_all_healthy_exits_zero(tmp_path):
    db = str(tmp_path / "t.db").replace("\\", "/")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "targets:\n  - name: ok\n    url: https://ok.test\n    expect:\n      status: 200\n"
        f"memory:\n  path: {db}\n",
        encoding="utf-8",
    )
    with respx.mock:
        respx.get("https://ok.test/health").mock(return_value=httpx.Response(200))
        r = CliRunner().invoke(main, ["triage", "--config", str(cfg)])
    assert r.exit_code == 0
