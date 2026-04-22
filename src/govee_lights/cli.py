from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

from .client import GoveeClient
from .config import (
    BRIGHTNESS_PERCENT,
    FLASH_DURATION_SECONDS,
    FLASH_RGB,
    STATE_TO_PAYLOAD,
    TARGET_DEVICES,
    load_api_key,
)
from .state import SessionEntry, locked_cache


def _push_device(client: GoveeClient, device, instance: str, value: int) -> None:
    if instance == "colorRgb":
        client.set_color_rgb(device.sku, device.device_id, value)
    else:
        client.set_color_temperature(device.sku, device.device_id, value)
    client.set_brightness(device.sku, device.device_id, BRIGHTNESS_PERCENT)


def _push_all(client: GoveeClient, instance: str, value: int) -> None:
    with ThreadPoolExecutor(max_workers=len(TARGET_DEVICES)) as pool:
        futures = [
            pool.submit(_push_device, client, device, instance, value)
            for device in TARGET_DEVICES
        ]
        for f in futures:
            f.result()


def _push_color(state: str) -> None:
    instance, value = STATE_TO_PAYLOAD[state]
    client = GoveeClient(api_key=load_api_key())
    _push_all(client, instance, value)


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


def _do_flash(session_id: str) -> None:
    """Reset this session to working, flash green, then restore the warm sticky state.

    If permission is active at either the start or the end of the flash, the
    flash defers to red: we do not override a pending-permission signal.
    """
    with locked_cache() as cache:
        now = datetime.now(timezone.utc)
        cache.sessions[session_id] = SessionEntry(state="working", updated_at=now.isoformat())
        cache.prune_stale(now)
        if cache.aggregate_state() == "permission":
            return

    client = GoveeClient(api_key=load_api_key())
    _push_all(client, "colorRgb", FLASH_RGB)
    time.sleep(FLASH_DURATION_SECONDS)

    with locked_cache() as cache:
        now = datetime.now(timezone.utc)
        cache.prune_stale(now)
        if cache.aggregate_state() == "permission":
            # Red arrived during the flash; its handler already pushed. Leave it.
            return
        instance, value = STATE_TO_PAYLOAD["working"]
        _push_all(client, instance, value)
        cache.current_color = "working"


def _detach(target: Callable[[], None]) -> None:
    """Double-fork so the hook returns immediately while `target` runs daemonized."""
    pid = os.fork()
    if pid > 0:
        os.waitpid(pid, 0)
        return
    try:
        os.setsid()
        if os.fork() > 0:
            os._exit(0)
    except OSError:
        os._exit(1)
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    null_fd = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        try:
            os.dup2(null_fd, fd)
        except OSError:
            pass
    if null_fd > 2:
        os.close(null_fd)
    try:
        target()
    except Exception:
        pass
    os._exit(0)


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
    if "permission" in message:
        _apply_state("permission", session_id)
    else:
        _detach(lambda: _do_flash(session_id))


def cmd_task_done(args: argparse.Namespace) -> None:
    payload = _read_hook_payload()
    session_id = payload.get("session_id", "manual")
    _detach(lambda: _do_flash(session_id))


def cmd_end_session(args: argparse.Namespace) -> None:
    payload = _read_hook_payload()
    session_id = payload.get("session_id")
    if not session_id:
        return
    _remove_session(session_id)


def cmd_list_devices(args: argparse.Namespace) -> None:
    client = GoveeClient(api_key=load_api_key())
    for d in client.list_devices():
        name = d.get("deviceName", "?")
        print(f"{name:<25} sku={d['sku']:<18} device={d['device']}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="govee-lights")
    sub = p.add_subparsers(dest="command", required=True)

    ss = sub.add_parser("set-state", help="Set current session to a sticky state")
    ss.add_argument("state", choices=["working", "permission"])
    ss.set_defaults(func=cmd_set_state)

    nt = sub.add_parser("notify", help="Handle Notification hook: permission → red, else green flash")
    nt.set_defaults(func=cmd_notify)

    td = sub.add_parser("task-done", help="Flash green briefly then return to warm (Stop hook)")
    td.set_defaults(func=cmd_task_done)

    es = sub.add_parser("end-session", help="Drop this session from the aggregate")
    es.set_defaults(func=cmd_end_session)

    ld = sub.add_parser("list-devices", help="Print Govee devices on this account")
    ld.set_defaults(func=cmd_list_devices)

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
