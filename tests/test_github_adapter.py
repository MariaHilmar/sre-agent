from datetime import datetime, timedelta, timezone

import httpx
import respx

from sre_agent.config import GitHubConfig
from sre_agent.models import ChangeKind
from sre_agent.signals.github import GitHubAdapter


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _cfg() -> GitHubConfig:
    return GitHubConfig(token="x", repos=["acme/app"], lookback_hours=24)


_NOW = datetime.now(timezone.utc)


def _runs_payload() -> dict:
    return {
        "workflow_runs": [
            {  # deploy que falhou → alertável
                "name": "deploy-railway",
                "status": "completed",
                "conclusion": "failure",
                "created_at": _iso(_NOW - timedelta(hours=1)),
                "html_url": "https://github.com/acme/app/actions/runs/2",
                "head_branch": "main",
                "actor": {"login": "dev1"},
            },
            {  # deploy ok
                "name": "deploy-railway",
                "status": "completed",
                "conclusion": "success",
                "created_at": _iso(_NOW - timedelta(hours=3)),
                "html_url": "https://github.com/acme/app/actions/runs/1",
                "head_branch": "main",
                "actor": {"login": "dev2"},
            },
            {  # em andamento → ignorado
                "name": "ci",
                "status": "in_progress",
                "conclusion": None,
                "created_at": _iso(_NOW),
                "html_url": "https://github.com/acme/app/actions/runs/3",
                "head_branch": "feature",
                "actor": {"login": "dev1"},
            },
            {  # antigo, fora da janela → ignorado
                "name": "deploy-railway",
                "status": "completed",
                "conclusion": "success",
                "created_at": _iso(_NOW - timedelta(hours=48)),
                "html_url": "https://github.com/acme/app/actions/runs/0",
                "head_branch": "main",
                "actor": {"login": "dev1"},
            },
        ]
    }


def _pulls_payload() -> list:
    return [
        {  # mergeado recentemente → contexto
            "number": 142,
            "title": "refatora pool de conexão",
            "merged_at": _iso(_NOW - timedelta(hours=2)),
            "html_url": "https://github.com/acme/app/pull/142",
            "user": {"login": "dev2"},
            "base": {"ref": "main"},
        },
        {  # fechado sem merge → ignorado
            "number": 143,
            "title": "wip",
            "merged_at": None,
            "html_url": "https://github.com/acme/app/pull/143",
            "user": {"login": "dev1"},
            "base": {"ref": "main"},
        },
    ]


@respx.mock
async def test_fetch_changes_parses_deploys_and_merges():
    respx.get(path__regex=r"/actions/runs$").mock(
        return_value=httpx.Response(200, json=_runs_payload())
    )
    respx.get(path__regex=r"/pulls$").mock(
        return_value=httpx.Response(200, json=_pulls_payload())
    )

    events = await GitHubAdapter(_cfg()).fetch_changes()

    deploys = [e for e in events if e.kind is ChangeKind.DEPLOY]
    merges = [e for e in events if e.kind is ChangeKind.MERGE]

    # 2 deploys concluídos na janela (falha + sucesso); em andamento e antigo fora
    assert len(deploys) == 2
    # 1 merge na janela; o fechado-sem-merge fica de fora
    assert len(merges) == 1
    assert merges[0].title.startswith("#142")


@respx.mock
async def test_failed_deploy_is_flagged():
    respx.get(path__regex=r"/actions/runs$").mock(
        return_value=httpx.Response(200, json=_runs_payload())
    )
    respx.get(path__regex=r"/pulls$").mock(
        return_value=httpx.Response(200, json=[])
    )

    events = await GitHubAdapter(_cfg()).fetch_changes()

    failed = [e for e in events if e.is_failed_deploy]
    assert len(failed) == 1
    assert failed[0].title == "deploy-railway"


@respx.mock
async def test_events_sorted_most_recent_first():
    respx.get(path__regex=r"/actions/runs$").mock(
        return_value=httpx.Response(200, json=_runs_payload())
    )
    respx.get(path__regex=r"/pulls$").mock(
        return_value=httpx.Response(200, json=_pulls_payload())
    )

    events = await GitHubAdapter(_cfg()).fetch_changes()

    timestamps = [e.timestamp for e in events]
    assert timestamps == sorted(timestamps, reverse=True)
