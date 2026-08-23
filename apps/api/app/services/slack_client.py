"""Posts to a Slack Incoming Webhook (https://api.slack.com/messaging/webhooks)
for scan-lifecycle notifications. One message shape, one operation — this
app doesn't need the full Slack Web API.
"""

from __future__ import annotations

import httpx


class SlackError(Exception):
    """Raised when the Slack webhook rejects a request or is unreachable."""


def send_slack_notification(webhook_url: str, text: str) -> None:
    if not webhook_url:
        return
    try:
        resp = httpx.post(webhook_url, json={"text": text}, timeout=10.0)
    except httpx.HTTPError as exc:
        raise SlackError(f"Slack webhook request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise SlackError(f"Slack webhook returned {resp.status_code}: {resp.text[:500]}")
