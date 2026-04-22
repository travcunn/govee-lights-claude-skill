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

    monkeypatch.setattr(cli, "GoveeClient", FakeClient)

    payload = json.dumps({"session_id": "sess-A"})
    assert _run_main(["set-state", "permission"], stdin_text=payload) == 0

    assert [c[0] for c in calls] == ["rgb", "rgb"]
    assert all(c[3] == 0xFF0000 for c in calls)

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
