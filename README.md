# RelayKit

Harness augmentation for multi-tool, human-in-the-loop parallel execution.

RelayKit augments existing harnesses like Codex, Claude Code, Gemini CLI, and Antigravity so one operator can run parallel lanes, assign deliberate roles, and keep the human in charge of coordination instead of treating every tool as a generic assistant.

Task intake, lane recommendation, onboarding, checkpoints, handoffs, and learning are the main mechanisms. They exist to make existing harnesses behave like one operator-directed system.

## Install

**Recommended — `pipx` (global, no activation needed):**

```bash
pipx install -e /path/to/relaykit
relaykit --version
relaykit-mcp --help
```

`pipx` installs into an isolated environment and puts `relaykit` and `relaykit-mcp` on your PATH globally. No venv activation, works from any directory or shell.

The installed `relaykit-mcp` entry point is the preferred MCP launch path across Codex, Claude Code, Gemini CLI, and Antigravity. It avoids raw source-tree config and keeps host wiring consistent.

**Skills only — zero dependencies (optional fallback):**

```bash
cp -r skills/ ~/.claude/skills/
```

Copies the skill surface directly. No Python required. Use this only if you want portable RelayKit skills without the CLI or MCP server. For Codex, Claude Code, Gemini CLI, and Antigravity, the normal `pipx` install plus `setup` path is the preferred setup.

**Fastest fallback on Homebrew Python — one command, venv-safe:**

```bash
python3 scripts/relaykit.py install-self
```

Use this when `pipx` is unavailable or you hit the Homebrew Python `externally-managed-environment` error.

**Manual venv — explicit fallback:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
relaykit --version
relaykit-mcp --help
```

With the venv flow, use the full venv path in any MCP config: `.venv/bin/relaykit-mcp`.

## Harness Setup

After install, run one command to wire your harness, run a safe local smoke test, and print the exact next prompt for that harness:

```bash
relaykit setup --current-host
```

Supported auto-wiring targets currently include Codex, Claude Code, Gemini CLI, and Antigravity.

To preview changes without applying them:

```bash
relaykit setup --current-host --dry-run
```

To run the reusable local lifecycle proof by itself:

```bash
relaykit smoke --current-host
```

Other onboarding commands:

```bash
relaykit host-status --current-host        # check what's wired and what's missing
relaykit setup --host codex                # bootstrap, smoke, and print the next Codex prompt
relaykit acknowledge-host --current-host   # defer onboarding without being asked again
relaykit uninstall-host --current-host     # remove RelayKit-managed wiring
relaykit doctor --current-host             # validate the full setup
```

Fastest full local bring-up when you also want onboarding:

```bash
python3 scripts/relaykit.py install-self
python3 scripts/relaykit.py setup --current-host --force
```

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

Answer clarification questions until you get a recommendation:

```bash
relaykit answer-task --workspace-root . --task-id <id> --answer "Keep it to one component."
```

Confirm and execute:

```bash
relaykit confirm-task --workspace-root . --task-id <id> --accept
```

Checkpoint, resume, and reflect when done:

```bash
relaykit checkpoint-task --workspace-root . --task-id <id> --notes "Header done, form next."
relaykit resume-task --workspace-root . --task-id <id>
relaykit reflect-task --workspace-root . --task-id <id> --split-worth-it yes --tool-fit good
```

## Workspace Setup

Save persistent defaults so RelayKit knows your available tools and models:

```bash
relaykit init-workspace --workspace-root . --start-with-defaults
relaykit doctor --workspace-root .
```

## Example

See the [end-to-end walkthrough](examples/basic-workspace/WALKTHROUGH.md) for a full task lifecycle: intake → clarification → recommendation → builder lane → checkpoint → reflect.

## Documentation

- [Docs Home](docs/index.md) — narrative and reading order
- [RelayKit vs RelayPack](docs/comparison.md) — product options and practical split
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
