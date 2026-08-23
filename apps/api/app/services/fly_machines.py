"""Thin client for the Fly Machines REST API (https://api.machines.dev/v1),
used to create the one-off scan-runner Machine for each scan and to inspect
its state. Deliberately minimal — only the operations the app actually uses.

Machines created here always set `config.auto_destroy = true` and
`config.restart.policy = "no"`, which is Fly's current documented mechanism
for a Machine that runs one job and cleans itself up: it is destroyed
automatically after it stops (a non-zero exit is kept around for a couple
of hours before Fly destroys it, which is useful for debugging a crashed
runner — see docs/fly-operations.md).
"""

from __future__ import annotations

import httpx

DEFAULT_BASE_URL = "https://api.machines.dev/v1"


class FlyMachinesError(Exception):
    """Raised when the Fly Machines API rejects a request or is unreachable."""


class FlyMachinesClient:
    def __init__(self, api_token: str, app_name: str, base_url: str = DEFAULT_BASE_URL) -> None:
        if not api_token or not app_name:
            raise FlyMachinesError("Fly API token and app name are required to create a Machine.")
        self._app_name = app_name
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FlyMachinesClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: object) -> dict | list:
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise FlyMachinesError(f"Fly Machines API request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise FlyMachinesError(
                f"Fly Machines API returned {resp.status_code} for {method} {path}: {resp.text[:500]}"
            )
        if not resp.content:
            return {}
        return resp.json()

    def create_machine(
        self,
        *,
        name: str,
        region: str,
        image: str,
        env: dict[str, str],
        cmd: list[str] | None = None,
        cpu_kind: str = "shared",
        cpus: int = 2,
        memory_mb: int = 2048,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """POST /apps/{app_name}/machines — creates and starts the Machine."""
        config: dict = {
            "image": image,
            "env": env,
            "guest": {"cpu_kind": cpu_kind, "cpus": cpus, "memory_mb": memory_mb},
            "restart": {"policy": "no"},
            "auto_destroy": True,
        }
        if cmd:
            config["init"] = {"cmd": cmd}
        if metadata:
            config["metadata"] = metadata

        body = {"name": name, "region": region, "config": config}
        return self._request("POST", f"/apps/{self._app_name}/machines", json=body)

    def wait(self, machine_id: str, *, state: str = "started", timeout_seconds: int = 60) -> dict:
        """GET /apps/{app_name}/machines/{machine_id}/wait?state=..."""
        return self._request(
            "GET",
            f"/apps/{self._app_name}/machines/{machine_id}/wait",
            params={"state": state, "timeout": timeout_seconds},
        )

    def get_machine(self, machine_id: str) -> dict:
        return self._request("GET", f"/apps/{self._app_name}/machines/{machine_id}")

    def list_machines(self) -> list[dict]:
        result = self._request("GET", f"/apps/{self._app_name}/machines")
        return result if isinstance(result, list) else []

    def stop(self, machine_id: str) -> None:
        """POST /apps/{app_name}/machines/{machine_id}/stop"""
        self._request("POST", f"/apps/{self._app_name}/machines/{machine_id}/stop")

    def destroy(self, machine_id: str, *, force: bool = True) -> None:
        """DELETE /apps/{app_name}/machines/{machine_id}?force=true"""
        self._request(
            "DELETE",
            f"/apps/{self._app_name}/machines/{machine_id}",
            params={"force": "true" if force else "false"},
        )
