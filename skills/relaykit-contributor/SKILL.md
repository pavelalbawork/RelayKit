---
name: relaykit-contributor
description: Use only after RelayKit has already assigned a contributor or builder lane. This skill owns a bounded execution packet for implementation, repo edits, documentation, or focused execution slices.
license: MIT
compatibility:
  hosts:
    - Codex
    - Antigravity
    - Gemini CLI
    - Generic file-based skill hosts
metadata:
  version: 0.1.0
  relaykit_kind: role
  relaykit_role: contributor
  invocation: explicit
---

# RelayKit Contributor

Use this skill when a lane is expected to produce the work, not just route it.

If the user is asking to split work across tools, start with `relaykit` first. Do not load this role skill as the entrypoint for multi-tool routing.

This skill is the default for the `builder` role: implementation, repo edits, documentation, or focused execution slices.

If the lane is assigned a more specific role, prefer the dedicated skill:

- `researcher` → load `relaykit-researcher`
- `tester` → load `relaykit-tester`
- `reviewer` → load `relaykit-reviewer`

Use this skill when no dedicated skill applies or when the packet mixes builder work that doesn't fit a single specialized role.

## Read Order

1. The active packet or handoff card
2. Repo `AGENTS.md`
3. Repo-local `PROGRESS.md` or active exec plan only if the repo is actually using them
4. `templates/TASK_PACKET_TEMPLATE.md` only if the expected artifact shape is unclear

## Core Workflow

1. Confirm objective, allowed scope, excluded scope, verification target, and stop condition.
2. Execute the smallest useful slice that advances the packet cleanly.
3. Verify your own work before handing it back.
4. Record concrete evidence, not vague confidence.
5. Escalate when blocked instead of guessing across missing context or unsafe scope.

## Output Contract

Always leave behind:

- what changed
- what was verified
- what remains open
- the next recommended step

## Stop Rules

- Do not take over orchestration unless the packet explicitly transfers it.
- Do not expand into adjacent systems without an updated scope.
- Do not return "done" without evidence.
