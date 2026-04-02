# Commands

## Task Lifecycle

| Command | Purpose |
|---|---|
| `start-task` | Begin a new multi-harness task from free text |
| `answer-task` | Answer a clarification question |
| `confirm-task` | Accept or modify the recommended lane setup |
| `show-task` | View current task state and lane assignments |
| `checkpoint-task` | Record progress at a named milestone |
| `advance-task` | Apply a setup or phase change after checkpoint |
| `resume-task` | Resume a paused task with context for the active lanes |
| `render-task-part` | Render the launch bundle for one task part |
| `reflect-task` | Post-task learning: was the multi-harness setup worth it? |

## Setup

| Command | Purpose |
|---|---|
| `init-workspace` | Create a persistent workspace profile |
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

**Simple solo task:**
```bash
relaykit start-task --workspace-root . --task "Fix the auth bug"
relaykit answer-task --workspace-root . --task-id <id> --answer "Only touch auth.py"
relaykit confirm-task --workspace-root . --task-id <id> --accept
```

**Full coordinated task with checkpoints:**
```bash
relaykit start-task --workspace-root . --task "Redesign the dashboard"
# ... answer questions ...
relaykit confirm-task --workspace-root . --task-id <id> --accept
relaykit checkpoint-task --workspace-root . --task-id <id> --notes "Layout done"
relaykit advance-task --workspace-root . --task-id <id>
relaykit resume-task --workspace-root . --task-id <id>
relaykit reflect-task --workspace-root . --task-id <id> --split-worth-it yes --tool-fit good
```

## MCP Tools

The MCP server exposes the operational RelayKit commands as tools prefixed with `relaykit_`:

`relaykit_start_task`, `relaykit_answer_task`, `relaykit_confirm_task`, `relaykit_show_task`, `relaykit_checkpoint_task`, `relaykit_advance_task`, `relaykit_resume_task`, `relaykit_render_task_part`, `relaykit_reflect_task`, `relaykit_host_status`, `relaykit_setup`, `relaykit_bootstrap_host`, `relaykit_uninstall_host`, `relaykit_acknowledge_host`, `relaykit_install_self`, `relaykit_smoke`, `relaykit_doctor`, `relaykit_list`, `relaykit_preset`, `relaykit_stack`, `relaykit_render_prompt_stack`, `relaykit_init_workspace`, `relaykit_init_project`, `relaykit_init_persona`.
