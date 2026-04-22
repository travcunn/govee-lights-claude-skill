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
            # Early return still saves the cache via locked_cache's __exit__; skips Govee push only.
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
            # Same as _apply_state: locked_cache saves on exit, we just skip the Govee push.
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


def cmd_notify(args: argparse.Namespace) -> None:
    payload = _read_hook_payload()
    session_id = payload.get("session_id", "manual")
    message = (payload.get("message") or "").lower()
    resolved_state = "permission" if "permission" in message else "your-turn"
    _apply_state(resolved_state, session_id)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="govee-lights")
    sub = p.add_subparsers(dest="command", required=True)

    ss = sub.add_parser("set-state", help="Set current session to a state")
    ss.add_argument("state", choices=["working", "your-turn", "permission"])
    ss.set_defaults(func=cmd_set_state)

    nt = sub.add_parser("notify", help="Parse Claude Notification hook payload")
    nt.set_defaults(func=cmd_notify)

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
