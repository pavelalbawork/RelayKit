# Skills

## What Skills Are

Skills are portable prompt assets that define how a role should behave. They ship as markdown files with YAML frontmatter and work across any host that can load file-based skills.

## Included Skills

| Skill | Role | When to use |
|---|---|---|
| `relaykit` | entry | Task intake, setup recommendation, skill dispatch |
| `relaykit-orchestrator` | orchestrator | Routing, sequencing, checkpointing, convergence |
| `relaykit-contributor` | builder | Implementation, repo editing, verification |
| `relaykit-critic` | critic | Challenge and critique without ownership transfer |

## How Skills Load

The entry skill (`relaykit`) drives the task-first flow. After setup confirmation, it loads the matching role skill for each task part.

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

## Writing Custom Skills

A skill file needs:
1. YAML frontmatter with `name`, `description`, `metadata.relaykit_kind`, `metadata.relaykit_role`
2. A "When To Use It" section
3. A "Read Order" section
4. A "Core Workflow" section
5. "Stop Rules" to prevent scope creep

See the included skills in `skills/` for examples.
