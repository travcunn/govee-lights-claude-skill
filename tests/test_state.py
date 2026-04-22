import multiprocessing
import time

import pytest
from datetime import datetime, timezone

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


def test_aggregate_state_returns_working_when_no_sessions():
    assert Cache().aggregate_state() == "working"


def test_aggregate_state_picks_highest_priority():
    c = Cache(sessions={
        "a": SessionEntry(state="working", updated_at="2026-04-22T00:00:00+00:00"),
        "b": SessionEntry(state="your-turn", updated_at="2026-04-22T00:00:00+00:00"),
        "c": SessionEntry(state="permission", updated_at="2026-04-22T00:00:00+00:00"),
    })
    assert c.aggregate_state() == "permission"


def test_aggregate_state_your_turn_beats_working():
    c = Cache(sessions={
        "a": SessionEntry(state="working", updated_at="2026-04-22T00:00:00+00:00"),
        "b": SessionEntry(state="your-turn", updated_at="2026-04-22T00:00:00+00:00"),
    })
    assert c.aggregate_state() == "your-turn"


def test_prune_stale_removes_entries_older_than_ttl():
    now = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)
    c = Cache(sessions={
        "fresh": SessionEntry(state="working", updated_at="2026-04-22T11:59:00+00:00"),
        "stale": SessionEntry(state="permission", updated_at="2026-04-22T11:00:00+00:00"),
    })
    c.prune_stale(now, ttl_seconds=30 * 60)
    assert list(c.sessions) == ["fresh"]


def test_prune_stale_keeps_entries_exactly_at_cutoff():
    now = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)
    c = Cache(sessions={
        "edge": SessionEntry(state="working", updated_at="2026-04-22T11:30:00+00:00"),
    })
    c.prune_stale(now, ttl_seconds=30 * 60)
    assert "edge" in c.sessions


def test_prune_stale_rejects_naive_datetime():
    naive = datetime(2026, 4, 22, 12, 0, 0)  # no tzinfo
    c = Cache()
    with pytest.raises(ValueError, match="timezone-aware"):
        c.prune_stale(naive)


def test_prune_stale_falls_back_to_config_session_ttl(monkeypatch):
    from govee_lights import config
    monkeypatch.setattr(config, "SESSION_TTL_SECONDS", 10)  # tiny TTL
    now = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)
    c = Cache(sessions={
        "stale":  SessionEntry(state="working", updated_at="2026-04-22T11:59:00+00:00"),  # 60s old > 10s TTL
        "fresh":  SessionEntry(state="working", updated_at="2026-04-22T11:59:55+00:00"),  # 5s old < 10s TTL
    })
    c.prune_stale(now)  # no explicit ttl, should use config.SESSION_TTL_SECONDS
    assert list(c.sessions) == ["fresh"]


def test_locked_cache_yields_cache_and_persists_changes(tmp_path):
    from govee_lights.state import locked_cache
    path = tmp_path / "state.json"

    with locked_cache(path) as cache:
        cache.sessions["s1"] = SessionEntry(state="permission", updated_at="2026-04-22T00:00:00+00:00")
        cache.current_color = "permission"

    reloaded = load_cache(path)
    assert reloaded.current_color == "permission"
    assert "s1" in reloaded.sessions


def _hold_lock_and_write(path_str, marker_str, hold_seconds):
    from pathlib import Path as _Path
    from govee_lights.state import locked_cache, SessionEntry
    with locked_cache(_Path(path_str)) as cache:
        cache.sessions[marker_str] = SessionEntry(state="working", updated_at="2026-04-22T00:00:00+00:00")
        time.sleep(hold_seconds)


def test_locked_cache_serializes_concurrent_writers(tmp_path):
    path = tmp_path / "state.json"

    p1 = multiprocessing.Process(target=_hold_lock_and_write, args=(str(path), "first", 0.4))
    p2 = multiprocessing.Process(target=_hold_lock_and_write, args=(str(path), "second", 0.0))

    p1.start()
    time.sleep(0.05)  # ensure p1 acquires first
    p2.start()
    p1.join(timeout=5)
    p2.join(timeout=5)

    assert p1.exitcode == 0 and p2.exitcode == 0
    final = load_cache(path)
    assert "first" in final.sessions
    assert "second" in final.sessions
