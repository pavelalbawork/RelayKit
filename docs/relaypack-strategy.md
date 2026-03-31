# RelayKit And RelayPack

## Roles

- `RelayKit` is the smaller canonical product.
- `RelayPack` is the larger comparison and incubation runtime currently housed in `/Users/palba/Projects/OperatorProtocol`.

The product rule is simple:

- new public behavior should land in `RelayKit` only when it clearly improves the small product
- larger ideas can live in `RelayPack` until they prove they belong

## Running Both

Right now the two repos still share internal Python module names like `scripts`, `mcp`, and `relaykit_backend`.

That means:

- you can install both repos into the same Python environment
- `RelayKit` owns the `relaykit` command
- `RelayPack` owns the `relaypack` command
- direct repo execution is still useful when you want to run the larger runtime straight from source

Practical comparison patterns:

```bash
# canonical product
cd /Users/palba/Projects/relaykit
python3 -m pip install -e .
relaykit --version
```

```bash
# larger comparison runtime in the same environment
cd /Users/palba/Projects/OperatorProtocol
python3 -m pip install -e .
relaypack --version
```

```bash
# larger comparison runtime, direct repo execution
cd /Users/palba/Projects/OperatorProtocol
python3 scripts/relaypack.py --version
python3 mcp/relaypack/server.py
```

## Promotion Path

Features should move from `RelayPack` into `RelayKit` only through an explicit promotion decision.

Use this ladder:

1. `candidate`
   Lives only in RelayPack.
2. `shadow`
   RelayKit gets only the schema or interface shape.
3. `promoted`
   RelayKit gets implementation, docs, and tests.
4. `canonical`
   RelayKit owns the feature. RelayPack either drops it or treats RelayKit as the authority.

## Promotion Rules

Promote only when all four are true:

- the feature has clear user value
- the module boundary is clean
- it does not bloat the default product path
- its tests and docs can move with it

## What Should Usually Stay In RelayPack

- protocol-heavy experimentation
- larger validation harnesses
- wrapper and host lab work
- risky routing experiments
- features that still need incubation

## What Should Usually Land In RelayKit

- cleaner task-first UX
- simpler state and checkpoint flows
- durable profiles and schemas
- stable MCP and CLI surfaces
- small, high-confidence personas and templates
