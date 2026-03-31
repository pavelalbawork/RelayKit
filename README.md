# RelayKit

Task-first routing for multi-tool AI workflows.

RelayKit helps you describe a task, get a setup recommendation (which tools, models, and roles to use), and then execute with checkpoints, handoffs, and learning — across Codex, Claude Code, Gemini CLI, Antigravity, or any file-based skill host.

## Install

```bash
pip install -e .
relaykit --version
```

## Quick Start

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

## MCP Server

Use RelayKit from any MCP-capable host:

```json
{
  "mcpServers": {
    "relaykit": {
      "command": "python3",
      "args": ["/path/to/relaykit/mcp/relaykit/server.py"]
    }
  }
}
```

## Optional Workspace Setup

Save persistent defaults so RelayKit knows your available tools and models:

```bash
relaykit init-workspace --workspace-root . --start-with-defaults
relaykit doctor --workspace-root .
```

## Documentation

- [Core Concepts](docs/concepts.md) — tasks, roles, lanes, hosts, checkpoints
- [Commands](docs/commands.md) — full CLI reference
- [Configuration](docs/configuration.md) — registry, profiles, presets
- [Skills](docs/skills.md) — portable role skills and how to use them
- [Personas](personas/README.md) — optional style/expertise overlays

## Requirements

- Python 3.11+
- No third-party dependencies

## License

MIT
