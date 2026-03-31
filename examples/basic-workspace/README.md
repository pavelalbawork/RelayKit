# Basic Workspace Example

This example shows the smallest useful RelayKit setup:

- one workspace profile
- one project profile
- one repo-local `AGENTS.md`
- one sample lane override

## Layout

- `./.relaykit/workspace-profile.json`
- `./AGENTS.md`
- `./sample-project/.relaykit/project-profile.json`
- `./sample-project/AGENTS.md`

## Try It

From the repo root:

```bash
python3 scripts/relaykit.py doctor \
  --workspace-root examples/basic-workspace \
  --project-root examples/basic-workspace/sample-project
```

Render the effective builder stack for the sample project:

```bash
python3 scripts/relaykit.py render-prompt-stack \
  --lane builder \
  --workspace-root examples/basic-workspace \
  --project-root examples/basic-workspace/sample-project
```

Render the frontend tester stack:

```bash
python3 scripts/relaykit.py render-prompt-stack \
  --lane frontend-tester \
  --workspace-root examples/basic-workspace \
  --project-root examples/basic-workspace/sample-project
```

## What It Demonstrates

- workspace onboarding can stay minimal
- project onboarding can inherit defaults
- lane overrides stay local to the project that needs them
- personas stay optional overlays, not global protocol law
