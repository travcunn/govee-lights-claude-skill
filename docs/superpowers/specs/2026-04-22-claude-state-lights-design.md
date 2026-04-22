# Claude Code state lights — design

**Status:** proposed
**Date:** 2026-04-22

## Goal

Use my two Govee office lights (H6076) as an ambient indicator of Claude Code state, so I can tell from the lights alone whether Claude is working, waiting on my input, or needs permission.

## Non-goals (v1)

- Build / CI / git signals (future v2)
- Per-project overrides
- Targeting the TV light or any device group
- Any GUI or config UI

## States and colors

Three states only:

| State        | Color         | Meaning                                           |
|--------------|---------------|---------------------------------------------------|
| `working`    | Warm white 2700K | Claude is actively working, or no active session |
| `your-turn`  | Yellow `#FFCC00` (RGB `16763904`) | Claude finished, waiting on me to reply |
| `permission` | Red `#FF0000` (RGB `16711680`)    | Claude needs permission approval         |

`working` doubles as the default / idle-background color.

## Target devices

Office light 1 and Office light 2 only (both sku `H6076`):

- `D2:F8:C4:32:38:31:70:27` — Office light 1
- `CB:AF:C3:32:38:31:3C:49` — Office light 2

Device IDs live in `config.py` (static for v1, since they're stable).

## Hook wiring

Global `~/.claude/settings.json`, each hook invokes the same CLI wrapper in this repo:

| Claude event        | CLI invocation                      | Target state                  |
|---------------------|-------------------------------------|-------------------------------|
| `Notification`      | `govee-hook notify`                 | `permission` or `your-turn` (parsed from message) |
| `Stop`              | `govee-hook set-state your-turn`    | `your-turn`                   |
| `UserPromptSubmit`  | `govee-hook set-state working`      | `working`                     |
| `PreToolUse`        | `govee-hook set-state working`      | `working` (resets after permission approval) |
| `SessionStart`      | `govee-hook set-state working`      | `working`                     |
| `SessionEnd`        | `govee-hook end-session`            | Removes this session from aggregate |

`PreToolUse` is the critical "return from red to warm white after I approve a permission prompt" trigger. It fires often, so the state cache short-circuits it into a no-op in the common case.

### Notification disambiguation

The `Notification` event fires for two different conditions:

1. Claude needs permission to run a tool
2. Claude has been idle for 60 seconds waiting for my input

Both arrive on stdin as JSON with a `message` field. The `notify` subcommand inspects the message: if it mentions "permission" it sets `permission`; otherwise it sets `your-turn`.

## CLI surface

Single entry point `govee-lights`:

- `govee-lights set-state {working|your-turn|permission}` — deterministic state setter
- `govee-lights notify` — reads Claude hook JSON from stdin, delegates to `set-state`
- `govee-lights end-session` — reads hook JSON from stdin, drops this session's entry
- `govee-lights list-devices` — convenience: prints devices from Govee, for verifying / refreshing hardcoded device IDs

All subcommands exit `0` on any failure (hooks must not block Claude). Failures log to stderr.

## Architecture

```
                    ┌─────────────────────┐
  Claude Code  ───▶ │ hooks/govee-hook    │  (thin bash wrapper)
    (event)         └──────────┬──────────┘
                               │ uv --directory ... run govee-lights ...
                               ▼
                    ┌─────────────────────┐
                    │  src/govee_lights/  │
                    │    cli.py           │  ◀── stdin: session_id + message
                    └──┬──────────┬───────┘
                       │          │
          ┌────────────┘          └────────────────┐
          ▼                                        ▼
  ┌──────────────┐                      ┌──────────────────┐
  │  state.py    │                      │   client.py      │
  │              │                      │                  │
  │ read/write   │                      │ POST Govee API   │
  │ per-session  │                      │ for each device  │
  │ cache w/     │                      │                  │
  │ flock + TTL  │                      │                  │
  └──────┬───────┘                      └──────────────────┘
         │
         ▼
  ~/.cache/govee-lights/state.json
```

### Repo layout

```
govee-lights/
├── pyproject.toml
├── .env                         # gitignored (GOVEE_API_KEY)
├── .env.example
├── .gitignore                   # .env, __pycache__, .venv, etc.
├── README.md                    # install + hook wiring instructions
├── src/govee_lights/
│   ├── __init__.py
│   ├── cli.py                   # argparse entry point
│   ├── client.py                # Govee HTTP client (httpx)
│   ├── config.py                # .env loader, device list, color palette
│   └── state.py                 # Cache read/write, priority aggregation, flock
├── hooks/
│   └── govee-hook               # bash wrapper: exec uv --directory ... run
├── docs/superpowers/specs/
│   └── 2026-04-22-claude-state-lights-design.md
└── tests/
    ├── test_client.py
    └── test_state.py
```

## State model (concurrent-session safe)

The user runs multiple Claude Code sessions in parallel. Naive "last event wins" loses permission prompts when a second session fires a low-priority event right after. Instead, we track per-session state and aggregate by priority.

Cache file `~/.cache/govee-lights/state.json`:

```json
{
  "sessions": {
    "<session-id>": { "state": "permission", "updated_at": "2026-04-22T12:34:56Z" }
  },
  "current_color": "permission"
}
```

Priority ladder (highest wins):

```
permission (3) > your-turn (2) > working (1)
```

On every CLI invocation:

1. `fcntl.flock(LOCK_EX)` on the cache file (blocking; waits are sub-ms in practice)
2. Read cache (treat missing or malformed file as empty)
3. Prune entries with `updated_at` older than 30 minutes (crashed-session cleanup)
4. Update this session's entry (or delete it, for `end-session`)
5. Compute aggregate color via priority ladder; if no active sessions, default to `working`
6. If aggregate equals `current_color`, release lock and exit 0 (short-circuit)
7. Otherwise POST to Govee for each device, update `current_color`, write cache atomically (`os.replace` from tempfile), release lock

### Parallel session behavior

- A=working, B=permission → lights red (permission wins)
- A=your-turn, B=working → lights yellow (your-turn wins)
- A ends (SessionEnd fires), B=working → lights warm white
- A crashes (no SessionEnd), B=working → A expires after 30 min; until then the priority rule still does the right thing unless A was stuck in permission

### Rate limiting

Govee free tier is 10k calls/day. Short-circuit on unchanged state makes `PreToolUse` effectively free. Worst case per day across all sessions is a few hundred real state transitions × 2 devices = well under 10k.

## Error handling

- Missing `.env` / missing `GOVEE_API_KEY` → log to stderr, exit 0
- Govee HTTP failure (non-200, timeout, network error) → log to stderr, exit 0; cache is **not** updated so the next hook fire will retry
- Malformed hook JSON on stdin → log to stderr, exit 0
- Cache file corrupt → treat as empty and overwrite

Hooks never exit nonzero. Worst case of any failure is the lights don't change.

## Configuration

`.env` holds `GOVEE_API_KEY=...`. Device IDs are hardcoded in `config.py` for v1 — they're unlikely to change and moving them to config adds setup friction. If they do change, `uv run govee-lights list-devices` (added as a convenience subcommand) prints the current list.

## Testing

- `test_client.py` — mock `httpx.Client`, assert request URL / headers / body for `set_color_rgb` and `set_color_temperature`
- `test_state.py` — round-trip cache read/write, priority aggregation, TTL pruning, short-circuit on unchanged state, concurrent-write safety (two processes with flock)
- No Govee integration tests in CI (would need the key). Manual smoke test documented in README: `uv run govee-lights set-state permission` should turn the lights red.

## Installation flow (for README)

1. Clone repo, `uv sync`
2. `cp .env.example .env` and paste API key
3. Make `hooks/govee-hook` executable
4. Append hook stanzas to `~/.claude/settings.json` (example block in README)
5. Sanity check: `uv run govee-lights set-state permission` → red; `set-state working` → warm white

## Out of scope / future

- v2: layer in build/CI status (GitHub Actions via `gh`, local test runner). Probably a second daemon-ish process, not hooks.
- v2: per-repo color overrides (e.g., "red only matters in the work repos")
- Device discovery / dynamic config (currently hardcoded)
- Cross-machine sync (state is local to this machine)
