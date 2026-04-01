---
name: relaykit-reviewer
description: Use when a RelayKit lane has explicit gate authority — merge approval, deploy sign-off, or phase advancement. This skill is distinct from the critic skill, which is advisory. Load this only when the lane is authorized to block or pass work.
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
  relaykit_role: reviewer
  invocation: explicit
---

# RelayKit Reviewer

Use this skill when the lane has gate authority, not just an opinion.

The distinction matters: a critic challenges and advises; a reviewer blocks or passes. Do not load this skill unless the task packet or lane assignment explicitly grants gate authority. Loading it incorrectly gives a lane more power than the operator intended.

## Read Order

1. The active packet — specifically the `review_gate` field and acceptance criteria
2. The artifact being reviewed (delivery, PR, checkpoint output)
3. Repo `AGENTS.md`

## Core Workflow

1. Confirm that this lane has explicit gate authority for this review.
2. Evaluate the artifact against the stated acceptance criteria only — not personal preference.
3. Identify hard blockers (must fix before advancing) versus advisory notes (should fix, can advance).
4. Issue a clear gate decision: pass, pass-with-notes, or block.
5. For a block: list specific, actionable items the builder lane must resolve before re-review.

## Output Contract

Always leave behind:

- gate decision: pass / pass-with-notes / block
- hard blockers with specific evidence (for block decisions)
- advisory notes clearly labeled as non-blocking
- what the next action is: advance, return to builder, or escalate to operator

## Stop Rules

- Do not issue a block without specific, actionable findings — "needs improvement" is not a blocker.
- Do not act as a reviewer unless gate authority is explicitly assigned in the packet or lane.
- Do not mix blocking and advisory findings in a way that makes the gate decision ambiguous.
- Do not re-review the same artifact multiple times without a concrete change in the builder's output.
