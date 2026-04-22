import io
import json
from unittest.mock import patch


def _run_main(argv, stdin_text=""):
    from govee_lights import cli
    with patch("sys.stdin", io.StringIO(stdin_text)):
        return cli.main(argv)


def test_set_state_writes_session_entry_and_pushes_color(tmp_path, monkeypatch):
    from govee_lights import cli, config, state

    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("GOVEE_API_KEY", "test-key")

    calls = []

    class FakeClient:
        def __init__(self, api_key): self.api_key = api_key
        def set_color_rgb(self, sku, device_id, rgb): calls.append(("rgb", sku, device_id, rgb))
        def set_color_temperature(self, sku, device_id, kelvin): calls.append(("kelvin", sku, device_id, kelvin))
        def set_brightness(self, sku, device_id, percent): calls.append(("brightness", sku, device_id, percent))

    monkeypatch.setattr(cli, "GoveeClient", FakeClient)

    payload = json.dumps({"session_id": "sess-A"})
    assert _run_main(["set-state", "permission"], stdin_text=payload) == 0

    color_calls = [c for c in calls if c[0] == "rgb"]
    brightness_calls = [c for c in calls if c[0] == "brightness"]
    assert [c[0] for c in color_calls] == ["rgb", "rgb"]
    assert all(c[3] == 0xFF0000 for c in color_calls)
    assert [c[0] for c in brightness_calls] == ["brightness", "brightness"]
    assert all(c[3] == 100 for c in brightness_calls)

    cache = state.load_cache(tmp_path / "state.json")
    assert cache.current_color == "permission"
    assert cache.sessions["sess-A"].state == "permission"


def test_set_state_short_circuits_when_color_unchanged(tmp_path, monkeypatch):
    from govee_lights import cli, config, state

    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("GOVEE_API_KEY", "test-key")

    state.save_cache(
        state.Cache(
            sessions={"sess-prev": state.SessionEntry(state="working", updated_at="2099-01-01T00:00:00+00:00")},
            current_color="working",
        ),
        tmp_path / "state.json",
    )

    calls = []

    class FakeClient:
        def __init__(self, api_key): pass
        def set_color_rgb(self, *a, **kw): calls.append("rgb")
        def set_color_temperature(self, *a, **kw): calls.append("kelvin")
        def set_brightness(self, *a, **kw): calls.append("brightness")

    monkeypatch.setattr(cli, "GoveeClient", FakeClient)

    payload = json.dumps({"session_id": "sess-B"})
    assert _run_main(["set-state", "working"], stdin_text=payload) == 0

    assert calls == []


def test_set_state_swallows_errors_and_exits_zero(tmp_path, monkeypatch, capsys):
    from govee_lights import cli, config

    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("GOVEE_API_KEY", "test-key")

    class BoomClient:
        def __init__(self, api_key): raise RuntimeError("boom")

    monkeypatch.setattr(cli, "GoveeClient", BoomClient)

    payload = json.dumps({"session_id": "sess-X"})
    rc = _run_main(["set-state", "permission"], stdin_text=payload)
    assert rc == 0
    err = capsys.readouterr().err
    assert "boom" in err


def test_notify_picks_permission_when_message_mentions_permission(tmp_path, monkeypatch):
    from govee_lights import cli, config, state

    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("GOVEE_API_KEY", "test-key")

    rgb_calls = []
    brightness_calls = []

    class FakeClient:
        def __init__(self, api_key): pass
        def set_color_rgb(self, sku, device_id, rgb): rgb_calls.append(rgb)
        def set_color_temperature(self, *a, **kw): rgb_calls.append("kelvin")
        def set_brightness(self, sku, device_id, percent): brightness_calls.append(percent)

    monkeypatch.setattr(cli, "GoveeClient", FakeClient)

    payload = json.dumps({
        "session_id": "sess-N",
        "message": "Claude needs your permission to use Bash",
    })
    assert _run_main(["notify"], stdin_text=payload) == 0
    assert rgb_calls == [0xFF0000, 0xFF0000]
    assert brightness_calls == [100, 100]

    cache = state.load_cache(tmp_path / "state.json")
    assert cache.sessions["sess-N"].state == "permission"


def test_notify_falls_back_to_your_turn_for_non_permission_messages(tmp_path, monkeypatch):
    from govee_lights import cli, config, state

    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("GOVEE_API_KEY", "test-key")

    rgb_calls = []
    brightness_calls = []

    class FakeClient:
        def __init__(self, api_key): pass
        def set_color_rgb(self, sku, device_id, rgb): rgb_calls.append(rgb)
        def set_color_temperature(self, *a, **kw): rgb_calls.append("kelvin")
        def set_brightness(self, sku, device_id, percent): brightness_calls.append(percent)

    monkeypatch.setattr(cli, "GoveeClient", FakeClient)

    payload = json.dumps({
        "session_id": "sess-N",
        "message": "Claude is waiting for your input",
    })
    assert _run_main(["notify"], stdin_text=payload) == 0
    assert rgb_calls == [0x9900FF, 0x9900FF]
    assert brightness_calls == [100, 100]


def test_notify_defaults_to_your_turn_when_message_field_absent(tmp_path, monkeypatch):
    from govee_lights import cli, config, state

    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("GOVEE_API_KEY", "test-key")

    rgb_calls = []
    brightness_calls = []

    class FakeClient:
        def __init__(self, api_key): pass
        def set_color_rgb(self, sku, device_id, rgb): rgb_calls.append(rgb)
        def set_color_temperature(self, *a, **kw): rgb_calls.append("kelvin")
        def set_brightness(self, sku, device_id, percent): brightness_calls.append(percent)

    monkeypatch.setattr(cli, "GoveeClient", FakeClient)

    payload = json.dumps({"session_id": "sess-N"})  # no "message" key
    assert _run_main(["notify"], stdin_text=payload) == 0
    assert rgb_calls == [0x9900FF, 0x9900FF]
    assert brightness_calls == [100, 100]

    cache = state.load_cache(tmp_path / "state.json")
    assert cache.sessions["sess-N"].state == "your-turn"


def test_end_session_removes_entry_and_recomputes_color(tmp_path, monkeypatch):
    from govee_lights import cli, config, state

    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("GOVEE_API_KEY", "test-key")

    state.save_cache(
        state.Cache(
            sessions={
                "A": state.SessionEntry(state="permission", updated_at="2099-01-01T00:00:00+00:00"),
                "B": state.SessionEntry(state="working",    updated_at="2099-01-01T00:00:00+00:00"),
            },
            current_color="permission",
        ),
        tmp_path / "state.json",
    )

    color_calls = []
    brightness_calls = []

    class FakeClient:
        def __init__(self, api_key): pass
        def set_color_rgb(self, sku, device_id, rgb): color_calls.append(("rgb", rgb))
        def set_color_temperature(self, sku, device_id, kelvin): color_calls.append(("kelvin", kelvin))
        def set_brightness(self, sku, device_id, percent): brightness_calls.append(percent)

    monkeypatch.setattr(cli, "GoveeClient", FakeClient)

    payload = json.dumps({"session_id": "A"})
    assert _run_main(["end-session"], stdin_text=payload) == 0

    assert color_calls == [("kelvin", 2700), ("kelvin", 2700)]
    assert brightness_calls == [100, 100]

    cache = state.load_cache(tmp_path / "state.json")
    assert "A" not in cache.sessions
    assert "B" in cache.sessions
    assert cache.current_color == "working"


def test_end_session_is_noop_without_session_id(tmp_path, monkeypatch):
    from govee_lights import cli, config

    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("GOVEE_API_KEY", "test-key")

    class ExplodeClient:
        def __init__(self, api_key): raise AssertionError("should not construct client")

    monkeypatch.setattr(cli, "GoveeClient", ExplodeClient)

    assert _run_main(["end-session"], stdin_text="{}") == 0


def test_list_devices_prints_device_rows(monkeypatch, capsys):
    from govee_lights import cli

    monkeypatch.setenv("GOVEE_API_KEY", "test-key")

    class FakeClient:
        def __init__(self, api_key): pass
        def list_devices(self):
            return [
                {"deviceName": "Office light 1", "sku": "H6076", "device": "AA:BB"},
                {"deviceName": "TV light",       "sku": "H6168", "device": "CC:DD"},
            ]

    monkeypatch.setattr(cli, "GoveeClient", FakeClient)

    assert _run_main(["list-devices"]) == 0
    out = capsys.readouterr().out
    assert "Office light 1" in out and "AA:BB" in out
    assert "TV light" in out and "CC:DD" in out
