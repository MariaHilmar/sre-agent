from datetime import datetime, timezone

import httpx
import respx

from sre_agent.config import RailwayConfig, VercelConfig
from sre_agent.signals.railway import RailwayAdapter
from sre_agent.signals.vercel import VercelAdapter

# --- Vercel ---------------------------------------------------------------

def _vercel_payload() -> dict:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return {
        "deployments": [
            {
                "name": "meu-front",
                "state": "ERROR",
                "created": now_ms,
                "url": "meu-front-abc.vercel.app",
                "creator": {"username": "dev1"},
            },
            {
                "name": "meu-front",
                "state": "READY",
                "created": now_ms - 3600_000,
                "url": "meu-front-xyz.vercel.app",
                "creator": {"username": "dev2"},
            },
            {  # em andamento → ignorado
                "name": "meu-front",
                "state": "BUILDING",
                "created": now_ms,
                "url": "meu-front-bbb.vercel.app",
                "creator": {"username": "dev1"},
            },
        ]
    }


@respx.mock
async def test_vercel_maps_terminal_states_and_flags_error():
    respx.get(path__regex=r"/v6/deployments$").mock(
        return_value=httpx.Response(200, json=_vercel_payload())
    )

    events = await VercelAdapter(VercelConfig(token="x", projects=["prj"])).fetch_changes()

    assert len(events) == 2  # BUILDING ignorado
    failed = [e for e in events if e.is_failed_deploy]
    assert len(failed) == 1
    assert failed[0].ref == "vercel"


# --- Railway --------------------------------------------------------------

def _railway_payload() -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "data": {
            "deployments": {
                "edges": [
                    {
                        "node": {
                            "id": "d1",
                            "status": "FAILED",
                            "createdAt": now,
                            "staticUrl": "svc.up.railway.app",
                            "service": {"name": "sj-scraping"},
                        }
                    },
                    {
                        "node": {
                            "id": "d2",
                            "status": "SUCCESS",
                            "createdAt": now,
                            "staticUrl": "svc.up.railway.app",
                            "service": {"name": "sj-scraping"},
                        }
                    },
                    {  # em andamento → ignorado
                        "node": {
                            "id": "d3",
                            "status": "DEPLOYING",
                            "createdAt": now,
                            "staticUrl": "svc.up.railway.app",
                            "service": {"name": "sj-scraping"},
                        }
                    },
                ]
            }
        }
    }


@respx.mock
async def test_railway_maps_status_and_flags_failure():
    respx.post(path__regex=r"/graphql/v2$").mock(
        return_value=httpx.Response(200, json=_railway_payload())
    )

    cfg = RailwayConfig(token="x", services=["svc1"])
    events = await RailwayAdapter(cfg).fetch_changes()

    assert len(events) == 2  # DEPLOYING ignorado
    failed = [e for e in events if e.is_failed_deploy]
    assert len(failed) == 1
    assert failed[0].repo == "sj-scraping"
