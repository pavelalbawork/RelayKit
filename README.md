# RelayKit

Harness augmentation for multi-tool, human-in-the-loop parallel execution.

RelayKit augments existing harnesses like Codex, Claude Code, Gemini CLI, and Antigravity so one operator can run parallel lanes, assign deliberate roles, and keep the human in charge of coordination instead of treating every tool as a generic assistant.

Task intake, lane recommendation, onboarding, checkpoints, handoffs, and learning are the main mechanisms. They exist to make existing harnesses behave like one operator-directed system.

## Quick Start

Install RelayKit:

```bash
pipx install "git+https://github.com/pavelalbawork/RelayKit.git"
pipx ensurepath
```

That is the normal install path. It does not require cloning the repo first.

If you are developing locally or want an editable install from a checkout, clone the repo and install from the working tree instead:

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

If your shell still says `command not found: relaykit`, reload it once:

```bash
exec zsh
```

If you want to continue immediately without reloading the shell, use the direct `pipx` app path once:

```bash
~/.local/bin/relaykit setup --host codex
```

Swap `codex` for `claude-code`, `gemini-cli`, or `antigravity`.

Supported hosts:
- `codex`
- `claude-code`
- `gemini-cli`
- `antigravity`

Run setup once per host you actually want RelayKit available in. To wire all supported hosts in one pass:

```bash
relaykit setup --all-hosts
```

Then restart your host and say:

```text
Use RelayKit MCP tools directly.
```

That is the main first-use path. Most users should stop there.

## If That Fails

If `pipx` is unavailable or your Python setup blocks it, use the built-in fallback:

```bash
python3 scripts/relaykit.py install-self
python3 scripts/relaykit.py setup --host codex --force
```

Then restart your host and use the same prompt:

```text
Use RelayKit MCP tools directly.
```

## Remove RelayKit Completely

If you want a clean uninstall, do it in this order:

1. remove RelayKit-managed host wiring
2. uninstall the package
3. delete copied skill folders only if you used the skills-only fallback

Remove host wiring:

```bash
relaykit uninstall-host --host codex
relaykit uninstall-host --host claude-code
relaykit uninstall-host --host gemini-cli
relaykit uninstall-host --host antigravity
```

Uninstall the package:

```bash
pipx uninstall relaykit
```

If you installed RelayKit into a manual virtualenv instead of `pipx`, remove that venv or run `pip uninstall relaykit` inside it.

If you copied skills manually, remove those folders too:

```bash
rm -rf ~/.claude/skills/relaykit*
rm -rf ~/.gemini/skills/relaykit*
rm -rf ~/.codex/skills/relaykit*
```

If you want your agent to help with cleanup, say:

```text
Remove RelayKit from this machine completely, including host wiring and any copied skill folders.
```

## What `setup` Does

`relaykit setup` is the normal onboarding command. It:

- wires the selected host
- runs a safe local smoke test
- prints concise next steps for entering the MCP path

In a normal terminal, `setup` now prints a short human-readable summary by default. Use `--format json` if you want the full machine payload.

The setup smoke is pinned to the host you selected, so `relaykit setup --host codex` verifies a Codex-only path instead of drifting to another host during the smoke recommendation.

Run it once per host you want to use with RelayKit. For example:

```bash
relaykit setup --host codex
relaykit setup --host claude-code
```

Or wire all supported hosts in one pass:

```bash
relaykit setup --all-hosts
```

Use `relaykit host-status --host <host>` when you want a readiness check without changing anything.

## More Install Options

**Install directly from GitHub (recommended for normal use):**

```bash
pipx install "git+https://github.com/pavelalbawork/RelayKit.git"
pipx ensurepath
relaykit --version
relaykit-mcp --help
```

This is the simplest path for most users. No local checkout is required.

**Clone the repo locally first (recommended for development):**

```bash
git clone git@github.com:pavelalbawork/RelayKit.git
cd RelayKit
pipx install -e .
pipx ensurepath
```

If you want a local working copy without keeping the upstream remote attached:

```bash
git remote remove origin
```

**Editable `pipx` from a local checkout:**

```bash
pipx install -e .
pipx ensurepath
relaykit --version
relaykit-mcp --help
```

Run that from inside the RelayKit repo checkout. If you are not in the repo directory, replace `.` with the full checkout path.

If `relaykit` is still not found right after install, your current shell has not reloaded the updated PATH yet. Run `exec zsh`, open a new terminal, or use `~/.local/bin/relaykit` once.

`pipx` installs into an isolated environment and puts `relaykit` and `relaykit-mcp` on your PATH globally. No venv activation, works from any directory or shell.

The installed `relaykit-mcp` entry point is the preferred MCP launch path across Codex, Claude Code, Gemini CLI, and Antigravity. It avoids raw source-tree config and keeps host wiring consistent.

**Manual venv — explicit fallback:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
relaykit --version
relaykit-mcp --help
```

With the venv flow, use the full venv path in any MCP config: `.venv/bin/relaykit-mcp`.

**Skills only — zero dependencies (optional fallback):**

```bash
cp -r skills/ ~/.claude/skills/
```

Copies the skill surface directly. No Python required. Use this only if you want portable RelayKit skills without the CLI or MCP server.

## MCP Server

If your host supports MCP, add this to its config:

```json
{
  "mcpServers": {
    "relaykit": {
      "command": "relaykit-mcp"
    }
  }
}
```

`relaykit-mcp` is registered as an entry point during install — no path needed. It is a long-lived stdio server backed by the official Python MCP SDK. `relaykit-mcp --help` and `relaykit-mcp --version` are safe to run; no arguments starts the server.

If you installed via venv instead of `pipx`, use the full path:

```json
{
  "mcpServers": {
    "relaykit": {
      "command": "/path/to/relaykit/.venv/bin/relaykit-mcp"
    }
  }
}
```

`bootstrap-host` can write this config automatically for supported hosts, so manual MCP editing should be the exception, not the default.

## Quick Start

Use RelayKit when you want multiple harnesses to behave like coordinated lanes in one human-directed system.

Start a task:

```bash
relaykit start-task --workspace-root . --task "Build the login page"
```

Lifecycle commands now default to a concise human-readable view in an interactive terminal. Use `--format json` when you want the raw machine payload for scripting or debugging.

If you want the guided shell version instead of stepping through individual commands, use:

```bash
relaykit run --workspace-root . --task "Build the login page"
```

RelayKit now makes the preflight verdict explicit in recommendations:
- `manual` means the task is probably too small for protocol overhead
- `lean` means a light protocol path is worth it
- `full` means durable continuity or a research lane is justified

Answer clarification questions until you get a recommendation:

```bash
relaykit answer-task --workspace-root . --task-id <id> --answer "Keep it to one component."
```

Confirm and execute:

```bash
relaykit confirm-task --workspace-root . --task-id <id> --accept
```

If RelayKit decides a task is so small and bounded that the protocol is not worth it, `confirm-task` will stop and recommend manual coordination instead. Use `--force-protocol` only when you explicitly want RelayKit state and handoffs anyway.

For small bounded coordinated tasks that still benefit from the protocol, RelayKit now defaults to `coordinated+lean`. In that path, `confirm-task` returns a `launch_bundle` immediately with ultra-compact handoff cards and compact launch markdown, so you usually do not need separate `render-task-part` calls unless you want a verbose packet or need to re-render later.

Checkpoint, resume, and reflect when done:

```bash
relaykit checkpoint-task --workspace-root . --task-id <id> --notes "Header done, form next."
relaykit resume-task --workspace-root . --task-id <id>
relaykit reflect-task --workspace-root . --task-id <id> --split-worth-it yes --tool-fit good
```

Use `resume-task` for the operator view. If you need ready-to-send packets for the remaining active parts after an interruption, use:

```bash
relaykit resume-handoff --workspace-root . --task-id <id>
```

For lean coordinated phases, prefer the batched path:

```bash
relaykit checkpoint-phase --workspace-root . --task-id <id> --reports '[{"part_id":"implementation","notes":"builder ready"},{"part_id":"critique","notes":"critic agrees"}]'
relaykit render-consolidation-packet --workspace-root . --task-id <id>
```

The compact consolidation packet keeps the full per-part reports in the structured payload while summarizing them in the markdown handoff by default. Use `--verbosity verbose` when you want the full inline report text. The lean path is optimized for low-overhead handoffs; use `render-task-part --verbosity verbose` when a receiving host needs the full prompt stack and richer context.

## Workspace Setup

Save persistent defaults so RelayKit knows your available tools and models:

```bash
relaykit init-workspace --workspace-root . --start-with-defaults
relaykit doctor --workspace-root .
```

If no workspace profile exists yet and you want a non-interactive first-run path, use the guided flow instead:

```bash
relaykit guided-setup --workspace-root . --host codex --preset balanced-default
```

If `git_integration` is enabled in the workspace or project profile, RelayKit will not create branches during `confirm-task`. It will return an explicit follow-up step instead:

```bash
relaykit prepare-git --workspace-root . --task-id <id>
```

## Example

See the [end-to-end walkthrough](examples/basic-workspace/WALKTHROUGH.md) for a full task lifecycle: intake → clarification → recommendation → builder lane → checkpoint → reflect.

## Documentation

- [Docs Home](docs/index.md) — narrative and reading order
- [Core Concepts](docs/concepts.md) — tasks, roles, lanes, hosts, checkpoints
- [Commands](docs/commands.md) — full CLI reference
- [Configuration](docs/configuration.md) — registry, profiles, presets
- [Skills](docs/skills.md) — portable role skills and how to use them
- [Personas](personas/README.md) — optional style/expertise overlays
- [Messaging](MESSAGING.md) — canonical positioning language
- [Landing Copy](LANDING_COPY.md) — website-ready hero, subhead, and blurb
- [GitHub Metadata](GITHUB_METADATA.md) — suggested repo description, topics, and blurbs

## Requirements

- Python 3.11+
- Small runtime dependencies: `anyio` and `mcp`
- Skills-only install still has no Python dependency requirement

## License

MIT
