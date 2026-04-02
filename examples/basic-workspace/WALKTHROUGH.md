# RelayKit Walkthrough

This is a complete end-to-end example of a RelayKit task lifecycle using the `sample-project` in this directory.

**Project:** A Python auth module (`src/auth.py`) with tests (`src/test_auth.py`).
**Task:** Add rate limiting to the login function.

---

## Prerequisites

Install RelayKit and create a workspace profile:

```bash
pipx install -e /path/to/relaykit

cd examples/basic-workspace
relaykit init-workspace --workspace-root . --start-with-defaults
relaykit doctor --workspace-root .
```

---

## Step 1: Start a task

```bash
relaykit start-task \
  --workspace-root . \
  --project-root sample-project \
  --task "Add rate limiting to the login endpoint so it blocks after 5 failed attempts"
```

**Output:**
```json
{
  "task_id": "task-001",
  "status": "clarifying",
  "question": "Is this change limited to the Python backend, or does it also need a frontend message or redirect when the limit is hit?"
}
```

RelayKit detected a backend task and is asking whether frontend work is in scope.

---

## Step 2: Answer clarification questions

```bash
relaykit answer-task \
  --workspace-root . \
  --task-id task-001 \
  --answer "Backend only. No frontend changes needed."
```

**Output:**
```json
{
  "task_id": "task-001",
  "status": "clarifying",
  "question": "Should the rate limit be enforced per email address, per IP address, or both?"
}
```

```bash
relaykit answer-task \
  --workspace-root . \
  --task-id task-001 \
  --answer "Per email address is enough for now."
```

**Output:**
```json
{
  "task_id": "task-001",
  "status": "recommending",
  "archetype": "backend",
  "coordination": "solo",
  "continuity": "lean",
  "confidence": "high",
  "recommendation": {
    "summary": "Single builder lane. No coordination overhead needed for a single-file backend change.",
    "task_parts": [
      {
        "part_id": "part-1",
        "role": "builder",
        "skill": "contributor",
        "host": "codex",
        "model": "gpt-5.4",
        "reasoning_effort": "high",
        "personas": ["pragmatic-builder"],
        "objective": "Add a rate limiter to the login function in src/auth.py that blocks after 5 failed attempts per email within a 15-minute window. Update tests in src/test_auth.py.",
        "allowed_scope": ["src/auth.py", "src/test_auth.py"],
        "verification_target": "python3 -m unittest discover -s src -p 'test_*.py' -v passes with no failures"
      }
    ]
  }
}
```

RelayKit classified this as a solo backend task and recommended a single builder lane on Codex.

---

## Step 3: Confirm the recommendation

```bash
relaykit confirm-task \
  --workspace-root . \
  --task-id task-001 \
  --accept
```

**Output:**
```json
{
  "task_id": "task-001",
  "status": "confirmed",
  "next_command": "relaykit render-task-part --workspace-root . --task-id task-001 --part-id part-1"
}
```

---

## Step 4: Render the launch bundle and hand off to the builder lane

```bash
relaykit render-task-part \
  --workspace-root . \
  --task-id task-001 \
  --part-id part-1
```

**Output** (a markdown block ready to paste into Codex):
```markdown
## Task Part: part-1

**Role:** builder
**Skill:** relaykit-contributor
**Host:** Codex
**Model:** gpt-5.4 (reasoning_effort: high)
**Persona:** pragmatic-builder

### Objective
Add a rate limiter to the login function in `src/auth.py` that blocks after 5
failed attempts per email within a 15-minute window. Update tests in
`src/test_auth.py` to cover the new behaviour.

### Allowed Scope
- src/auth.py
- src/test_auth.py

### Excluded Scope
- Any file outside src/

### Verification Target
`python3 -m unittest discover -s src -p 'test_*.py' -v` passes with no failures.

### Stop Condition
Rate limiter implemented, tests pass, no scope expansion.
```

Paste this into Codex (or the harness of your choice) and let it execute.

---

## Step 5: Checkpoint when the builder is done

Once Codex reports the implementation is complete:

```bash
relaykit checkpoint-task \
  --workspace-root . \
  --task-id task-001 \
  --notes "Rate limiter added using in-memory dict. login() now raises RateLimitError after 5 failures. Tests updated — all passing."
```

**Output:**
```json
{
  "task_id": "task-001",
  "checkpoint_id": "cp-1",
  "outcome": "ready_for_next_phase",
  "recommended_action": "reflect",
  "summary": "Work is complete and verified. Ready to reflect and close."
}
```

---

## Step 6: Reflect and close

```bash
relaykit reflect-task \
  --workspace-root . \
  --task-id task-001 \
  --split-worth-it no \
  --tool-fit good \
  --simpler-better no \
  --apply
```

**Output:**
```json
{
  "task_id": "task-001",
  "status": "reflected",
  "learning": "Solo builder lane was the right call. No coordination overhead needed for a single-file change. Pragmatic-builder persona was a good fit."
}
```

RelayKit records this in `.relaykit/learning-log.jsonl` and uses it to refine lane recommendations for similar future tasks.

---

## Inspect the task state

At any point you can inspect the full task state:

```bash
relaykit show-task --workspace-root . --task-id task-001
```

The full state file is also available directly:

```
sample-project/.relaykit/tasks/task-001/state.json
```

See the pre-generated example in this directory to understand the structure.

---

## What RelayKit learned

After reflecting, the learning log gets an entry:

```jsonl
{"task_id": "task-001", "archetype": "backend", "coordination": "solo", "continuity": "lean", "split_worth_it": false, "tool_fit": "good", "simpler_better": false, "timestamp": "2026-04-01T10:45:00Z"}
```

Next time you start a similar backend task, RelayKit will more confidently recommend a solo lean setup without asking as many clarification questions.

---

## When you'd get a different recommendation

Change the task and RelayKit routes differently:

| Task description | Archetype | Coordination | Lanes |
|---|---|---|---|
| "Add rate limiting to login" | backend | solo | builder |
| "Redesign the login page" | frontend | solo | builder + tester |
| "Audit all auth flows for security issues" | review-hardening | coordinated | orchestrator + critic |
| "Research whether OAuth2 is better than our current approach" | research-heavy | solo | researcher |
| "Migrate auth to a new service across 3 repos" | cross-project | coordinated | orchestrator + builder + builder |
