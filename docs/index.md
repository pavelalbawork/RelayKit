# RelayKit Docs

Harness augmentation for multi-tool, human-in-the-loop parallel execution.

RelayKit augments existing harnesses like Codex, Claude Code, Gemini CLI, and Antigravity so one operator can run parallel lanes, assign deliberate roles, and keep the human in charge of coordination.

## Start Here

Install RelayKit:

```bash
pipx install "git+https://github.com/pavelalbawork/RelayKit.git"
pipx ensurepath
```

That is the normal install path. It does not require cloning the repo first.

If you want a local editable install instead:

```bash
git clone git@github.com:pavelalbawork/RelayKit.git
cd RelayKit
pipx install -e .
pipx ensurepath
```

Wire your host:

```bash
relaykit setup --host codex
```

If your current shell still cannot find `relaykit`, run:

```bash
exec zsh
```

Or continue immediately with:

```bash
~/.local/bin/relaykit setup --host codex
```

Supported hosts:
- `codex`
- `claude-code`
- `gemini-cli`
- `antigravity`

Run setup once per host you want available. To wire all supported hosts in one pass:

```bash
relaykit setup --all-hosts
```

Then restart your host and say:

```text
Use RelayKit MCP tools directly.
```

If you want a local working copy without keeping the upstream remote:

```bash
git remote remove origin
```

If `pipx` is unavailable, use:

```bash
python3 scripts/relaykit.py install-self
python3 scripts/relaykit.py setup --host codex --force
```

If you want to remove RelayKit completely later:

```bash
relaykit uninstall-host --host codex
pipx uninstall relaykit
rm -rf ~/.claude/skills/relaykit*
rm -rf ~/.gemini/skills/relaykit*
rm -rf ~/.codex/skills/relaykit*
```

Use the skill-folder cleanup only if you copied skills manually.

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
