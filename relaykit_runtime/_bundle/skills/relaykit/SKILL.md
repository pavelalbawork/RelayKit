---
name: relaykit
description: Use when you want RelayKit to augment Codex, Claude Code, Antigravity, or Gemini CLI for multi-tool, human-in-the-loop parallel execution, starting from task intake and ending in the right lane assignments.
license: MIT
compatibility:
  hosts:
    - Codex
    - Claude Code
    - Antigravity
    - Gemini CLI
    - Generic file-based skill hosts
metadata:
  version: 0.2.0
  relaykit_kind: entry
  invocation: explicit
---

# RelayKit

Use this as the entry skill for the RelayKit pack.

This skill does not replace the role skills. It chooses and loads them cleanly so multiple harnesses can behave like one operator-directed system.

## When To Use It

- the workspace has not been onboarded into RelayKit yet
- the host should use the RelayKit intake flow before committing to lane assignments
- the task needs a portable setup recommendation instead of a tool-bound role assumption
- the operator wants multi-tool work to stay explicitly human-directed
- you want to load the RelayKit role pack from a skill-aware host

## Read Order

1. Repo `AGENTS.md`
2. Active packet, handoff, plan, or repo guide if one exists
3. Existing `.relaykit/workspace-profile.json` or `.relaykit/project-profile.json` if present

## Core Workflow

1. Run `relaykit start-task --workspace-root <root> --task "<task>" [--project-root <project>]`.
2. Keep answering `answer-task` until RelayKit returns a recommendation, unless the user explicitly wants to skip the question phase.
3. Confirm the recommendation with `confirm-task`, or request changes.
4. If the task is continuing in full mode, use `checkpoint-task`, `advance-task`, `resume-task`, and `reflect-task` as needed.
5. Load the matching role skill, host guide, model note, persona, packet, or repo guide from the resolved task parts.

## Practical Rule

Prefer the RelayKit MCP server when the host can call tools directly and should own the wiring and onboarding flow.

Prefer the CLI when the host is shell-first.

Use `render-task-part` for current task-part launch bundles.

Use `advanced stack` or `advanced render-prompt-stack` only when you already know the exact lane or host assignment and do not need the intake flow.

## Stop Rules

- Do not hard-bind a role to one tool when RelayKit can recommend a better multi-harness setup.
- Do not skip the clarification phase unless the user explicitly asks to do so.
- Do not dump the whole protocol into context if the resolved task parts already give the minimal load order.
