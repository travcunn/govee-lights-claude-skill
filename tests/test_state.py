from govee_lights.state import Cache, SessionEntry, load_cache, save_cache


def test_cache_from_empty_dict():
    c = Cache.from_dict({})
    assert c.sessions == {}
    assert c.current_color == "working"


def test_cache_round_trip_via_to_and_from_dict():
    original = Cache(
        sessions={"sid-1": SessionEntry(state="permission", updated_at="2026-04-22T00:00:00+00:00")},
        current_color="permission",
    )
    restored = Cache.from_dict(original.to_dict())
    assert restored == original


def test_load_cache_returns_empty_cache_when_file_missing(tmp_path):
    cache = load_cache(tmp_path / "does-not-exist.json")
    assert cache == Cache()


def test_load_cache_returns_empty_cache_when_file_corrupt(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("this is not json")
    assert load_cache(path) == Cache()


def test_save_cache_round_trips(tmp_path):
    path = tmp_path / "nested" / "state.json"
    cache = Cache(
        sessions={"sid-1": SessionEntry(state="your-turn", updated_at="2026-04-22T00:00:00+00:00")},
        current_color="your-turn",
    )
    save_cache(cache, path)
    assert load_cache(path) == cache


def test_save_cache_is_atomic_no_tempfile_left_behind(tmp_path):
    path = tmp_path / "state.json"
    save_cache(Cache(), path)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "state.json"]
    assert leftovers == []
