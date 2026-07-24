from datetime import datetime, timezone

from sre_agent.models import (
    AdvisoryLevel,
    ChangeEvent,
    ChangeKind,
    HealthReport,
    HealthStatus,
    ServiceHealth,
)

_NOW = datetime.now(timezone.utc)


def _svc(status: HealthStatus) -> ServiceHealth:
    return ServiceHealth(name="s", platform="p", url="u", status=status)


def _report(*statuses: HealthStatus) -> HealthReport:
    return HealthReport([_svc(s) for s in statuses], _NOW, _NOW)


def test_overall_down_wins_and_counts():
    r = _report(HealthStatus.HEALTHY, HealthStatus.DOWN, HealthStatus.DEGRADED)
    assert r.overall is HealthStatus.DOWN
    assert r.has_failures
    assert r.count(HealthStatus.HEALTHY) == 1


def test_overall_degraded_when_no_down():
    r = _report(HealthStatus.HEALTHY, HealthStatus.DEGRADED)
    assert r.overall is HealthStatus.DEGRADED


def test_overall_all_healthy():
    r = _report(HealthStatus.HEALTHY, HealthStatus.HEALTHY)
    assert r.overall is HealthStatus.HEALTHY
    assert not r.has_failures


def test_overall_empty_is_unknown():
    assert _report().overall is HealthStatus.UNKNOWN


def test_severity_orders_down_before_healthy():
    assert HealthStatus.DOWN.severity < HealthStatus.HEALTHY.severity


def test_status_has_emoji():
    assert all(s.emoji for s in HealthStatus)


def test_change_is_failed_deploy():
    failed = ChangeEvent(ChangeKind.DEPLOY, "r", "t", "a", "", _NOW, ok=False)
    ok = ChangeEvent(ChangeKind.DEPLOY, "r", "t", "a", "", _NOW, ok=True)
    merge = ChangeEvent(ChangeKind.MERGE, "r", "t", "a", "", _NOW)
    assert failed.is_failed_deploy
    assert not ok.is_failed_deploy
    assert not merge.is_failed_deploy


def test_advisory_level_alertable():
    assert AdvisoryLevel.ERROR.is_alertable
    assert not AdvisoryLevel.WARN.is_alertable
    assert not AdvisoryLevel.INFO.is_alertable
