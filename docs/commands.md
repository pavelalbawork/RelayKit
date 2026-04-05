# Commands

## Task Lifecycle

Task lifecycle commands default to `--format auto`, which means a concise human-readable view in an interactive terminal and JSON when stdout is redirected. Use `--format json` to force the machine payload, or `--format human` to force the operator view.

| Command | Purpose |
|---|---|
| `run` | Guided interactive shell for intake, clarification, recommendation, and confirmation |
| `start-task` | Begin a new multi-harness task from free text |
| `answer-task` | Answer a clarification question |
| `confirm-task` | Accept or modify the recommended lane setup |
| `show-task` | View current task state and lane assignments |
| `list-tasks` | Enumerate tasks under the current workspace or project storage root |
| `checkpoint-task` | Record progress at a named milestone |
| `checkpoint-phase` | Record a batch checkpoint for multiple task parts in the current phase |
| `prepare-git` | Explicitly create per-task-part git branches after confirmation |
| `advance-task` | Apply a setup or phase change after checkpoint |
| `resume-task` | Resume a paused task with operator-facing context for the active lanes |
| `resume-handoff` | Generate ready-to-send handoff packets for the remaining active task parts |
| `render-task-part` | Render one task part as an ultra-compact, compact, or verbose launch bundle |
| `render-consolidation-packet` | Generate a consolidation handoff from the latest phase checkpoints |
| `reflect-task` | Post-task learning: was the multi-harness setup worth it? |

## Setup

| Command | Purpose |
|---|---|
| `init-workspace` | Create a persistent workspace profile |
| `guided-setup` | Create a workspace profile from guided first-run answers |
| `init-project` | Create a project profile inheriting workspace defaults |
| `init-persona` | Scaffold a new persona file |
| `host-status` | Check whether a harness is ready and get onboarding actions |
| `setup` | First-use path: wire a harness, run a local smoke test, and print the next host prompt |
| `bootstrap-host` | Install RelayKit skills and supported harness wiring |
| `uninstall-host` | Remove RelayKit-managed harness wiring |
| `acknowledge-host` | Record that onboarding was offered and deferred |
| `install-self` | Create a venv, install RelayKit, and optionally wire harnesses |
| `smoke` | Run the reusable local lifecycle smoke flow without changing harness wiring |
| `doctor` | Validate registry, profiles, schemas, and optional host readiness |

## Inspection

| Command | Purpose |
|---|---|
| `list` | List skills, hosts, models, presets, personas, or lanes |
| `preset` | Show a preset or single lane configuration |
| `--version` | Show the RelayKit version |

## Advanced

| Command | Purpose |
|---|---|
| `advanced stack` | Resolve the prompt stack for a lane directly |
| `advanced render-prompt-stack` | Render a compiled prompt stack as markdown |

These bypass the intake flow. Use them only when you already know the exact lane assignment.

## Common Workflows

**Guided shell flow:**
```bash
relaykit run --workspace-root . --task "Fix the auth bug"
```

`run` is the easiest human-first entrypoint. It walks clarifications interactively, prints the verdict (`manual`, `lean`, or `full`), and then confirms or revises the setup without making you chain commands manually.

`setup` and `smoke` also default to `--format auto`, so a normal terminal gets a concise human-readable summary while redirected output stays JSON-safe. Use `--format json` when you want the raw payload.

Supported host ids:
- `codex`
- `claude-code`
- `gemini-cli`
- `antigravity`

**Simple solo task:**
```bash
relaykit start-task --workspace-root . --task "Fix the auth bug"
relaykit answer-task --workspace-root . --task-id <id> --answer "Only touch auth.py"
relaykit confirm-task --workspace-root . --task-id <id> --accept
```

**Lean coordinated task (default for small bounded two-part work):**
```bash
relaykit start-task --workspace-root . --task "Fix malformed stored hash handling in login and review the change"
# ... answer questions ...
relaykit confirm-task --workspace-root . --task-id <id> --accept
relaykit checkpoint-phase --workspace-root . --task-id <id> --reports '[{"part_id":"implementation","notes":"builder done"},{"part_id":"critique","notes":"critic agrees"}]'
relaykit render-consolidation-packet --workspace-root . --task-id <id>
relaykit reflect-task --workspace-root . --task-id <id> --split-worth-it yes --tool-fit good
```

`confirm-task` returns a `launch_bundle` automatically on lean coordinated runs, so you usually do not need separate `render-task-part` calls unless you want a verbose packet or need to re-render later. Compact launch markdown omits empty task-context fields and keeps the machine-readable handoff card in the structured payload instead of repeating it inline. The default lean launch bundle now uses `ultra-compact` handoffs to minimize packet size.

Recommendations and handoff packets now include a phase mode (`research-phase`, `review-phase`, or `implementation-phase`) plus a per-part output contract. Use that contract to keep pre-implementation work out of code lanes until the task is explicitly rerouted.

If `confirm-task` says the task should stay manual, RelayKit is telling you the protocol overhead is not worth it. Force the protocol only when you explicitly need handoffs or persistent state:

```bash
relaykit confirm-task --workspace-root . --task-id <id> --accept --force-protocol
```

**Full coordinated task with explicit per-part rendering and checkpoints:**
```bash
relaykit start-task --workspace-root . --task "Redesign the dashboard"
# ... answer questions ...
relaykit confirm-task --workspace-root . --task-id <id> --accept
relaykit render-task-part --workspace-root . --task-id <id> --part-id implementation --verbosity verbose
relaykit checkpoint-task --workspace-root . --task-id <id> --notes "Layout done"
relaykit advance-task --workspace-root . --task-id <id>
relaykit resume-task --workspace-root . --task-id <id>
relaykit reflect-task --workspace-root . --task-id <id> --split-worth-it yes --tool-fit good
```

`checkpoint-task`, `checkpoint-phase`, and `render-consolidation-packet` can now surface `phase_warnings` when outputs drift across phase boundaries, such as production code appearing in a research-first task or research claims being checkpointed without explicit sources.

RelayKit now also surfaces `drift_warnings` and `orchestration_guidance` in `show-task`, `resume-task`, and `inspect-task` when repo activity is moving faster than the orchestration state. If files are changing but the task is still only recommended, or an active phase has real work but no checkpoint yet, RelayKit will tell the operator to confirm or advance the task instead of silently lagging behind.

For critique-driven follow-up work, RelayKit now tracks source issue inventories from referenced Markdown docs and can mark reflected fix packets as `addressed-unverified`. That gives later tasks a structured issue state instead of treating every old critique line as permanently open backlog.

Operational rule:
- run `confirm-task` before real work starts
- run `checkpoint-task` or `checkpoint-phase` after the first concrete artifact, blocker, or verified finding
- run `advance-task` as soon as RelayKit says `blocked`, `needs_reroute`, or `ready_for_next_phase`
- if `show-task` or `resume-task` returns `required_action`, do that next instead of continuing off-ledger
- when using the MCP server, summarize RelayKit’s human-readable result for the user instead of echoing raw payloads

**Interrupted lean task:**
```bash
relaykit resume-task --workspace-root . --task-id <id>
relaykit resume-handoff --workspace-root . --task-id <id>
```

Use `resume-task` for the operator summary and `resume-handoff` when you need the remaining-part launch packets directly.

**Remove RelayKit from a machine completely:**
```bash
relaykit uninstall-host --host codex
relaykit uninstall-host --host claude-code
relaykit uninstall-host --host gemini-cli
relaykit uninstall-host --host antigravity
pipx uninstall relaykit
rm -rf ~/.claude/skills/relaykit*
rm -rf ~/.gemini/skills/relaykit*
rm -rf ~/.codex/skills/relaykit*
```

Only remove the skill folders if you copied them manually with the skills-only fallback.

**Wire every supported host in one pass:**
```bash
relaykit setup --all-hosts
```

You can also repeat `--host`:

```bash
relaykit setup --host codex --host claude-code --host gemini-cli --host antigravity
```

## MCP Tools

The MCP server exposes the operational RelayKit commands as tools prefixed with `relaykit_`:

`relaykit_start_task`, `relaykit_answer_task`, `relaykit_confirm_task`, `relaykit_show_task`, `relaykit_list_tasks`, `relaykit_checkpoint_task`, `relaykit_checkpoint_phase`, `relaykit_prepare_git`, `relaykit_advance_task`, `relaykit_resume_task`, `relaykit_resume_handoff`, `relaykit_render_task_part`, `relaykit_render_consolidation_packet`, `relaykit_reflect_task`, `relaykit_host_status`, `relaykit_guided_setup`, `relaykit_setup`, `relaykit_bootstrap_host`, `relaykit_uninstall_host`, `relaykit_acknowledge_host`, `relaykit_install_self`, `relaykit_smoke`, `relaykit_doctor`, `relaykit_list`, `relaykit_preset`, `relaykit_stack`, `relaykit_render_prompt_stack`, `relaykit_init_workspace`, `relaykit_init_project`, `relaykit_init_persona`.

For the main lifecycle tools, MCP text content is now human-readable by default and structured content still carries the full payload. Agents should prefer the human summary unless the user explicitly asks for raw JSON.
