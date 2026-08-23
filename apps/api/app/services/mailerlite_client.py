"""Thin client for the MailerLite subscribers API
(https://connect.mailerlite.com/api). Only the one upsert operation this app
needs — adding a verified signup to the veritech-scan-user group without
disturbing any other group membership.
"""

from __future__ import annotations

import httpx

DEFAULT_BASE_URL = "https://connect.mailerlite.com/api"


class MailerLiteError(Exception):
    """Raised when the MailerLite API rejects a request or is unreachable."""


class MailerLiteClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL) -> None:
        if not api_key:
            raise MailerLiteError("A MailerLite API key is required.")
        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=15.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MailerLiteClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def upsert_subscriber(self, *, email: str, group_id: str) -> None:
        """POST /subscribers is an upsert: creates the subscriber if new, or
        updates and adds the group if the email already exists, without
        removing existing group memberships.
        """
        try:
            resp = self._client.post("/subscribers", json={"email": email, "groups": [group_id]})
        except httpx.HTTPError as exc:
            raise MailerLiteError(f"MailerLite API request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise MailerLiteError(f"MailerLite API returned {resp.status_code}: {resp.text[:500]}")
