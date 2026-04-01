# Basic Workspace Example

This example shows a complete RelayKit workspace setup with a real project and a full task walkthrough.

## Walkthrough

For a step-by-step end-to-end example — intake, clarification, recommendation, builder lane, checkpoint, reflect — see [WALKTHROUGH.md](./WALKTHROUGH.md).

## Layout

```
basic-workspace/
├── .relaykit/workspace-profile.json   # workspace defaults
├── AGENTS.md                          # workspace-level rules
├── WALKTHROUGH.md                     # end-to-end task lifecycle example
└── sample-project/
    ├── .relaykit/
    │   ├── project-profile.json       # project overrides
    │   └── tasks/task-001/state.json  # example completed task state
    ├── AGENTS.md                      # project rules and verification target
    └── src/
        ├── auth.py                    # example implementation target
        └── test_auth.py               # tests
```

## Try It

Install RelayKit first (see the main README). Then from this directory:

```bash
relaykit doctor --workspace-root .
```

Render the effective prompt stack for the builder lane:

```bash
relaykit advanced render-prompt-stack \
  --lane builder \
  --workspace-root . \
  --project-root sample-project
```

Run a full task lifecycle against the sample project:

```bash
relaykit start-task \
  --workspace-root . \
  --project-root sample-project \
  --task "Add input validation to the login function"
```

## What It Demonstrates

- workspace onboarding can stay minimal — one profile, one AGENTS.md
- project onboarding inherits workspace defaults and only overrides what differs
- a completed task state (task-001) shows exactly what RelayKit persists
- the walkthrough shows how a real task flows from intake to reflection
