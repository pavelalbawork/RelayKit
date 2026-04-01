# AGENTS.md

This repo is the canonical home of RelayKit.

## Read First

1. [`README.md`](README.md)
2. [`docs/concepts.md`](docs/concepts.md)

## Scope

Edit here when changing:

- RelayKit runtime behavior (CLI, MCP, backend)
- Skills, templates, or personas
- Configuration and registry

## Rules

- Keep the runtime file-first with zero external dependencies.
- Record meaningful decisions in commit messages, not separate logs.
- Keep host-specific concerns in configuration, not in code.
- Do not treat this repo as the authoring authority for mirrored product surfaces.
- If a change touches mirrored skills, messaging, docs, or example assets, promote it into RelayPack canon first and then re-sync.
- Public-facing RelayKit copy should read as a complete product. Internal canon or subset language belongs only in maintainer surfaces.
