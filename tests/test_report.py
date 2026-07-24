from datetime import datetime, timezone

from sre_agent import report
from sre_agent.models import (
    Action,
    Advisory,
    AdvisoryLevel,
    ChangeEvent,
    ChangeKind,
    HealthReport,
    HealthStatus,
    ServiceHealth,
)

_NOW = datetime.now(timezone.utc)


def _report() -> HealthReport:
    return HealthReport(
        [
            ServiceHealth("a", "railway", "u", HealthStatus.DOWN, "HTTP 500", 500, 10),
            ServiceHealth("b", "railway", "u", HealthStatus.HEALTHY, "HTTP 200", 200, 5),
        ],
        _NOW, _NOW,
    )


def test_summarize_health_counts_and_flags_down():
    s = report.summarize(_report())
    assert "1/2" in s
    assert "FORA DO AR" in s


def test_render_health_runs_without_error():
    r = _report()
    report.render_table(r)
    report.print_summary(r)


def test_summarize_and_render_changes():
    events = [
        ChangeEvent(ChangeKind.DEPLOY, "r", "deploy", "a", "", _NOW, ok=False),
        ChangeEvent(ChangeKind.MERGE, "r", "#1 x", "a", "", _NOW),
    ]
    s = report.summarize_changes(events)
    assert "1 deploys" in s and "1 merges" in s
    assert "FALHARAM" in s
    report.render_timeline(events)
    report.print_changes_summary(events)


def test_summarize_and_render_advisories():
    advs = [Advisory("p", AdvisoryLevel.ERROR, "security", "n", "RLS off")]
    s = report.summarize_advisories(advs)
    assert "1 de nível ERROR" in s
    report.render_advisories(advs)
    report.print_advisories_summary(advs)


def test_render_actions_and_empty():
    report.render_actions([Action(service="s", kind="rollback", description="x")])
    report.render_actions([])
