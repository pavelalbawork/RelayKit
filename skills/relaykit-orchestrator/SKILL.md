---
name: relaykit-orchestrator
description: Use only after RelayKit has already assigned an orchestration lane. This skill owns routing, sequencing, checkpointing, or convergence for a task.
license: MIT
compatibility:
  hosts:
    - Codex
    - Claude Code
    - Antigravity
    - Gemini CLI
    - Generic file-based skill hosts
metadata:
  version: 0.1.0
  relaykit_kind: role
  relaykit_role: orchestrator
  invocation: explicit
---

# RelayKit Orchestrator

Use this skill when the lane owns coherence for the work:

If the user is asking to split work across tools, start with `relaykit` first. Do not load this role skill as the entrypoint for multi-tool routing.

- selecting or adjusting lanes
- sequencing packets or phases
- deciding when to split, hand off, checkpoint, or converge
- preserving shared state and stop conditions

Do not use this skill as an excuse to own all implementation. An orchestrator should keep execution delegated when the packet is already clear.

## Read Order

1. The active packet, plan, or routing note
2. Repo `AGENTS.md`
3. Run `relaykit list presets` only if lane topology is unclear and you need a default starting map
4. Run `relaykit preset <name>` only if you need to inspect a specific lane layout

## Core Workflow

1. Restate the objective, current packet state, writable scope, verification target, and stop condition.
2. Keep one owner per writable slice unless overlap is explicitly worth the cost.
3. Choose or update lanes based on task fit, not habit.
4. Push ambiguous work toward a bounded packet before handing it off.
5. At each checkpoint, choose one of: continue, hand off, escalate, review, or converge.

## Output Contract

Always leave behind:

- the current objective
- the active lane map or routing change
- the next valid command
- the blocking risk if work cannot continue cleanly

## Stop Rules

- Do not silently expand scope.
- Do not take over another lane's packet unless ownership is explicitly transferred.
- Do not split work just because multiple tools exist.
