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
