"""Email-on-failure via Resend.

Design §6 pins Resend as the v1 alert mechanism. We POST directly to
the REST API rather than depending on the `resend` Python SDK —
keeps the dep tree light, and the API surface we touch is one
endpoint with auth header + JSON body.

If `RESEND_API_KEY` or `SOUNDINGS_ALERT_EMAIL` aren't set, the function
logs a warning and returns. We never raise from this path: alert
failures must not cascade into the calling operation.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"
_FROM_ADDRESS = "alerts@soundings.dev"


def send_alert(
    subject: str,
    body: str,
    *,
    source: str,
    http_client: httpx.Client | None = None,
) -> None:
    """Fire an alert email. Best-effort; never raises."""
    api_key = os.environ.get("RESEND_API_KEY")
    to_addr = os.environ.get("SOUNDINGS_ALERT_EMAIL")
    if not api_key or not to_addr:
        logger.warning(
            "alert dropped (no RESEND_API_KEY / SOUNDINGS_ALERT_EMAIL): source=%s subject=%s",
            source,
            subject,
        )
        return

    payload = {
        "from": _FROM_ADDRESS,
        "to": [to_addr],
        "subject": f"[soundings] {subject}",
        "text": f"source: {source}\n\n{body}",
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    client = http_client or httpx.Client(timeout=10.0)
    owns_client = http_client is None
    try:
        response = client.post(RESEND_ENDPOINT, json=payload, headers=headers)
        if response.status_code >= 400:
            logger.error(
                "resend rejected alert: status=%s body=%s",
                response.status_code,
                response.text,
            )
    except Exception:
        logger.exception("resend POST failed; alert lost")
    finally:
        if owns_client:
            client.close()
