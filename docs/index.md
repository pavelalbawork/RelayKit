# RelayKit Docs

Harness augmentation for multi-tool, human-in-the-loop parallel execution.

RelayKit augments existing harnesses like Codex, Claude Code, Gemini CLI, and Antigravity so one operator can run parallel lanes, assign deliberate roles, and keep the human in charge of coordination.

## Start Here

Install RelayKit:

```bash
pipx install -e /path/to/relaykit
```

Wire your host:

```bash
relaykit setup --host codex
```

Then restart your host and say:

```text
Use RelayKit MCP tools directly and help me finish setup if anything is still missing.
```

If `pipx` is unavailable, use:

```bash
python3 scripts/relaykit.py install-self
python3 scripts/relaykit.py setup --host codex --force
```

Use RelayKit when you want a focused product surface for:

- task intake
- lane recommendation
- harness onboarding
- prompt-stack resolution
- checkpoints and resume flows
- optional personas and overlays

## Read This First

- [Core Concepts](./concepts.md)
- [Commands](./commands.md)
- [Configuration](./configuration.md)
- [Skills](./skills.md)
