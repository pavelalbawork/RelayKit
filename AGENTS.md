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
- Public-facing RelayKit copy should read as a complete product.
- If a change touches duplicated public surfaces maintained elsewhere, keep them in sync instead of allowing drift.
- Keep maintainer-only policy language out of public-facing product docs.
