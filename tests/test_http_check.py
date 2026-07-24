import httpx
import respx

from sre_agent.checks.http import check_http
from sre_agent.config import Config, Expect, Target
from sre_agent.models import HealthStatus


def _cfg() -> Config:
    return Config(targets=[], default_timeout=5, default_health_path="/health")


@respx.mock
async def test_healthy_when_json_matches():
    respx.get("https://svc.test/health").mock(
        return_value=httpx.Response(200, json={"status": "healthy", "database": "ok"})
    )
    target = Target(
        name="svc", url="https://svc.test", platform="railway",
        expect=Expect(status=200, json={"status": "healthy", "database": "ok"}),
    )
    async with httpx.AsyncClient() as client:
        res = await check_http(target, _cfg(), client)

    assert res.status is HealthStatus.HEALTHY
    assert res.http_status == 200
    assert res.latency_ms is not None


@respx.mock
async def test_down_on_500():
    respx.get("https://svc.test/health").mock(return_value=httpx.Response(500))
    target = Target(name="svc", url="https://svc.test", expect=Expect(status=200))
    async with httpx.AsyncClient() as client:
        res = await check_http(target, _cfg(), client)

    assert res.status is HealthStatus.DOWN
    assert "500" in res.detail


@respx.mock
async def test_degraded_when_json_mismatch():
    respx.get("https://svc.test/health").mock(
        return_value=httpx.Response(200, json={"status": "healthy", "database": "down"})
    )
    target = Target(
        name="svc", url="https://svc.test",
        expect=Expect(status=200, json={"status": "healthy", "database": "ok"}),
    )
    async with httpx.AsyncClient() as client:
        res = await check_http(target, _cfg(), client)

    assert res.status is HealthStatus.DEGRADED
    assert "database" in res.detail


@respx.mock
async def test_down_on_timeout():
    respx.get("https://svc.test/health").mock(side_effect=httpx.TimeoutException("t"))
    target = Target(name="svc", url="https://svc.test", expect=Expect(status=200))
    async with httpx.AsyncClient() as client:
        res = await check_http(target, _cfg(), client)

    assert res.status is HealthStatus.DOWN
    assert "timeout" in res.detail
