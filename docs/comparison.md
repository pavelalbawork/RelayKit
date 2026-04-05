# RelayKit vs RelayPack

## Summary

Both are about harness augmentation for multi-tool, human-in-the-loop parallel execution.

The difference is simple:

- `RelayKit` is the product you install and use day to day.
- `RelayPack` is the broader maintainer/runtime surface for validation, experiments, and protocol-heavy comparison work.

## Comparison Table

| Dimension | RelayKit | RelayPack |
|---|---|---|
| Best for | Daily operator use | Maintainers and comparison work |
| Main focus | Product workflow | Validation, experiments, and broader runtime surfaces |
| Runtime surfaces | CLI, MCP, skills, profiles | CLI, MCP, skills, profiles, validation, protocol fixtures |
| Onboarding | Cleaner first-use path | Broader host and runtime comparison work |
| Docs posture | Product-oriented | More protocol- and maintainer-oriented |

## Practical Rule

Use `RelayKit` when you want the cleanest product for coordinating multiple harnesses.

Use `RelayPack` when you need:

- validation suites
- host adaptation experiments
- comparison work
- protocol-heavy maintainer surfaces
