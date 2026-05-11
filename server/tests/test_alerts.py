import httpx
import pytest

from soundings.alerts.resend import RESEND_ENDPOINT, send_alert


def test_send_alert_posts_to_resend_with_auth_and_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "key-123")
    monkeypatch.setenv("SOUNDINGS_ALERT_EMAIL", "ops@example.org")

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = request.read().decode("utf-8")
        return httpx.Response(200, json={"id": "fake"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        send_alert(
            "Sanitiser blew up",
            "details here",
            source="sanitiser",
            http_client=client,
        )

    assert captured["url"] == RESEND_ENDPOINT
    assert captured["auth"] == "Bearer key-123"
    assert "ops@example.org" in str(captured["body"])
    assert "sanitiser" in str(captured["body"])
    assert "Sanitiser blew up" in str(captured["body"])


def test_send_alert_silently_drops_without_env(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("SOUNDINGS_ALERT_EMAIL", raising=False)

    # No exception, no HTTP call attempted. Should log a warning.
    with caplog.at_level("WARNING"):
        send_alert("any", "body", source="retention")
    assert any("alert dropped" in record.message for record in caplog.records)


def test_send_alert_swallows_http_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "key-123")
    monkeypatch.setenv("SOUNDINGS_ALERT_EMAIL", "ops@example.org")

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ConnectError("simulated")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        # Must not raise.
        send_alert("x", "y", source="test", http_client=client)
