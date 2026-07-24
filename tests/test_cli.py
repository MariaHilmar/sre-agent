import httpx
import respx
from click.testing import CliRunner

from sre_agent.cli import main


def _config(tmp_path, body: str = "targets: []\n") -> str:
    db = str(tmp_path / "t.db").replace("\\", "/")
    p = tmp_path / "config.yaml"
    p.write_text(body + f"memory:\n  path: {db}\n", encoding="utf-8")
    return str(p)


def test_approval_flow_propose_actions_approve(tmp_path):
    cfg = _config(tmp_path)
    runner = CliRunner()

    r = runner.invoke(
        main,
        ["propose", "--config", cfg, "--service", "s", "--kind", "rollback", "--description", "x"],
    )
    assert r.exit_code == 0
    assert "#1" in r.output

    r = runner.invoke(main, ["actions", "--config", cfg])
    assert "rollback" in r.output

    r = runner.invoke(main, ["approve", "--config", cfg, "1"])
    assert r.exit_code == 0
    assert "approved" in r.output

    # aprovar de novo falha (já decidida)
    r = runner.invoke(main, ["approve", "--config", cfg, "1"])
    assert r.exit_code == 2


def test_reject_unknown_action(tmp_path):
    cfg = _config(tmp_path)
    r = CliRunner().invoke(main, ["reject", "--config", cfg, "999"])
    assert r.exit_code == 2


@respx.mock
def test_check_command_exit_code_on_failure(tmp_path):
    respx.get("https://x.test/health").mock(return_value=httpx.Response(500))
    cfg = _config(
        tmp_path,
        "targets:\n  - name: x\n    url: https://x.test\n    expect:\n      status: 200\n",
    )
    r = CliRunner().invoke(main, ["check", "--config", cfg])
    assert r.exit_code == 1  # falha detectada


def test_diagnose_all_healthy_exits_zero(tmp_path):
    # sem targets => sem falhas nunca; mas diagnose exige targets, então testamos
    # o caminho "tudo saudável" com um serviço que responde 200.
    with respx.mock:
        respx.get("https://ok.test/health").mock(return_value=httpx.Response(200))
        cfg = _config(
            tmp_path,
            "targets:\n  - name: ok\n    url: https://ok.test\n    expect:\n      status: 200\n",
        )
        r = CliRunner().invoke(main, ["diagnose", "--config", cfg])
    assert r.exit_code == 0
    assert "saudável" in r.output
