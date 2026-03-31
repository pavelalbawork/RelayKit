# Core Concepts

## Tasks

A task is a piece of work you describe in plain text. RelayKit clarifies it, classifies it, and recommends a setup.

Tasks have two dimensions:
- **Solo or coordinated** — one tool or multiple tools working together
- **Lean or full** — ephemeral state or file-backed checkpoints

All four combinations are valid. RelayKit picks the smallest setup likely to work well.

## Roles

Roles describe what a lane does, not which tool runs it:

| Role | Responsibility |
|---|---|
| orchestrator | Planning, routing, checkpointing, convergence |
| builder | Implementation and verification |
| critic | Advisory challenge without ownership |
| reviewer | Gate review with pass/fail authority |
| researcher | Evidence gathering and synthesis |
| tester | Browser, QA, or regression verification |

Roles are not permanently tied to tools or models.

## Lanes

A lane binds a role to a concrete execution slice: tool + model + capabilities + prompt stack. Lanes are the unit that gets assigned.

Essential lane fields:
- `lane_id` — stable identifier
- `host` — the tool surface (codex, claude-code, gemini-cli, etc.)
- `model` — the model running in that host
- `role` — the job this lane owns

Optional lane fields: `reasoning_effort`, `capabilities`, `credit_pool`, `personas`, `prompt_stack`, `review_gate`, `fallback_lane`.

## Hosts

A host is a tool surface that can run work: Codex, Claude Code, Gemini CLI, Antigravity, or any file-based skill host.

The backend stays host-neutral. Host-specific concerns (prompt phrasing, capability quirks) stay in configuration.

## Checkpoints

In full mode, work is checkpoint-driven. Each checkpoint produces:
- Current state
- Recommended next action
- Safe stop point
- Resume instructions

Checkpoint outcomes: `on_track`, `blocked`, `needs_reroute`, `ready_for_next_phase`.

## Task Parts

When RelayKit recommends a coordinated setup, the task is split into parts. Each part gets its own lane assignment, objective, and optional persona.

The default second part, when coordination is justified, is critique.

## Presets

Presets are named lane maps for common routing patterns. They're starting points, not rules — any task can override a preset.

## Artifacts

Tasks produce file-backed artifacts:
- **Task packet** — bounded unit of work with scope, verification target, and stop condition
- **Handoff card** — transfer brief when ownership changes
- **Checkpoint review** — gate review at named milestones

Templates for these live in `templates/`.

## Personas

Optional style/expertise overlays that bias a lane's behavior. Never required. See `personas/README.md`.
