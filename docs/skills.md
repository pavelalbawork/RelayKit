# Skills

## What Skills Are

Skills are portable prompt assets that define how a role should behave. They ship as markdown files with YAML frontmatter and work across any harness that can load file-based skills.

## Included Skills

| Skill | Role | When to use |
|---|---|---|
| `relaykit` | entry | Task intake, lane recommendation, skill dispatch |
| `relaykit-orchestrator` | orchestrator | Lane planning, sequencing, checkpointing, convergence |
| `relaykit-contributor` | builder | Implementation, repo editing, verification |
| `relaykit-critic` | critic | Advisory challenge without ownership transfer |
| `relaykit-converger` | converger | Compare competing outputs and drive a final convergence decision |
| `relaykit-reviewer` | reviewer | Gate review with explicit pass/fail authority |
| `relaykit-researcher` | researcher | Evidence gathering and synthesis before execution |
| `relaykit-tester` | tester | Verification against acceptance criteria, concrete pass/fail |

## Updating Skills

Skills ship with the product. Do not edit skill files installed in harness homes directly — reinstall from the product to update them.

## How Skills Load

The entry skill (`relaykit`) drives the intake flow. After setup confirmation, it loads the matching role skill for each task part.

Each role skill defines:
- When to use it
- What to read first
- Core workflow steps
- Output contract
- Stop rules

## Installing Skills

Install the skill pack into a file-based skill home:

```bash
# Codex
cp -r skills/ ~/.codex/skills/

# Claude Code
cp -r skills/ ~/.claude/skills/

# Gemini CLI
cp -r skills/ ~/.gemini/skills/
```

If the harness can call MCP tools directly, prefer `relaykit_host_status` plus `relaykit_bootstrap_host` so the harness owns the wiring instead of the user editing config by hand.

## Writing Custom Skills

A skill file needs:
1. YAML frontmatter with `name`, `description`, `metadata.relaykit_kind`, `metadata.relaykit_role`
2. A "When To Use It" section
3. A "Read Order" section
4. A "Core Workflow" section
5. "Stop Rules" to prevent scope creep

See the included skills in `skills/` for examples.
