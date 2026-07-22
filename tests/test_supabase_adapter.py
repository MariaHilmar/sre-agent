import httpx
import respx

from sre_agent.config import SupabaseConfig
from sre_agent.models import AdvisoryLevel
from sre_agent.signals.supabase import SupabaseAdapter


def _cfg() -> SupabaseConfig:
    return SupabaseConfig(access_token="x", projects=["proj1"])


def _security_payload() -> dict:
    return {
        "lints": [
            {
                "name": "rls_disabled_in_public",
                "level": "ERROR",
                "title": "RLS desabilitado em tabela pública",
                "detail": "A tabela public.clientes não tem RLS.",
                "remediation": "https://supabase.com/docs/guides/database/postgres/row-level-security",
            }
        ]
    }


def _performance_payload() -> dict:
    return {
        "lints": [
            {
                "name": "unindexed_foreign_keys",
                "level": "INFO",
                "title": "Chave estrangeira sem índice",
                "detail": "processos.cliente_id sem índice.",
            }
        ]
    }


@respx.mock
async def test_fetch_advisories_maps_levels_and_sorts():
    respx.get(path__regex=r"/advisors/security$").mock(
        return_value=httpx.Response(200, json=_security_payload())
    )
    respx.get(path__regex=r"/advisors/performance$").mock(
        return_value=httpx.Response(200, json=_performance_payload())
    )

    advisories = await SupabaseAdapter(_cfg()).fetch_advisories()

    assert len(advisories) == 2
    # ERROR ordenado antes de INFO
    assert advisories[0].level is AdvisoryLevel.ERROR
    assert advisories[0].category == "security"
    assert advisories[-1].level is AdvisoryLevel.INFO


@respx.mock
async def test_error_advisory_is_alertable():
    respx.get(path__regex=r"/advisors/security$").mock(
        return_value=httpx.Response(200, json=_security_payload())
    )
    respx.get(path__regex=r"/advisors/performance$").mock(
        return_value=httpx.Response(200, json={"lints": []})
    )

    advisories = await SupabaseAdapter(_cfg()).fetch_advisories()

    alertable = [a for a in advisories if a.level.is_alertable]
    assert len(alertable) == 1
    assert alertable[0].name == "rls_disabled_in_public"
