# Configuration

## Registry

`config/registry.json` is the central configuration. It defines:

- **skills** — role skill paths and default capabilities
- **hosts** — available tool surfaces and their supported models
- **models** — model-specific notes and host availability
- **presets** — named lane maps for common routing patterns
- **personas** — optional style/expertise overlays
- **defaults** — profile directory names, default preset, persona mode

Edit this file to match your available tools and subscriptions.

## Workspace Profile

Created by `relaykit init-workspace`. Stored at `.relaykit/workspace-profile.json`.

Contains:
- Available hosts and models
- Default preset
- Default personas
- Lane overrides

This is git-ignored by default since it reflects your local environment.

## Project Profile

Created by `relaykit init-project`. Stored at `.relaykit/project-profile.json`.

Inherits workspace defaults and adds project-specific overrides.

## Presets

Presets are starting-point lane maps. The registry ships with examples:

| Preset | Intent |
|---|---|
| `balanced-default` | Planning + critique on Claude, execution on Codex |
| `cost-aware` | Minimize premium credits |
| `custom` | Empty — define your own topology |

You can add your own presets directly in the registry.

## Task State

Full-mode tasks persist under `.relaykit/tasks/<task-id>/`:
- `state.json` — full task state machine
- `summary.json` — current human-readable summary

## Learning

RelayKit learns from reflections:
- `.relaykit/learning-log.jsonl` — raw append-only log
- `.relaykit/learned-tendencies.json` — regenerated summary

Learning is advisory. It influences recommendations but never silently rewrites defaults.
