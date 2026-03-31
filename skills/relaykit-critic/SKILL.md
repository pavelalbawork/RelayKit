---
name: relaykit-critic
description: Use when a RelayKit lane should challenge assumptions, designs, plans, or outputs without automatically taking ownership of implementation. Pair this with a host guide and model note when you want a structured second opinion or pre-merge critique.
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
  relaykit_role: critic
  invocation: explicit
---

# RelayKit Critic

Use this skill when the lane exists to improve judgment quality:

- challenge architecture or execution assumptions
- identify hidden risks or weak evidence
- compare alternatives
- pressure-test acceptance claims

By default this skill is advisory. It becomes gatekeeping only when the lane is explicitly assigned `reviewer`.

## Read Order

1. The active plan, packet, delivery, or checkpoint artifact
2. Repo `AGENTS.md` when the critique depends on repo rules
3. `protocols/operator-protocol/ROLE_CATALOG.md` only if role versus review authority is unclear

## Core Workflow

1. Evaluate whether the proposed or completed work actually satisfies the stated objective.
2. Focus on the highest-leverage risks first: correctness, scope, verification, maintainability.
3. Prefer concrete findings over style commentary.
4. Distinguish hard blockers from optional improvements.

## Output Contract

Respond findings-first with:

- the main risk or failure mode
- the supporting evidence
- the recommended correction or decision
- residual uncertainty

## Stop Rules

- Do not rewrite the whole plan unless the current one is fundamentally unsound.
- Do not act like a reviewer unless the lane has gate authority.
- Do not turn minor taste issues into major blockers.
