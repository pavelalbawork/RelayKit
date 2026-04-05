# Core Concepts

RelayKit is a harness-augmentation layer. Its job is not to replace Codex, Claude Code, Gemini CLI, or Antigravity. Its job is to make those harnesses behave like coordinated lanes under one operator.

## Tasks

A task is a piece of work you describe in plain text. RelayKit clarifies it, classifies it, and recommends the smallest lane setup likely to work.

Tasks have two dimensions:
- **Solo or coordinated** — one tool or multiple tools working together
- **Lean or full** — ephemeral state or file-backed checkpoints

All four combinations are valid. RelayKit picks the smallest setup likely to work well while preserving operator control.

Tasks also carry a **phase mode**:
- **research-phase** — evidence, design exploration, and decision-making before implementation
- **review-phase** — critique or gate review without implementation ownership
- **implementation-phase** — execution is allowed to produce code and verification artifacts

Phase mode shapes the lane contracts and lets RelayKit warn when outputs drift into the wrong phase.

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

A lane binds a role to a concrete execution slice: harness + model + capabilities + prompt stack. Lanes are the unit that gets assigned.

Essential lane fields:
- `lane_id` — stable identifier
- `host` — the harness surface (codex, claude-code, gemini-cli, antigravity, etc.)
- `model` — the model running in that host
- `role` — the job this lane owns

Optional lane fields: `reasoning_effort`, `capabilities`, `credit_pool`, `personas`, `prompt_stack`, `review_gate`, `fallback_lane`.

## Hosts

A host is a harness surface that can run work: Codex, Claude Code, Gemini CLI, Antigravity, or any file-based skill host.

The backend stays host-neutral. Harness-specific concerns like prompt phrasing, capability quirks, and wiring stay in configuration.

## Checkpoints

In full mode, work is checkpoint-driven. Each checkpoint produces:
- Current state
- Recommended next action
- Safe stop point
- Resume instructions

Checkpoint outcomes: `on_track`, `blocked`, `needs_reroute`, `ready_for_next_phase`.

RelayKit can also attach **phase warnings** to checkpoints when outputs violate the current phase contract. Example: a research-phase lane producing `.swift` files or unsupported API claims without explicit sources.

## Task Parts

When RelayKit recommends a coordinated setup, the task is split into parts. Each part gets its own lane assignment, objective, and optional persona so multiple harnesses can run in parallel without losing role clarity.

The default second part, when coordination is justified, is critique.

Each task part also carries an **output contract**:
- allowed outputs
- disallowed outputs
- whether source-backed evidence is required

RelayKit includes that contract in the handoff packet so receiving hosts know whether they are supposed to research, design, review, or implement.

## Presets

Presets are named lane maps for common multi-harness patterns. They're starting points, not rules; any task can override a preset.

## Artifacts

Tasks produce file-backed artifacts:
- **Task packet** — bounded unit of work with scope, verification target, and stop condition
- **Handoff card** — transfer brief when ownership changes
- **Checkpoint review** — gate review at named milestones

Templates for these live in `templates/`.

## Personas

Optional style/expertise overlays that bias a lane's behavior. Never required. See `personas/README.md`.
