"""Health check HTTP — Camada 1 do runbook.

Para cada serviço: GET no endpoint de health, valida o status HTTP e,
opcionalmente, um subconjunto do JSON de resposta (ex.: status=healthy,
database=ok). Mede latência. Equivalente Python dos smoke_railway.sh.
"""

from __future__ import annotations

import time

import httpx

from ..config import Config, Target
from ..models import HealthStatus, ServiceHealth


def _json_matches(body: dict, expected: dict) -> tuple[bool, str]:
    """Verifica se `body` contém todos os pares esperados. Retorna (ok, detalhe)."""
    mismatches = [
        f"{key}={body.get(key)!r} (esperado {want!r})"
        for key, want in expected.items()
        if body.get(key) != want
    ]
    if mismatches:
        return False, "; ".join(mismatches)
    return True, ", ".join(f"{k}={v}" for k, v in expected.items()) or "ok"


async def check_http(
    target: Target, config: Config, client: httpx.AsyncClient
) -> ServiceHealth:
    path = target.health_path if target.health_path is not None else config.default_health_path
    url = f"{target.url}{path}"
    timeout = target.timeout_seconds or config.default_timeout

    started = time.perf_counter()
    try:
        resp = await client.get(url, timeout=timeout)
    except httpx.TimeoutException:
        return ServiceHealth(
            target.name, target.platform, url, HealthStatus.DOWN,
            detail=f"timeout após {timeout}s",
        )
    except httpx.HTTPError as exc:
        return ServiceHealth(
            target.name, target.platform, url, HealthStatus.DOWN,
            detail=f"erro de conexão: {exc.__class__.__name__}",
        )
    latency_ms = int((time.perf_counter() - started) * 1000)

    if resp.status_code != target.expect.status:
        return ServiceHealth(
            target.name, target.platform, url, HealthStatus.DOWN,
            detail=f"HTTP {resp.status_code} (esperado {target.expect.status})",
            http_status=resp.status_code, latency_ms=latency_ms,
        )

    if target.expect.json:
        try:
            body = resp.json()
        except ValueError:
            return ServiceHealth(
                target.name, target.platform, url, HealthStatus.DEGRADED,
                detail="200 mas resposta não-JSON",
                http_status=resp.status_code, latency_ms=latency_ms,
            )
        ok, detail = _json_matches(body if isinstance(body, dict) else {}, target.expect.json)
        return ServiceHealth(
            target.name, target.platform, url,
            HealthStatus.HEALTHY if ok else HealthStatus.DEGRADED,
            detail=detail, http_status=resp.status_code, latency_ms=latency_ms,
        )

    return ServiceHealth(
        target.name, target.platform, url, HealthStatus.HEALTHY,
        detail=f"HTTP {resp.status_code}", http_status=resp.status_code, latency_ms=latency_ms,
    )
