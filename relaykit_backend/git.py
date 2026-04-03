"""Optional git integration for RelayKit task lanes.

All functions are safe to call even when git is unavailable — they return
None or empty results instead of raising.  The module is only activated
when the workspace or project profile sets ``git_integration: true``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def is_git_repo(path: Path) -> bool:
    """Return True if *path* is inside a git working tree."""
    result = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path)
    return result.returncode == 0 and result.stdout.strip() == "true"


def current_branch(repo: Path) -> str | None:
    """Return the current branch name, or None if detached / not a repo."""
    result = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    if result.returncode != 0:
        return None
    name = result.stdout.strip()
    return None if name == "HEAD" else name


def branch_exists(repo: Path, branch: str) -> bool:
    result = _run(["git", "rev-parse", "--verify", f"refs/heads/{branch}"], cwd=repo)
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Branch lifecycle
# ---------------------------------------------------------------------------

def part_branch_name(task_id: str, part_id: str) -> str:
    """Deterministic branch name for a task part."""
    return f"relaykit/{task_id}/{part_id}"


def create_part_branch(
    repo: Path,
    task_id: str,
    part_id: str,
    base_branch: str | None = None,
) -> str | None:
    """Create a branch for a task part.  Returns the branch name or None on failure."""
    name = part_branch_name(task_id, part_id)
    if branch_exists(repo, name):
        return name
    base = base_branch or current_branch(repo) or "HEAD"
    result = _run(["git", "branch", name, base], cwd=repo)
    if result.returncode != 0:
        return None
    return name


def delete_part_branch(repo: Path, task_id: str, part_id: str) -> bool:
    """Delete a task-part branch.  Returns True on success."""
    name = part_branch_name(task_id, part_id)
    if not branch_exists(repo, name):
        return True
    result = _run(["git", "branch", "-D", name], cwd=repo)
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Diff / stats
# ---------------------------------------------------------------------------

def diff_stat(repo: Path, branch: str) -> dict[str, Any] | None:
    """Return diff stats between *branch* and its merge-base with the current branch.

    Returns None if git is unavailable or the branch doesn't exist.
    """
    base_result = _run(["git", "merge-base", "HEAD", branch], cwd=repo)
    if base_result.returncode != 0:
        return None
    merge_base = base_result.stdout.strip()
    stat_result = _run(["git", "diff", "--stat", merge_base, branch], cwd=repo)
    if stat_result.returncode != 0:
        return None
    files_result = _run(["git", "diff", "--name-only", merge_base, branch], cwd=repo)
    files = [f for f in files_result.stdout.strip().splitlines() if f] if files_result.returncode == 0 else []
    return {
        "branch": branch,
        "merge_base": merge_base,
        "stat": stat_result.stdout.strip(),
        "files_changed": files,
    }


def part_diff_stat(repo: Path, task_id: str, part_id: str) -> dict[str, Any] | None:
    """Convenience wrapper: diff stats for a task-part branch."""
    name = part_branch_name(task_id, part_id)
    if not branch_exists(repo, name):
        return None
    return diff_stat(repo, name)


# ---------------------------------------------------------------------------
# Resolution helper
# ---------------------------------------------------------------------------

def resolve_git_config(
    workspace_profile: dict[str, Any] | None,
    project_profile: dict[str, Any] | None,
) -> bool:
    """Return whether git integration is enabled.

    Project profile overrides workspace profile.  Default is False.
    """
    enabled = False
    if workspace_profile:
        enabled = workspace_profile.get("git_integration", False)
    if project_profile and "git_integration" in project_profile:
        enabled = project_profile["git_integration"]
    return bool(enabled)
