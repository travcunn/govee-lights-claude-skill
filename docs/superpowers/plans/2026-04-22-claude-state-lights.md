# Claude Code state lights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Python CLI + Claude Code hooks so the two office Govee H6076 lights reflect Claude's state (working / your-turn / permission) with safe behavior across parallel Claude Code sessions.

**Architecture:** Single Python package (`govee_lights`) with three pure modules (`config`, `client`, `state`) plus a thin `cli` that wires them together. Claude Code hooks invoke a bash wrapper (`hooks/govee-hook`) that calls `uv run govee-lights …`. A JSON cache under `~/.cache/govee-lights/` tracks per-session state behind an `fcntl` file lock; aggregate color is computed by priority (permission > your-turn > working) so parallel sessions don't step on each other.

**Tech Stack:** Python 3.11+, `uv`, `httpx` (Govee HTTP), `python-dotenv` (.env loader), `pytest` (tests), `fcntl` (stdlib file lock), `argparse` (stdlib CLI).

---

## Reference

**Spec:** `docs/superpowers/specs/2026-04-22-claude-state-lights-design.md`

**File structure produced by this plan:**

```
govee-lights/
├── pyproject.toml
├── .env.example
├── .gitignore
├── README.md
├── src/govee_lights/
│   ├── __init__.py
│   ├── cli.py
│   ├── client.py
│   ├── config.py
│   └── state.py
├── hooks/
│   └── govee-hook
└── tests/
    ├── __init__.py
    ├── test_client.py
    ├── test_config.py
    ├── test_state.py
    └── test_cli.py
```

**Shared type vocabulary (used across tasks, keep identical):**

- `State = Literal["working", "your-turn", "permission"]`
- `SessionEntry` — dataclass with fields `state: str`, `updated_at: str` (ISO 8601 UTC)
- `Cache` — dataclass with fields `sessions: dict[str, SessionEntry]`, `current_color: str`; methods `aggregate_state()`, `prune_stale(now, ttl_seconds)`, `to_dict()`, `from_dict()`
- Priority map: `{"working": 1, "your-turn": 2, "permission": 3}`
- `STATE_TO_PAYLOAD: dict[str, tuple[str, int]]` where the tuple is `(instance, value)` matching Govee capability instances `"colorRgb"` or `"colorTemperatureK"`

**Commands used throughout:**

- Install / sync deps: `uv sync`
- Run tests: `uv run pytest -v`
- Run single test: `uv run pytest tests/test_state.py::test_name -v`

---

## Task 1: Scaffold uv project

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/govee_lights/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "govee-lights"
version = "0.1.0"
description = "Claude Code state indicator via Govee office lights"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "python-dotenv>=1.0",
]

[project.scripts]
govee-lights = "govee_lights.cli:main"

[dependency-groups]
dev = [
    "pytest>=8.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/govee_lights"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write `.gitignore`**

```
.env
.venv/
__pycache__/
*.pyc
.pytest_cache/
dist/
build/
*.egg-info/
```

- [ ] **Step 3: Write `.env.example`**

```
# Get this from Govee Home → Profile → About Us → Apply for API Key
GOVEE_API_KEY=your-api-key-here
```

- [ ] **Step 4: Create empty package and tests `__init__.py`**

```python
# src/govee_lights/__init__.py
```

```python
# tests/__init__.py
```

- [ ] **Step 5: Sync deps and verify**

Run: `uv sync`
Expected: Creates `.venv/`, installs httpx, python-dotenv, pytest; no errors.

Run: `uv run pytest`
Expected: `no tests ran in 0.XXs` (success, empty suite).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore .env.example src/ tests/
git commit -m "feat: scaffold uv project for govee-lights"
```

---

## Task 2: Config module (device list, colors, API key loader)

**Files:**
- Create: `src/govee_lights/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
import os
from pathlib import Path

import pytest

from govee_lights import config


def test_target_devices_are_the_two_office_lights():
    names = [d.name for d in config.TARGET_DEVICES]
    assert names == ["Office light 1", "Office light 2"]
    for d in config.TARGET_DEVICES:
        assert d.sku == "H6076"


def test_state_payload_map_covers_all_three_states():
    assert set(config.STATE_TO_PAYLOAD) == {"working", "your-turn", "permission"}
    # working uses color temperature, others use RGB
    assert config.STATE_TO_PAYLOAD["working"] == ("colorTemperatureK", 2700)
    assert config.STATE_TO_PAYLOAD["your-turn"] == ("colorRgb", 0xFFCC00)
    assert config.STATE_TO_PAYLOAD["permission"] == ("colorRgb", 0xFF0000)


def test_priority_orders_permission_highest():
    assert config.PRIORITY["permission"] > config.PRIORITY["your-turn"]
    assert config.PRIORITY["your-turn"] > config.PRIORITY["working"]


def test_cache_path_is_under_user_cache_dir():
    assert config.CACHE_PATH == Path.home() / ".cache" / "govee-lights" / "state.json"


def test_session_ttl_is_30_minutes():
    assert config.SESSION_TTL_SECONDS == 30 * 60


def test_load_api_key_reads_environment(monkeypatch):
    monkeypatch.setenv("GOVEE_API_KEY", "test-key-123")
    assert config.load_api_key() == "test-key-123"


def test_load_api_key_raises_when_missing(monkeypatch, tmp_path, chdir):
    monkeypatch.delenv("GOVEE_API_KEY", raising=False)
    chdir(tmp_path)  # avoid picking up repo .env
    with pytest.raises(RuntimeError, match="GOVEE_API_KEY"):
        config.load_api_key()
```

- [ ] **Step 2: Add the `chdir` fixture**

Create `tests/conftest.py`:

```python
import os
from pathlib import Path

import pytest


@pytest.fixture
def chdir():
    """Change working directory for the duration of a test."""
    original = Path.cwd()

    def _chdir(path: Path) -> None:
        os.chdir(path)

    yield _chdir
    os.chdir(original)
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: All tests fail with `ModuleNotFoundError` or `AttributeError` on `config.*`.

- [ ] **Step 4: Implement `config.py`**

```python
# src/govee_lights/config.py
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


def load_api_key() -> str:
    load_dotenv()
    key = os.environ.get("GOVEE_API_KEY")
    if not key:
        raise RuntimeError("GOVEE_API_KEY not set; put it in .env or your shell env")
    return key
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add src/govee_lights/config.py tests/test_config.py tests/conftest.py
git commit -m "feat(config): device list, color palette, api key loader"
```

---

## Task 3: Govee HTTP client (list_devices + color control)

**Files:**
- Create: `src/govee_lights/client.py`
- Create: `tests/test_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_client.py
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
    # requestId must be a non-empty string (uuid)
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


def test_non_2xx_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": 401, "msg": "invalid key"})

    client = _mock_client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        client.list_devices()
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_client.py -v`
Expected: All fail with `ModuleNotFoundError: No module named 'govee_lights.client'`.

- [ ] **Step 3: Implement `client.py`**

```python
# src/govee_lights/client.py
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
        self._control(sku, device_id, "colorRgb", rgb)

    def set_color_temperature(self, sku: str, device_id: str, kelvin: int) -> None:
        self._control(sku, device_id, "colorTemperatureK", kelvin)

    def _control(self, sku: str, device_id: str, instance: str, value: int) -> None:
        payload = {
            "requestId": str(uuid.uuid4()),
            "payload": {
                "sku": sku,
                "device": device_id,
                "capability": {
                    "type": "devices.capabilities.color_setting",
                    "instance": instance,
                    "value": value,
                },
            },
        }
        r = self.http.post("/device/control", json=payload)
        r.raise_for_status()
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_client.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/govee_lights/client.py tests/test_client.py
git commit -m "feat(client): govee http client with list/set color/set temp"
```

---

## Task 4: State cache — data model, load, save (atomic)

**Files:**
- Create: `src/govee_lights/state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_state.py
import json
from datetime import datetime, timezone

import pytest

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
    # Only the final file should remain; no stray .state.* tempfiles
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "state.json"]
    assert leftovers == []
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_state.py -v`
Expected: All fail with `ModuleNotFoundError: No module named 'govee_lights.state'`.

- [ ] **Step 3: Implement `state.py` (first slice: data model + load/save)**

Note: `load_cache` and `save_cache` take `Path | None` and resolve the default *at call time* via `config.CACHE_PATH`. This matters because default arguments are evaluated once at function-def time, so a frozen default would ignore monkeypatching of `config.CACHE_PATH` during tests.

```python
# src/govee_lights/state.py
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config


@dataclass
class SessionEntry:
    state: str
    updated_at: str  # ISO 8601 UTC


@dataclass
class Cache:
    sessions: dict[str, SessionEntry] = field(default_factory=dict)
    current_color: str = "working"

    def to_dict(self) -> dict:
        return {
            "sessions": {sid: asdict(e) for sid, e in self.sessions.items()},
            "current_color": self.current_color,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Cache":
        sessions = {
            sid: SessionEntry(**entry)
            for sid, entry in (data.get("sessions") or {}).items()
        }
        return cls(
            sessions=sessions,
            current_color=data.get("current_color", "working"),
        )


def load_cache(path: Path | None = None) -> Cache:
    if path is None:
        path = config.CACHE_PATH
    if not path.exists():
        return Cache()
    try:
        with path.open() as f:
            data = json.load(f)
        return Cache.from_dict(data)
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return Cache()


def save_cache(cache: Cache, path: Path | None = None) -> None:
    if path is None:
        path = config.CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".state.", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(cache.to_dict(), f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_state.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/govee_lights/state.py tests/test_state.py
git commit -m "feat(state): cache data model with atomic load/save"
```

---

## Task 5: State cache — aggregate_state and prune_stale

**Files:**
- Modify: `src/govee_lights/state.py` (add methods to `Cache`)
- Modify: `tests/test_state.py` (append tests)

- [ ] **Step 1: Append failing tests to `tests/test_state.py`**

```python
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
```

- [ ] **Step 2: Run tests, verify the new ones fail**

Run: `uv run pytest tests/test_state.py -v`
Expected: Previous 6 still pass; new 5 fail with `AttributeError` on `aggregate_state`/`prune_stale`.

- [ ] **Step 3: Add methods to `Cache` in `state.py`**

Add this import at the top (keep the existing `from . import config`):

```python
from datetime import datetime
```

Add these methods inside the `Cache` dataclass (before `to_dict`):

```python
    def aggregate_state(self) -> str:
        if not self.sessions:
            return "working"
        return max(
            (entry.state for entry in self.sessions.values()),
            key=lambda s: config.PRIORITY[s],
        )

    def prune_stale(self, now: datetime, ttl_seconds: int | None = None) -> None:
        if ttl_seconds is None:
            ttl_seconds = config.SESSION_TTL_SECONDS
        cutoff = now.timestamp() - ttl_seconds
        self.sessions = {
            sid: entry
            for sid, entry in self.sessions.items()
            if datetime.fromisoformat(entry.updated_at).timestamp() >= cutoff
        }
```

- [ ] **Step 4: Run tests, verify all pass**

Run: `uv run pytest tests/test_state.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/govee_lights/state.py tests/test_state.py
git commit -m "feat(state): priority aggregation and TTL pruning"
```

---

## Task 6: State cache — `locked_cache` context manager (flock)

**Files:**
- Modify: `src/govee_lights/state.py` (add `locked_cache`)
- Modify: `tests/test_state.py` (append tests)

- [ ] **Step 1: Append failing tests**

```python
import multiprocessing
import time


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
    # Separate-process helper; runs via multiprocessing.
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
    # Both writers' entries must be present: if the lock worked, p2 read p1's write.
    assert "first" in final.sessions
    assert "second" in final.sessions
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_state.py -v`
Expected: new tests fail with `ImportError` on `locked_cache`.

- [ ] **Step 3: Add `locked_cache` to `state.py`**

Add imports at top of `state.py`:

```python
import fcntl
from contextlib import contextmanager
from typing import Iterator
```

Add at the bottom of the file (note: resolves `config.CACHE_PATH` at call time, same reason as `load_cache`):

```python
@contextmanager
def locked_cache(path: Path | None = None) -> Iterator[Cache]:
    if path is None:
        path = config.CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(".lock")
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            cache = load_cache(path)
            yield cache
            save_cache(cache, path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
```

- [ ] **Step 4: Run tests, verify all pass**

Run: `uv run pytest tests/test_state.py -v`
Expected: 13 passed (the concurrent test takes ~0.5s).

- [ ] **Step 5: Commit**

```bash
git add src/govee_lights/state.py tests/test_state.py
git commit -m "feat(state): locked_cache context manager for concurrent sessions"
```

---

## Task 7: CLI — `set-state` subcommand (orchestrates state + client)

**Files:**
- Create: `src/govee_lights/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
import io
import json
from unittest.mock import patch

import pytest


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

    # Both office devices received an RGB call
    assert [c[0] for c in calls] == ["rgb", "rgb"]
    assert all(c[3] == 0xFF0000 for c in calls)

    # Cache was updated
    cache = state.load_cache(tmp_path / "state.json")
    assert cache.current_color == "permission"
    assert cache.sessions["sess-A"].state == "permission"


def test_set_state_short_circuits_when_color_unchanged(tmp_path, monkeypatch):
    from govee_lights import cli, config, state

    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("GOVEE_API_KEY", "test-key")

    # Pre-seed cache: already working, a previous session contributed working
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

    # No API calls because aggregate is still "working"
    assert calls == []


def test_set_state_swallows_errors_and_exits_zero(tmp_path, monkeypatch, capsys):
    from govee_lights import cli, config, state

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
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All fail (module `govee_lights.cli` does not exist).

- [ ] **Step 3: Implement `cli.py`**

```python
# src/govee_lights/cli.py
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from .client import GoveeClient
from .config import STATE_TO_PAYLOAD, TARGET_DEVICES, load_api_key
from .state import SessionEntry, locked_cache


def _push_color(state: str) -> None:
    instance, value = STATE_TO_PAYLOAD[state]
    client = GoveeClient(api_key=load_api_key())
    for device in TARGET_DEVICES:
        if instance == "colorRgb":
            client.set_color_rgb(device.sku, device.device_id, value)
        else:
            client.set_color_temperature(device.sku, device.device_id, value)


def _apply_state(state: str, session_id: str) -> None:
    now = datetime.now(timezone.utc)
    with locked_cache() as cache:
        cache.sessions[session_id] = SessionEntry(state=state, updated_at=now.isoformat())
        cache.prune_stale(now)
        aggregate = cache.aggregate_state()
        if aggregate == cache.current_color:
            return
        _push_color(aggregate)
        cache.current_color = aggregate


def _remove_session(session_id: str) -> None:
    now = datetime.now(timezone.utc)
    with locked_cache() as cache:
        cache.sessions.pop(session_id, None)
        cache.prune_stale(now)
        aggregate = cache.aggregate_state()
        if aggregate == cache.current_color:
            return
        _push_color(aggregate)
        cache.current_color = aggregate


def _read_hook_payload() -> dict:
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def cmd_set_state(args: argparse.Namespace) -> None:
    payload = _read_hook_payload()
    session_id = payload.get("session_id", "manual")
    _apply_state(args.state, session_id)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="govee-lights")
    sub = p.add_subparsers(dest="command", required=True)

    ss = sub.add_parser("set-state", help="Set current session to a state")
    ss.add_argument("state", choices=["working", "your-turn", "permission"])
    ss.set_defaults(func=cmd_set_state)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except Exception as exc:
        print(f"govee-lights: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: All tests (config, client, state, cli) pass.

- [ ] **Step 6: Commit**

```bash
git add src/govee_lights/cli.py tests/test_cli.py
git commit -m "feat(cli): set-state subcommand with priority-aware orchestration"
```

---

## Task 8: CLI — `notify` subcommand (parses Claude message)

**Files:**
- Modify: `src/govee_lights/cli.py`
- Modify: `tests/test_cli.py` (append)

- [ ] **Step 1: Append failing tests**

```python
def test_notify_picks_permission_when_message_mentions_permission(tmp_path, monkeypatch):
    from govee_lights import cli, config, state

    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("GOVEE_API_KEY", "test-key")

    calls = []

    class FakeClient:
        def __init__(self, api_key): pass
        def set_color_rgb(self, sku, device_id, rgb): calls.append(rgb)
        def set_color_temperature(self, *a, **kw): calls.append("kelvin")

    monkeypatch.setattr(cli, "GoveeClient", FakeClient)

    payload = json.dumps({
        "session_id": "sess-N",
        "message": "Claude needs your permission to use Bash",
    })
    assert _run_main(["notify"], stdin_text=payload) == 0
    assert calls == [0xFF0000, 0xFF0000]  # red, both devices

    cache = state.load_cache(tmp_path / "state.json")
    assert cache.sessions["sess-N"].state == "permission"


def test_notify_falls_back_to_your_turn_for_non_permission_messages(tmp_path, monkeypatch):
    from govee_lights import cli, config, state

    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("GOVEE_API_KEY", "test-key")

    calls = []

    class FakeClient:
        def __init__(self, api_key): pass
        def set_color_rgb(self, sku, device_id, rgb): calls.append(rgb)
        def set_color_temperature(self, *a, **kw): calls.append("kelvin")

    monkeypatch.setattr(cli, "GoveeClient", FakeClient)

    payload = json.dumps({
        "session_id": "sess-N",
        "message": "Claude is waiting for your input",
    })
    assert _run_main(["notify"], stdin_text=payload) == 0
    assert calls == [0xFFCC00, 0xFFCC00]  # yellow, both devices
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: new tests fail with `argparse` error ("invalid choice: 'notify'" or similar).

- [ ] **Step 3: Add `cmd_notify` and register subcommand**

Add this function to `cli.py`:

```python
def cmd_notify(args: argparse.Namespace) -> None:
    payload = _read_hook_payload()
    session_id = payload.get("session_id", "manual")
    message = (payload.get("message") or "").lower()
    state = "permission" if "permission" in message else "your-turn"
    _apply_state(state, session_id)
```

Add to `build_parser()` after `set-state` registration:

```python
    nt = sub.add_parser("notify", help="Parse Claude Notification hook payload")
    nt.set_defaults(func=cmd_notify)
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/govee_lights/cli.py tests/test_cli.py
git commit -m "feat(cli): notify subcommand dispatches on message content"
```

---

## Task 9: CLI — `end-session` subcommand

**Files:**
- Modify: `src/govee_lights/cli.py`
- Modify: `tests/test_cli.py` (append)

- [ ] **Step 1: Append failing tests**

```python
def test_end_session_removes_entry_and_recomputes_color(tmp_path, monkeypatch):
    from govee_lights import cli, config, state

    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("GOVEE_API_KEY", "test-key")

    # Seed: session A is in permission (red); session B is working
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

    calls = []

    class FakeClient:
        def __init__(self, api_key): pass
        def set_color_rgb(self, sku, device_id, rgb): calls.append(("rgb", rgb))
        def set_color_temperature(self, sku, device_id, kelvin): calls.append(("kelvin", kelvin))

    monkeypatch.setattr(cli, "GoveeClient", FakeClient)

    payload = json.dumps({"session_id": "A"})
    assert _run_main(["end-session"], stdin_text=payload) == 0

    # With A removed, aggregate drops to "working" → kelvin push for both devices
    assert calls == [("kelvin", 2700), ("kelvin", 2700)]

    cache = state.load_cache(tmp_path / "state.json")
    assert "A" not in cache.sessions
    assert "B" in cache.sessions
    assert cache.current_color == "working"


def test_end_session_is_noop_without_session_id(tmp_path, monkeypatch):
    from govee_lights import cli, config, state

    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "state.json")
    monkeypatch.setenv("GOVEE_API_KEY", "test-key")

    class ExplodeClient:
        def __init__(self, api_key): raise AssertionError("should not construct client")

    monkeypatch.setattr(cli, "GoveeClient", ExplodeClient)

    # Empty payload → session_id missing → early return
    assert _run_main(["end-session"], stdin_text="{}") == 0
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: new tests fail with argparse error on "end-session".

- [ ] **Step 3: Add `cmd_end_session` and register**

Add to `cli.py`:

```python
def cmd_end_session(args: argparse.Namespace) -> None:
    payload = _read_hook_payload()
    session_id = payload.get("session_id")
    if not session_id:
        return
    _remove_session(session_id)
```

Add to `build_parser()`:

```python
    es = sub.add_parser("end-session", help="Drop this session from the aggregate")
    es.set_defaults(func=cmd_end_session)
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/govee_lights/cli.py tests/test_cli.py
git commit -m "feat(cli): end-session subcommand removes entry and recomputes"
```

---

## Task 10: CLI — `list-devices` subcommand

**Files:**
- Modify: `src/govee_lights/cli.py`
- Modify: `tests/test_cli.py` (append)

- [ ] **Step 1: Append failing test**

```python
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
```

- [ ] **Step 2: Run test, verify it fails**

Run: `uv run pytest tests/test_cli.py::test_list_devices_prints_device_rows -v`
Expected: argparse error on "list-devices".

- [ ] **Step 3: Add `cmd_list_devices` and register**

Add to `cli.py`:

```python
def cmd_list_devices(args: argparse.Namespace) -> None:
    client = GoveeClient(api_key=load_api_key())
    for d in client.list_devices():
        name = d.get("deviceName", "?")
        print(f"{name:<25} sku={d['sku']:<18} device={d['device']}")
```

Add to `build_parser()`:

```python
    ld = sub.add_parser("list-devices", help="Print Govee devices on this account")
    ld.set_defaults(func=cmd_list_devices)
```

- [ ] **Step 4: Run tests, verify all pass**

Run: `uv run pytest -v`
Expected: All tests pass (config, client, state, cli combined).

- [ ] **Step 5: Commit**

```bash
git add src/govee_lights/cli.py tests/test_cli.py
git commit -m "feat(cli): list-devices subcommand for quick inspection"
```

---

## Task 11: hooks/govee-hook bash wrapper

**Files:**
- Create: `hooks/govee-hook`

- [ ] **Step 1: Create the wrapper script**

Create `hooks/govee-hook`:

```bash
#!/usr/bin/env bash
# Thin wrapper so Claude Code hooks can invoke govee-lights from anywhere.
# Resolves the repo root via the script's own location.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
exec uv --directory "$REPO_ROOT" run govee-lights "$@"
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x hooks/govee-hook`

- [ ] **Step 3: Smoke test it**

Prereq: user has put a real key in `.env`. If not, skip the real-API check and only verify `--help` works.

Run: `./hooks/govee-hook --help`
Expected: Prints argparse usage with subcommands `set-state`, `notify`, `end-session`, `list-devices`.

Run (only if `.env` is populated): `./hooks/govee-hook set-state permission`
Expected: Lights turn red, exit 0.

Run (cleanup): `./hooks/govee-hook set-state working`
Expected: Lights return to warm white.

- [ ] **Step 4: Commit**

```bash
git add hooks/govee-hook
git commit -m "feat(hooks): bash wrapper script for claude code hooks"
```

---

## Task 12: README with installation and hook-wiring instructions

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# govee-lights

Ambient Claude Code state indicator using two Govee H6076 office lights.

- **Warm white** — Claude is working (or no active session)
- **Yellow** — Claude finished, waiting on your input
- **Red** — Claude needs permission approval

Parallel Claude Code sessions are handled via per-session priority aggregation: the loudest state across any active session wins.

## Install

```bash
uv sync
cp .env.example .env
# Edit .env and paste your Govee API key
```

## Verify

```bash
uv run govee-lights list-devices        # should print your devices
uv run govee-lights set-state permission # office lights → red
uv run govee-lights set-state working    # office lights → warm white
```

## Wire up Claude Code hooks

Add these to `~/.claude/settings.json` (replace `<REPO_PATH>` with the absolute path to this repo):

```json
{
  "hooks": {
    "Notification":     [{ "hooks": [{ "type": "command", "command": "<REPO_PATH>/hooks/govee-hook notify" }] }],
    "Stop":             [{ "hooks": [{ "type": "command", "command": "<REPO_PATH>/hooks/govee-hook set-state your-turn" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "<REPO_PATH>/hooks/govee-hook set-state working" }] }],
    "PreToolUse":       [{ "hooks": [{ "type": "command", "command": "<REPO_PATH>/hooks/govee-hook set-state working" }] }],
    "SessionStart":     [{ "hooks": [{ "type": "command", "command": "<REPO_PATH>/hooks/govee-hook set-state working" }] }],
    "SessionEnd":       [{ "hooks": [{ "type": "command", "command": "<REPO_PATH>/hooks/govee-hook end-session" }] }]
  }
}
```

## Tests

```bash
uv run pytest -v
```

## Notes

- API key lives in `.env` (gitignored). Never commit it.
- Stale session entries in the local cache self-expire after 30 minutes.
- Hooks always exit 0 so Govee failures never block Claude Code.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with install, verify, and hook-wiring instructions"
```

---

## Task 13: Final end-to-end smoke test

This is a manual verification task. No code changes, just make sure the thing works in real conditions.

- [ ] **Step 1: Ensure `.env` contains the real API key**

Check: `grep GOVEE_API_KEY .env` and confirm it's the real key, not `your-api-key-here`.

- [ ] **Step 2: Full test suite**

Run: `uv run pytest -v`
Expected: all passing, no skipped tests except intentional ones.

- [ ] **Step 3: CLI smoke test (hits real Govee)**

Run: `uv run govee-lights set-state permission`
Expected: both office lights turn red within ~1 second.

Run: `uv run govee-lights set-state your-turn`
Expected: both office lights turn yellow.

Run: `uv run govee-lights set-state working`
Expected: both office lights turn warm white (2700K).

- [ ] **Step 4: Inspect cache**

Run: `cat ~/.cache/govee-lights/state.json | python -m json.tool`
Expected: shows a `manual` session entry and `current_color: "working"`.

- [ ] **Step 5: Install hooks**

Follow the README section "Wire up Claude Code hooks" and edit `~/.claude/settings.json`. (Use `<REPO_PATH> = /Users/tcunningham/govee-lights`.)

- [ ] **Step 6: Live Claude Code verification**

Start a new Claude Code session in any repo. Expected observations:
- `SessionStart` fires → lights stay/become warm white.
- Ask Claude to do something that needs permission (e.g. run a git write command in a sandbox). → lights go red.
- Approve the permission. → on next `PreToolUse` lights return to warm white.
- Claude finishes its response. → lights go yellow.
- Send another prompt. → lights return to warm white.
- Exit Claude. → `SessionEnd` fires, cache entry for that session is removed.

- [ ] **Step 7: No commit needed** — smoke test only.

---

## Self-review (done at plan-write time)

- **Spec coverage:** ✅ States (working/your-turn/permission) → Tasks 2, 7, 8. Device list → Task 2. Hook wiring → Tasks 11, 12. Per-session priority + TTL → Tasks 5, 6. Flock → Task 6. Short-circuit on unchanged state → Task 7. `end-session` → Task 9. `list-devices` → Task 10. Error swallowing → Task 7 (test + implementation). `.env` + `.env.example` + gitignore → Task 1.
- **Placeholder scan:** none; every code step shows the real code.
- **Type consistency:** `Cache`, `SessionEntry`, `aggregate_state`, `prune_stale`, `locked_cache`, `load_cache`, `save_cache`, `STATE_TO_PAYLOAD`, `TARGET_DEVICES`, `PRIORITY` — names identical across tasks. State strings (`"working"`, `"your-turn"`, `"permission"`) spelled consistently.
