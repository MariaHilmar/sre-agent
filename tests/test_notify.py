import httpx
import respx

from sre_agent.config import NotifyConfig
from sre_agent.notify import SlackNotifier, build_notifier


@respx.mock
def test_slack_notifier_posts_payload():
    route = respx.post("https://hooks.slack.test/xxx").mock(
        return_value=httpx.Response(200, text="ok")
    )

    SlackNotifier("https://hooks.slack.test/xxx").send("DOWN · saúde", "1 serviço fora do ar")

    assert route.called
    sent = route.calls.last.request
    body = sent.content.decode()
    assert "DOWN" in body
    assert "fora do ar" in body


def test_build_notifier_disabled_returns_none():
    assert build_notifier(NotifyConfig(enabled=False, slack_webhook="x")) is None


def test_build_notifier_enabled_without_webhook_returns_none():
    assert build_notifier(NotifyConfig(enabled=True, slack_webhook="")) is None


def test_build_notifier_enabled_with_webhook_returns_slack():
    notifier = build_notifier(NotifyConfig(enabled=True, slack_webhook="https://hooks.slack.test/x"))
    assert isinstance(notifier, SlackNotifier)
