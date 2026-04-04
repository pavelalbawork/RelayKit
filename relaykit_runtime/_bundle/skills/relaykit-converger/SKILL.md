---
name: relaykit-converger
description: Use when several candidate outputs, reviews, or RelayKit lanes need to be compared, merged, or resolved into one final direction without losing the decision rationale.
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
  relaykit_role: converger
  invocation: explicit
---

# RelayKit Converger

Use this skill when the lane owns synthesis across several competing or overlapping outputs.

Common fits:

- compare two candidate implementations
- merge critic and builder outputs
- resolve conflicting recommendations
- produce one final direction from several lanes

## Read Order

1. The active packet, delivery reports, or convergence artifact
2. Repo `AGENTS.md` when local acceptance rules matter
3. The relevant checkpoint or review artifacts

## Core Workflow

1. Restate the decision to be made and the criteria that matter.
2. Compare outputs by evidence, not by tool identity.
3. Preserve useful minority findings even when one direction wins.
4. Lock the chosen direction into a visible next step.

## Output Contract

Always leave behind:

- the compared inputs
- the decision dimensions
- the selected direction
- the reason it won
- the next valid command

## Stop Rules

- Do not choose based on tool loyalty or model prestige.
- Do not collapse meaningful differences into vague compromise.
- Do not lose the rationale for why one path was selected.
