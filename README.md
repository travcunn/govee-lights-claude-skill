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
