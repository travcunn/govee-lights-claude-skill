from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Device:
    name: str
    sku: str
    device_id: str


TARGET_DEVICES: tuple[Device, ...] = (
    Device("Office light 1", "H6076", "D2:F8:C4:32:38:31:70:27"),
    Device("Office light 2", "H6076", "CB:AF:C3:32:38:31:3C:49"),
)

STATE_TO_PAYLOAD: dict[str, tuple[str, int]] = {
    "working":    ("colorTemperatureK", 2700),
    "your-turn":  ("colorRgb", 0xFFCC00),
    "permission": ("colorRgb", 0xFF0000),
}

PRIORITY: dict[str, int] = {
    "working": 1,
    "your-turn": 2,
    "permission": 3,
}

CACHE_PATH: Path = Path.home() / ".cache" / "govee-lights" / "state.json"
SESSION_TTL_SECONDS: int = 30 * 60
BRIGHTNESS_PERCENT: int = 100


def load_api_key() -> str:
    load_dotenv()
    key = os.environ.get("GOVEE_API_KEY")
    if not key:
        raise RuntimeError("GOVEE_API_KEY not set; put it in .env or your shell env")
    return key
