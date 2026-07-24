import httpx
import respx

from sre_agent.agent import run_checks
from sre_agent.config import Config, Expect, Target
from sre_agent.models import HealthStatus
from sre_agent.signals.timeline import gather_changes, has_change_source


@respx.mock
async def test_run_checks_runs_parallel_and_sorts_failures_first():
    respx.get("https://a.test/health").mock(return_value=httpx.Response(200))
    respx.get("https://b.test/health").mock(return_value=httpx.Response(500))
    cfg = Config(
        targets=[
            Target(name="a", url="https://a.test", expect=Expect(status=200)),
            Target(name="b", url="https://b.test", expect=Expect(status=200)),
        ]
    )

    report = await run_checks(cfg)

    assert report.services[0].status is HealthStatus.DOWN  # falha ordenada primeiro
    assert report.has_failures
    assert len(report.services) == 2


def test_has_change_source_false_without_config():
    assert has_change_source(Config(targets=[])) is False


async def test_gather_changes_empty_without_sources():
    assert await gather_changes(Config(targets=[])) == []
