# RelayKit Testing Guide

## Prerequisites

- Python 3.11+
- Git
- Access to at least one of: Codex, Claude Code, Gemini CLI, Antigravity

## Installation

**Recommended — `pipx` (no activation needed):**

```bash
pipx install -e /path/to/relaykit
relaykit --version
relaykit-mcp --help
```

This is the preferred path for Codex, Claude Code, Gemini CLI, and Antigravity because it gives every harness the same stable `relaykit-mcp` command.

**Fastest first-use path after install:**

```bash
relaykit setup --host codex
```

Swap `codex` for `claude-code`, `gemini-cli`, or `antigravity`. `setup` bootstraps the host, runs a safe local smoke flow, and prints the exact next prompt for that harness.

**Fallback — one command, venv-safe:**

```bash
cd /path/to/relaykit
python3 scripts/relaykit.py install-self
```

Use this when `pipx` is unavailable or Homebrew Python blocks ambient package installation.

**Fallback — manual venv:**

```bash
cd /path/to/relaykit
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
relaykit --version
relaykit-mcp --help
```

## Registry Setup

The shipped registry already includes Codex, Claude Code, Gemini CLI, and Antigravity with the supported model notes and host guides. You should not need to hand-edit `config/registry.json` before normal testing.

## Setup: Create a Test Workspace

```bash
mkdir -p /tmp/relaykit-test
cd /tmp/relaykit-test
relaykit init-workspace --workspace-root .
# Follow the prompts — list your available hosts and models
relaykit doctor --workspace-root .
# Should show status: ok for registry and workspace
```

---

## Test Case 1: Codex via MCP

**Goal:** Verify the full task flow works when driven from Codex through the MCP server.

### Step 1: Configure the MCP server in Codex

Prefer the built-in onboarding path first:

```bash
relaykit setup --host codex --dry-run
relaykit setup --host codex --force
```

If you need to wire Codex manually, add this to its MCP config:

If installed via `pipx`:

```json
{
  "mcpServers": {
    "relaykit": {
      "command": "relaykit-mcp"
    }
  }
}
```

If installed via venv, use the full path instead:

```json
{
  "mcpServers": {
    "relaykit": {
      "command": "/path/to/relaykit/.venv/bin/relaykit-mcp"
    }
  }
}
```

### Step 2: Install skills (optional, for skill-first flow)

```bash
cp -r /Users/palba/Projects/Orchestration/RelayKit/skills/* ~/.codex/skills/ 2>/dev/null || echo "Create ~/.codex/skills/ first"
```

`setup --host codex --force` can do this automatically for supported hosts, so manual copying should usually be unnecessary.

### Step 3: Run the test from Codex

Open Codex and run these MCP tool calls (or ask Codex to run them):

```
1. Call relaykit_doctor with workspace_root="/tmp/relaykit-test"
   Expected: status ok for registry and workspace

2. Call relaykit_start_task with:
   - workspace_root: "/tmp/relaykit-test"
   - task: "Add input validation to the signup form"
   Expected: Returns task_id and first clarification question

3. Call relaykit_answer_task with:
   - workspace_root: "/tmp/relaykit-test"
   - task_id: <from step 2>
   - answer: "Only validate email and password fields"
   Expected: Returns next question

4. Call relaykit_answer_task with:
   - workspace_root: "/tmp/relaykit-test"
   - task_id: <from step 2>
   - skip_clarification: true
   Expected: Returns recommendation with archetype, setup, and task_parts

5. Call relaykit_confirm_task with:
   - workspace_root: "/tmp/relaykit-test"
   - task_id: <from step 2>
   - accept: true
   Expected: Returns confirmed plan

6. Call relaykit_checkpoint_task with:
   - workspace_root: "/tmp/relaykit-test"
   - task_id: <from step 2>
   - notes: "Email regex validation done, password rules next"
   Expected: Returns checkpoint with recommended_outcome

7. Call relaykit_reflect_task with:
   - workspace_root: "/tmp/relaykit-test"
   - task_id: <from step 2>
   - split_worth_it: "no"
   - tool_fit: "good"
   - simpler_better: "no"
   - apply: true
   Expected: Returns reflection confirmation
```

### Pass criteria

- All 7 steps complete without errors
- Task state files exist under `/tmp/relaykit-test/.relaykit/tasks/<task-id>/`
- Learning log entry written to `/tmp/relaykit-test/.relaykit/learning-log.jsonl`

---

## Test Case 2: Gemini CLI via MCP + Skills

**Goal:** Verify the full host-wired flow works from Gemini CLI with RelayKit-managed MCP wiring and skills.

### Step 1: Bootstrap Gemini CLI

```bash
relaykit bootstrap-host --host gemini-cli --dry-run
relaykit bootstrap-host --host gemini-cli --force
gemini mcp list
```

### Step 2: Create a test workspace

```bash
mkdir -p /tmp/relaykit-gemini-test
cd /tmp/relaykit-gemini-test
relaykit init-workspace --workspace-root .
relaykit doctor --workspace-root .
```

### Step 3: Run the test from Gemini CLI

Open Gemini CLI in `/tmp/relaykit-gemini-test` and use either the RelayKit MCP tools directly or the RelayKit skill:

```
Prompt 1: "Call relaykit_start_task for: Refactor the database queries to use connection pooling"
Expected: Gemini uses the MCP tool, returns first question

Prompt 2: "Answer: Only refactor queries in db.py, don't change the schema"
Expected: Runs answer-task, returns next question

Prompt 3: "Skip remaining questions"
Expected: Runs answer-task --skip, returns recommendation

Prompt 4: "Accept the recommendation"
Expected: Runs confirm-task --accept, returns confirmed plan

Prompt 5: "Checkpoint: connection pool initialized, query migration in progress"
Expected: Runs checkpoint-task, returns checkpoint outcome

Prompt 6: "Reflect: the setup worked well, tool fit was good, no simpler setup needed"
Expected: Runs reflect-task, records learning
```

### Pass criteria

- All 6 prompts complete without errors
- Gemini CLI exposes the RelayKit MCP tools after bootstrap
- Task state persists in `/tmp/relaykit-gemini-test/.relaykit/tasks/`
- Learning log gets an entry

---

## Quick CLI Smoke Test (No External Host)

If you want to verify the core runtime without Codex or Gemini:

```bash
cd /tmp/relaykit-test

# Full lifecycle
TASK_ID=$(relaykit start-task --workspace-root . --task "Add rate limiting to the API" 2>&1 | python3 -c "import sys,json; print(json.load(sys.stdin)['task_id'])")
echo "Task: $TASK_ID"

relaykit answer-task --workspace-root . --task-id $TASK_ID --answer "Only the /api/auth endpoints"
relaykit answer-task --workspace-root . --task-id $TASK_ID --answer "Rate limit errors return 429"
relaykit answer-task --workspace-root . --task-id $TASK_ID --skip

relaykit confirm-task --workspace-root . --task-id $TASK_ID --accept
relaykit checkpoint-task --workspace-root . --task-id $TASK_ID --notes "Middleware added"
relaykit show-task --workspace-root . --task-id $TASK_ID
relaykit reflect-task --workspace-root . --task-id $TASK_ID \
  --split-worth-it no --tool-fit good --simpler-better no --apply

# Check artifacts
ls .relaykit/tasks/$TASK_ID/
cat .relaykit/learning-log.jsonl
```

All commands should return valid JSON without errors.
