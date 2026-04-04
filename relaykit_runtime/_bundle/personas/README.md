# Personas

Optional style/expertise overlays for lanes. Never required.

## Included

| Persona | Effect |
|---|---|
| `pragmatic-builder` | Biases toward practical delivery and tight scope |
| `stern-architect` | Pushes harder architectural scrutiny |
| `reality-checker` | Adds skeptical evidence-first pressure |
| `design-critic` | Sharper hierarchy and interaction quality for UI |

## Usage

```bash
# Use a registered persona
relaykit advanced stack --lane critic --workspace-root . --persona reality-checker

# Use a custom file
relaykit advanced stack --lane builder --workspace-root . --persona-path ./my-persona.md
```

Set workspace defaults in `.relaykit/workspace-profile.json`.

## Writing Personas

Keep them short. A persona adds principles and style pressure, not workflows.

Scaffold one:

```bash
relaykit init-persona \
  --name "My Persona" \
  --description "What it does." \
  --kind style \
  --role reviewer \
  --principle "first principle" \
  --dry-run
```
