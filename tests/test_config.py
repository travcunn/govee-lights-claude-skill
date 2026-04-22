from pathlib import Path

import pytest

from govee_lights import config


def test_target_devices_are_the_two_office_lights():
    names = [d.name for d in config.TARGET_DEVICES]
    assert names == ["Office light 1", "Office light 2"]
    for d in config.TARGET_DEVICES:
        assert d.sku == "H6076"


def test_state_payload_map_covers_sticky_states():
    assert set(config.STATE_TO_PAYLOAD) == {"working", "permission"}
    assert config.STATE_TO_PAYLOAD["working"] == ("colorTemperatureK", 2700)
    assert config.STATE_TO_PAYLOAD["permission"] == ("colorRgb", 0xFF0000)


def test_priority_orders_permission_over_working():
    assert config.PRIORITY["permission"] > config.PRIORITY["working"]


def test_flash_config_is_pure_green_two_seconds():
    assert config.FLASH_RGB == 0x00FF00
    assert config.FLASH_DURATION_SECONDS == 2.0


def test_cache_path_is_under_user_cache_dir():
    assert config.CACHE_PATH == Path.home() / ".cache" / "govee-lights" / "state.json"


def test_session_ttl_is_2_minutes():
    assert config.SESSION_TTL_SECONDS == 2 * 60


def test_load_api_key_reads_environment(monkeypatch):
    monkeypatch.setenv("GOVEE_API_KEY", "test-key-123")
    assert config.load_api_key() == "test-key-123"


def test_load_api_key_raises_when_missing(monkeypatch):
    monkeypatch.delenv("GOVEE_API_KEY", raising=False)
    monkeypatch.setattr("govee_lights.config.load_dotenv", lambda: None)
    with pytest.raises(RuntimeError, match="GOVEE_API_KEY"):
        config.load_api_key()
