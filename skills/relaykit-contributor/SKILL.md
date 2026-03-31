---
name: relaykit-contributor
description: Use when a RelayKit lane owns a bounded packet as the main contributor. This skill is host-neutral and works for implementation, repo edits, documentation, or focused execution slices. Pair it with a host guide and model note to choose the actual tool and model.
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
  relaykit_role: contributor
  invocation: explicit
---

# RelayKit Contributor

Use this skill when a lane is expected to produce the work, not just route it.

This skill is intentionally broader than one protocol role. It commonly maps to:

- `builder`
- `researcher`
- `tester`

The packet or plan decides which one is active.

## Read Order

1. The active packet or handoff card
2. Repo `AGENTS.md`
3. Repo-local `THREAD_SYNC.md`, `PROGRESS.md`, or active exec plan only if the repo is actually using them
4. `protocols/operator-protocol/ARTIFACT_STANDARD.md` only if artifact shape is unclear

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
