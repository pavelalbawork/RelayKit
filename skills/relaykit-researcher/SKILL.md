---
name: relaykit-researcher
description: Use when a RelayKit lane owns information gathering, evidence synthesis, or hypothesis validation before execution begins. Load this when the task needs a discovery phase before any implementation lane can start.
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
  relaykit_role: researcher
  invocation: explicit
---

# RelayKit Researcher

Use this skill when the lane exists to reduce uncertainty, not produce deliverables.

This skill is for work that precedes execution: gathering sources, validating assumptions, testing hypotheses, or producing a findings brief that the builder lane can act on.

Do not use this skill to own implementation. Researcher lanes produce evidence and recommendations, not code or artifacts.

## Read Order

1. The active packet or handoff card — especially the objective and open questions
2. Repo `AGENTS.md`
3. Repo-local `PROGRESS.md` only if prior research has already been logged

## Core Workflow

1. Restate the specific question or hypothesis the lane is being asked to resolve.
2. Identify the minimum evidence set that would answer it — don't over-gather.
3. Gather, test, or inspect sources within the allowed scope.
4. Synthesize into a findings brief: what is confirmed, what is ruled out, what remains open.
5. Deliver findings-first with explicit confidence level and recommended next action.

## Output Contract

Always leave behind:

- the question that was investigated
- findings with supporting evidence (not summary claims)
- what was ruled out and why
- confidence level: confirmed / probable / uncertain / unknown
- recommended next step for the builder or orchestrator lane

## Stop Rules

- Do not begin implementation because a solution became obvious during research.
- Do not expand the question set without operator approval.
- Do not return confident findings without traceable evidence.
- Do not block on exhaustive coverage — deliver partial findings if scope or time runs out.
