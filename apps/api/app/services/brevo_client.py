"""Thin client for the Brevo REST API (https://api.brevo.com/v3). This is
the first Brevo integration in this codebase (see Part 0 recon in the
free-launch signup build doc — no prior client, contact-attribute names, or
automation-trigger shape existed to extend), so contact attribute names and
the upsert shape here are new and should be confirmed against whatever
automation workflow already lives in the Brevo dashboard.
"""

from __future__ import annotations

import httpx

DEFAULT_BASE_URL = "https://api.brevo.com/v3"


class BrevoError(Exception):
    """Raised when the Brevo API rejects a request or is unreachable."""


class BrevoClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL) -> None:
        if not api_key:
            raise BrevoError("A Brevo API key is required.")
        self._client = httpx.Client(
            base_url=base_url,
            headers={"api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"},
            timeout=15.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BrevoClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: object) -> dict:
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise BrevoError(f"Brevo API request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise BrevoError(f"Brevo API returned {resp.status_code} for {method} {path}: {resp.text[:500]}")
        if not resp.content:
            return {}
        return resp.json()

    def send_transactional_email(
        self,
        *,
        to_email: str,
        sender_email: str,
        sender_name: str,
        template_id: int | None,
        magic_link_url: str,
    ) -> None:
        """Sends the magic-link email. Prefers a Brevo template (subject/copy
        owned by Danielle, kept out of this codebase) if one is configured;
        otherwise falls back to plain minimal inline HTML so the flow is
        testable end to end before a template exists.
        """
        if template_id is not None:
            payload: dict = {
                "to": [{"email": to_email}],
                "templateId": template_id,
                "params": {"MAGIC_LINK_URL": magic_link_url},
            }
        else:
            payload = {
                "sender": {"name": sender_name, "email": sender_email},
                "to": [{"email": to_email}],
                "subject": "Your sign-in link",
                "htmlContent": (
                    f'<p>Click the link below to sign in:</p><p><a href="{magic_link_url}">{magic_link_url}</a></p>'
                    "<p>This link expires in 20 minutes and can only be used once.</p>"
                ),
            }
        self._request("POST", "/smtp/email", json=payload)

    def send_html_email(
        self,
        *,
        to_email: str,
        sender_email: str,
        sender_name: str,
        subject: str,
        html_content: str,
        text_content: str | None = None,
    ) -> None:
        """Plain inline-HTML transactional send — used for the completed-scan
        results copy, which has no dashboard template (unlike the magic-link
        email, this isn't Danielle's copy to write; it's an internal ops
        notification).
        """
        payload = {
            "sender": {"name": sender_name, "email": sender_email},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html_content,
        }
        if text_content is not None:
            payload["textContent"] = text_content
        self._request(
            "POST",
            "/smtp/email",
            json=payload,
        )

    def upsert_contact(self, *, email: str, attributes: dict) -> None:
        """Creates the contact if new, or updates attributes on the existing
        one, via Brevo's updateEnabled upsert semantics.
        """
        self._request(
            "POST",
            "/contacts",
            json={"email": email, "attributes": attributes, "updateEnabled": True},
        )
