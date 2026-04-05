---
name: relaykit-tester
description: Use only after RelayKit has already assigned a tester lane. This skill owns verification, coverage, or evidence generation for completed work.
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
  relaykit_role: tester
  invocation: explicit
---

# RelayKit Tester

Use this skill when the lane exists to verify work, not produce it.

If the user is asking to split work across tools, start with `relaykit` first. Do not load this role skill as the entrypoint for multi-tool routing.

This skill is for testing that delivered output actually satisfies acceptance criteria: writing tests, running them, checking edge cases, and producing a concrete pass/fail record. The tester lane does not own the implementation — it owns the evidence.

## Read Order

1. The active packet or handoff card — specifically the acceptance criteria and verification target
2. The builder lane's output or delivery note
3. Repo `AGENTS.md`

## Core Workflow

1. Read the acceptance criteria and verification target from the packet.
2. Plan the minimal test set that covers the stated criteria plus obvious edge cases.
3. Execute tests, inspections, or checks within the allowed scope.
4. Record concrete pass/fail results — not confidence claims.
5. If anything fails, report the specific failure with enough detail for the builder to act on it without a follow-up question.

## Output Contract

Always leave behind:

- what was tested and what coverage was achieved
- concrete pass/fail result per acceptance criterion
- specific failure details if anything did not pass
- any edge cases that were not covered and why
- recommended next step: advance, return to builder, or escalate

## Stop Rules

- Do not fix failures found during testing — report them and return to the builder lane.
- Do not invent acceptance criteria not stated in the packet.
- Do not return "tests passed" without traceable evidence.
- Do not block on full coverage if partial coverage is what the scope allows — report what was covered.
