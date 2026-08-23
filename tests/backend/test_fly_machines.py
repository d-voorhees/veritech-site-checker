"""FlyMachinesClient against a mocked HTTP transport (respx) — verifies the
request shape sent to the Fly Machines API and error handling. Never talks
to a real Fly app or needs real credentials.
"""

import pytest
import respx
from httpx import Response

from app.services.fly_machines import FlyMachinesClient, FlyMachinesError

BASE_URL = "https://api.machines.dev/v1"


@pytest.fixture()
def client():
    return FlyMachinesClient(api_token="test-token", app_name="veritech-scan-test", base_url=BASE_URL)


def test_constructor_requires_token_and_app_name():
    with pytest.raises(FlyMachinesError):
        FlyMachinesClient(api_token="", app_name="veritech-scan-test")
    with pytest.raises(FlyMachinesError):
        FlyMachinesClient(api_token="test-token", app_name="")


@respx.mock
def test_create_machine_sends_documented_request_shape(client):
    route = respx.post(f"{BASE_URL}/apps/veritech-scan-test/machines").mock(
        return_value=Response(200, json={"id": "abc123", "name": "scan-runner-xyz", "state": "started"})
    )

    result = client.create_machine(
        name="scan-runner-xyz",
        region="iad",
        image="registry.fly.io/veritech-scan-test:latest",
        env={"SCAN_ID": "xyz"},
        cmd=["/app/scripts/entrypoint.sh", "scan-runner"],
        metadata={"role": "scan-runner"},
    )

    assert result["id"] == "abc123"
    assert route.called
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer test-token"

    import json

    body = json.loads(request.content)
    assert body["name"] == "scan-runner-xyz"
    assert body["region"] == "iad"
    assert body["config"]["image"] == "registry.fly.io/veritech-scan-test:latest"
    assert body["config"]["env"] == {"SCAN_ID": "xyz"}
    assert body["config"]["init"]["cmd"] == ["/app/scripts/entrypoint.sh", "scan-runner"]
    assert body["config"]["auto_destroy"] is True
    assert body["config"]["restart"]["policy"] == "no"
    assert body["config"]["metadata"] == {"role": "scan-runner"}


@respx.mock
def test_create_machine_raises_fly_machines_error_on_4xx(client):
    respx.post(f"{BASE_URL}/apps/veritech-scan-test/machines").mock(
        return_value=Response(422, text="invalid region")
    )
    with pytest.raises(FlyMachinesError):
        client.create_machine(
            name="scan-runner-xyz", region="not-a-region", image="img", env={}, cmd=None
        )


@respx.mock
def test_create_machine_raises_fly_machines_error_on_network_failure(client):
    import httpx

    respx.post(f"{BASE_URL}/apps/veritech-scan-test/machines").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(FlyMachinesError):
        client.create_machine(name="scan-runner-xyz", region="iad", image="img", env={}, cmd=None)


@respx.mock
def test_wait_hits_wait_endpoint_with_state_param(client):
    route = respx.get(f"{BASE_URL}/apps/veritech-scan-test/machines/abc123/wait").mock(
        return_value=Response(200, json={"ok": True})
    )
    client.wait("abc123", state="started", timeout_seconds=30)
    assert route.called
    assert route.calls.last.request.url.params["state"] == "started"
    assert route.calls.last.request.url.params["timeout"] == "30"


@respx.mock
def test_stop_hits_stop_endpoint(client):
    route = respx.post(f"{BASE_URL}/apps/veritech-scan-test/machines/abc123/stop").mock(return_value=Response(200))
    client.stop("abc123")
    assert route.called


@respx.mock
def test_destroy_hits_delete_endpoint_with_force_param(client):
    route = respx.delete(f"{BASE_URL}/apps/veritech-scan-test/machines/abc123").mock(return_value=Response(200))
    client.destroy("abc123", force=True)
    assert route.called
    assert route.calls.last.request.url.params["force"] == "true"


@respx.mock
def test_list_machines_returns_list(client):
    respx.get(f"{BASE_URL}/apps/veritech-scan-test/machines").mock(
        return_value=Response(200, json=[{"id": "a"}, {"id": "b"}])
    )
    result = client.list_machines()
    assert len(result) == 2
