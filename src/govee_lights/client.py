from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx


GOVEE_BASE_URL = "https://openapi.api.govee.com/router/api/v1"


@dataclass
class GoveeClient:
    api_key: str
    http: httpx.Client | None = None

    def __post_init__(self) -> None:
        if self.http is None:
            self.http = httpx.Client(
                base_url=GOVEE_BASE_URL,
                headers={
                    "Govee-API-Key": self.api_key,
                    "Content-Type": "application/json",
                },
                timeout=5.0,
            )

    def list_devices(self) -> list[dict]:
        r = self.http.get("/user/devices")
        r.raise_for_status()
        return r.json().get("data", [])

    def set_color_rgb(self, sku: str, device_id: str, rgb: int) -> None:
        self._control(sku, device_id, "devices.capabilities.color_setting", "colorRgb", rgb)

    def set_color_temperature(self, sku: str, device_id: str, kelvin: int) -> None:
        self._control(sku, device_id, "devices.capabilities.color_setting", "colorTemperatureK", kelvin)

    def set_brightness(self, sku: str, device_id: str, percent: int) -> None:
        self._control(sku, device_id, "devices.capabilities.range", "brightness", percent)

    def _control(self, sku: str, device_id: str, capability_type: str, instance: str, value: int) -> None:
        payload = {
            "requestId": str(uuid.uuid4()),
            "payload": {
                "sku": sku,
                "device": device_id,
                "capability": {
                    "type": capability_type,
                    "instance": instance,
                    "value": value,
                },
            },
        }
        r = self.http.post("/device/control", json=payload)
        r.raise_for_status()
