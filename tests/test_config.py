from sre_agent.config import Config

_FULL = """
defaults:
  timeout_seconds: 7
  health_path: /hz
targets:
  - name: api
    platform: railway
    url: https://api.test/
    expect:
      status: 201
      json: {status: ok}
github:
  token: ${MY_TOKEN}
  repos: [o/r]
  lookback_hours: 48
supabase:
  access_token: ${MY_TOKEN}
  projects: [ref1]
vercel:
  token: ${MY_TOKEN}
  projects: [prj]
railway:
  token: ${MY_TOKEN}
  services: [svc]
llm:
  model: claude-x
memory:
  path: x.db
notify:
  enabled: true
  slack_webhook: ${MY_TOKEN}
"""


def test_load_full_config_with_env_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "secret123")
    f = tmp_path / "c.yaml"
    f.write_text(_FULL, encoding="utf-8")

    c = Config.load(f)

    assert c.default_timeout == 7
    assert c.default_health_path == "/hz"
    t = c.targets[0]
    assert t.url == "https://api.test"  # barra final removida
    assert t.expect.status == 201
    assert t.expect.json == {"status": "ok"}
    assert c.github.token == "secret123"  # ${MY_TOKEN} expandido
    assert c.github.lookback_hours == 48
    assert c.supabase.projects == ["ref1"]
    assert c.vercel.projects == ["prj"]
    assert c.railway.services == ["svc"]
    assert c.llm.model == "claude-x"
    assert c.memory.path == "x.db"
    assert c.notify.enabled is True
    assert c.notify.slack_webhook == "secret123"


def test_load_minimal_uses_defaults(tmp_path):
    f = tmp_path / "m.yaml"
    f.write_text("targets: []\n", encoding="utf-8")

    c = Config.load(f)

    assert c.targets == []
    assert c.github is None
    assert c.supabase is None
    assert c.llm.provider == "anthropic"
    assert c.llm.model == "claude-sonnet-5"
    assert c.memory.path == "incidents.db"
    assert c.notify.enabled is False


def test_missing_env_var_expands_to_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("ABSENT_TOKEN", raising=False)
    f = tmp_path / "c.yaml"
    f.write_text(
        "targets: []\ngithub:\n  token: ${ABSENT_TOKEN}\n  repos: [o/r]\n",
        encoding="utf-8",
    )

    c = Config.load(f)

    assert c.github.token == ""
