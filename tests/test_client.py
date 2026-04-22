import json

import httpx
import pytest

from govee_lights.client import GoveeClient, GOVEE_BASE_URL


def _mock_client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(
        base_url=GOVEE_BASE_URL,
        headers={"Govee-API-Key": "KEY", "Content-Type": "application/json"},
        transport=transport,
    )
    return GoveeClient(api_key="KEY", http=http)


def test_list_devices_returns_data_array():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/user/devices")
        assert request.headers["Govee-API-Key"] == "KEY"
        return httpx.Response(200, json={"code": 200, "data": [{"sku": "H6076"}]})

    client = _mock_client(handler)
    assert client.list_devices() == [{"sku": "H6076"}]


def test_set_color_rgb_posts_correct_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": 200, "msg": "success"})

    client = _mock_client(handler)
    client.set_color_rgb(sku="H6076", device_id="AA:BB", rgb=0x00FF00)

    assert seen["method"] == "POST"
    assert seen["path"].endswith("/device/control")
    assert seen["body"]["payload"]["sku"] == "H6076"
    assert seen["body"]["payload"]["device"] == "AA:BB"
    cap = seen["body"]["payload"]["capability"]
    assert cap["type"] == "devices.capabilities.color_setting"
    assert cap["instance"] == "colorRgb"
    assert cap["value"] == 0x00FF00
    assert isinstance(seen["body"]["requestId"], str) and seen["body"]["requestId"]


def test_set_color_temperature_posts_correct_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": 200, "msg": "success"})

    client = _mock_client(handler)
    client.set_color_temperature(sku="H6076", device_id="AA:BB", kelvin=2700)

    cap = seen["body"]["payload"]["capability"]
    assert cap["instance"] == "colorTemperatureK"
    assert cap["value"] == 2700


def test_set_brightness_posts_correct_payload():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": 200, "msg": "success"})

    client = _mock_client(handler)
    client.set_brightness(sku="H6076", device_id="AA:BB", percent=100)

    cap = seen["body"]["payload"]["capability"]
    assert cap["type"] == "devices.capabilities.range"
    assert cap["instance"] == "brightness"
    assert cap["value"] == 100


def test_non_2xx_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": 401, "msg": "invalid key"})

    client = _mock_client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        client.list_devices()
