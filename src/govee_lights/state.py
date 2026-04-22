from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

from . import config


@dataclass
class SessionEntry:
    state: str
    updated_at: str  # ISO 8601 UTC


@dataclass
class Cache:
    sessions: dict[str, SessionEntry] = field(default_factory=dict)
    current_color: str = "working"

    def aggregate_state(self) -> str:
        if not self.sessions:
            return "working"
        return max(
            (entry.state for entry in self.sessions.values()),
            key=lambda s: config.PRIORITY[s],
        )

    def prune_stale(self, now: datetime, ttl_seconds: int | None = None) -> None:
        if now.tzinfo is None:
            raise ValueError("prune_stale: 'now' must be a timezone-aware datetime")
        if ttl_seconds is None:
            ttl_seconds = config.SESSION_TTL_SECONDS
        cutoff = now.timestamp() - ttl_seconds
        self.sessions = {
            sid: entry
            for sid, entry in self.sessions.items()
            if datetime.fromisoformat(entry.updated_at).timestamp() >= cutoff
        }

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
