# govee-lights

Ambient Claude Code state indicator using two Govee H6076 office lights.

- **Warm white** — idle / Claude is working
- **Red** — Claude needs permission approval (sticky until resolved)
- **Green flash (~2s)** — Claude finished a task or pinged for attention, then fades back to warm

Parallel Claude Code sessions are handled via per-session priority aggregation: any session holding permission keeps the lights red; otherwise they stay warm. Green flashes are per-event and never override an active red.

## Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh` on macOS/Linux)
- A Govee API key — get one from the Govee Home app: **Profile → About Us → Apply for API Key**. Govee emails it within a few minutes.
- Govee devices that support `colorRgb` and `colorTemperatureK` capabilities (the defaults in `config.py` are two Office H6076 lights; edit `TARGET_DEVICES` to match yours).

## Install

```bash
git clone https://github.com/travcunn/govee-lights-claude-skill.git
cd govee-lights-claude-skill
uv sync
cp .env.example .env
# Edit .env and paste your Govee API key
```

## Verify

```bash
uv run govee-lights list-devices         # prints devices on your account
uv run govee-lights set-state permission # office lights → red
uv run govee-lights set-state working    # office lights → warm white
uv run govee-lights task-done            # green flash ~2s, then warm
```

If `list-devices` works but `set-state` does nothing, confirm the `device_id` and `sku` values in `src/govee_lights/config.py` match entries from `list-devices`.

## Wire up Claude Code hooks

Add these to `~/.claude/settings.json` (replace `<REPO_PATH>` with the absolute path to this repo):

```json
{
  "hooks": {
    "Notification":     [{ "hooks": [{ "type": "command", "command": "<REPO_PATH>/hooks/govee-hook notify" }] }],
    "Stop":             [{ "hooks": [{ "type": "command", "command": "<REPO_PATH>/hooks/govee-hook task-done" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "<REPO_PATH>/hooks/govee-hook set-state working" }] }],
    "PreToolUse":       [{ "hooks": [{ "type": "command", "command": "<REPO_PATH>/hooks/govee-hook set-state working" }] }],
    "SessionStart":     [{ "hooks": [{ "type": "command", "command": "<REPO_PATH>/hooks/govee-hook set-state working" }] }],
    "SessionEnd":       [{ "hooks": [{ "type": "command", "command": "<REPO_PATH>/hooks/govee-hook end-session" }] }]
  }
}
```

Restart Claude Code (or start a new session) so the hooks take effect.

## How it works

Each hook invocation calls `hooks/govee-hook`, which runs `uv run govee-lights <subcommand>`. The CLI:

1. Acquires a `fcntl.flock` on `~/.cache/govee-lights/state.lock` to serialize parallel sessions.
2. Updates this session's entry in `~/.cache/govee-lights/state.json` (session ID comes from Claude's hook payload on stdin).
3. Prunes entries older than 2 minutes (cleans up crashed sessions; live sessions heartbeat on every hook fire, so they never expire).
4. Computes the aggregate sticky color via priority ladder: `permission > working`.
5. If the aggregate differs from the currently-pushed color, POSTs to the Govee API for each target device.

The `task-done` subcommand (wired to `Stop` and to non-permission `Notification`s) is different:

1. Double-forks into a daemonized grandchild so the hook returns immediately.
2. Resets this session's entry to `working` and checks the aggregate.
3. If aggregate is `permission`, the flash is suppressed (red stays up).
4. Otherwise, pushes green, sleeps 2 seconds, re-checks the aggregate, and pushes warm (or no-ops if a new permission arrived during the sleep).

Every error path logs to stderr and exits 0, so Govee hiccups never block Claude Code.

## Tests

```bash
uv run pytest -v
```

## Notes

- API key lives in `.env` (gitignored). Never commit it.
- Stale session entries in the local cache self-expire after 2 minutes. Live sessions refresh their entry on every hook fire, so only crashed / abandoned sessions age out.
- Hooks always exit 0 so Govee failures never block Claude Code.
- The `list-devices` subcommand is handy for grabbing `device_id` / `sku` values when editing `TARGET_DEVICES`.
