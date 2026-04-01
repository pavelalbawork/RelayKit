# RelayKit Subset Policy

`RelayKit` is the smaller canonical product, but it is still a subset of `RelayPack` canon.

That means `RelayKit` should not drift into its own parallel authority.

## Core Rule

Stable RelayKit behavior should be authored in `RelayPack` first, then mirrored into `RelayKit`.

If you change a mirrored surface directly in `RelayKit`, you must promote that change back into `RelayPack` immediately and re-sync. Otherwise the repos drift.

## Current Mirror Surfaces

RelayKit currently receives mirrored content from RelayPack for:

- role skills
- selected product-facing docs and messaging surfaces
- selected example assets

Those mirrors are validated from the RelayPack side.

## Practical Rule

Use `RelayKit` as the smaller product surface.

Use `RelayPack` as the authoring authority for anything that should survive and stay in sync.

For public-facing product copy, keep the relationship invisible:

- RelayKit should read as a complete product
- mirror and subset mechanics stay in maintainer-only surfaces
