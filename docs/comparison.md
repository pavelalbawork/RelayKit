# RelayKit vs RelayPack

## Summary

Both products are about harness augmentation for multi-tool, human-in-the-loop parallel execution.

They serve different use cases:

- `RelayKit` is a focused product surface for day-to-day harness augmentation.
- `RelayPack` is an expanded runtime with more validation, protocol, and experimentation surfaces.

## Comparison Table

| Dimension | RelayKit | RelayPack |
|---|---|---|
| Primary role | Focused product surface | Expanded runtime surface |
| Default use | Daily install and product surface | Validation, comparison, experimentation, protocol-heavy work |
| Main story | Harness augmentation under operator control | Harness augmentation plus validator lab and canon |
| Runtime surfaces | CLI, MCP, skills, profiles | CLI, MCP, skills, profiles, validation, protocol fixtures |
| Onboarding | Product-facing harness onboarding | Product-facing onboarding plus broader host/runtime experiments |
| Docs posture | Cleaner public surface | Larger and more protocol-heavy |
| Share with users | Yes, by default | When they need the broader runtime surface |

## Practical Rule

Use `RelayKit` when you want the cleanest product for coordinating multiple harnesses.

Use `RelayPack` when you need:

- protocol canon
- larger validation flows
- host adaptation experiments
- comparison work

## Install Pattern

You can install both into the same environment and compare them directly:

```bash
python -m pip install -e /Users/palba/Projects/Orchestration/RelayKit
python -m pip install -e /Users/palba/Projects/Orchestration/RelayPack
relaykit --version
relaypack --version
```
