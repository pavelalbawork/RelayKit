from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PACKAGE_ROOT.parents[1]
BUNDLE_ROOT = PACKAGE_ROOT / "_bundle"


def _has_runtime_root(root: Path) -> bool:
    return (
        (root / "scripts" / "relaykit.py").exists()
        and (root / "config" / "registry.json").exists()
        and (root / "skills").exists()
    )


def runtime_root() -> Path:
    if _has_runtime_root(SOURCE_ROOT):
        return SOURCE_ROOT
    return BUNDLE_ROOT


def bundle_root() -> Path:
    return BUNDLE_ROOT


def using_source_runtime() -> bool:
    return _has_runtime_root(SOURCE_ROOT)
