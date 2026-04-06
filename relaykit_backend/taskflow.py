from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import secrets
from typing import Any

from . import git as git_module
from relaykit_runtime.layout import runtime_root


TASKFLOW_VERSION = 1
REPO_ROOT = runtime_root()
TASKS_DIRNAME = "tasks"
LEARNING_LOG_FILENAME = "learning-log.jsonl"
LEARNING_SUMMARY_FILENAME = "learned-tendencies.json"

QUALITY_POSTURES = {"balanced", "cost-aware", "quality-first", "speed-first"}
CHECKPOINT_OUTCOMES = {"on_track", "blocked", "needs_reroute", "ready_for_next_phase", "failed", "abandoned"}
CHECKPOINT_ACTIONS = {
    "keep_setup",
    "simplify_setup",
    "expand_setup",
    "change_setup",
    "move_to_next_phase",
    "pause_for_research",
    "stop",
}
CHANGE_REASONS = {"stage_change", "setup_underperformed", "new_information", "scope_change", "none"}
REFLECTION_VALUES = {"yes", "no", "mixed", "unknown"}
TOOL_FIT_VALUES = {"good", "bad", "mixed", "unknown"}
HANDOFF_VERBOSITIES = {"ultra-compact", "compact", "verbose"}
RESUME_VERBOSITIES = {"compact", "verbose"}
RESULT_VERBOSITIES = {"compact", "verbose"}
PHASE_MODES = {"review-phase", "research-phase", "implementation-phase"}
INTAKE_MODES = {"auto", "guided", "manual"}
TOOL_COST = {
    "gpt-5.4": "high",
    "gpt-5.4-mini": "low",
    "opus-4.6": "high",
    "sonnet-4.6": "medium",
    "gemini-3.1-pro": "medium",
    "gemini-3.1-flash": "low",
}
ROLE_TO_SKILL = {
    "orchestrator": "orchestrator",
    "planner": "orchestrator",
    "builder": "contributor",
    "critic": "critic",
    "reviewer": "reviewer",
    "tester": "tester",
    "researcher": "researcher",
    "converger": "converger",
}
FRONTEND_KEYWORDS = {
    "frontend",
    "ui",
    "ux",
    "design",
    "browser",
    "playwright",
    "react",
    "css",
    "layout",
    "component",
    "tailwind",
    "page",
}
BACKEND_KEYWORDS = {
    "api",
    "server",
    "storage",
    "database",
    "migration",
    "transport",
    "integration",
    "service",
}
SECURITY_KEYWORDS = {
    "security",
    "auth",
    "oauth",
    "credential",
    "credentials",
    "secret",
    "token",
    "keychain",
    "permission",
}
CLEANUP_KEYWORDS = {
    "cleanup",
    "housekeeping",
    "stale",
    "empty dir",
    "remove",
    "delete",
    "tidy",
    "prune",
}
CROSS_PROJECT_KEYWORDS = {
    "cross-project",
    "cross project",
    "across projects",
    "across repos",
    "multiple projects",
    "multiple repos",
    "multi-project",
    "multi project",
    "portfolio",
}
REVIEW_KEYWORDS = {
    "review",
    "critic",
    "critique",
    "audit",
    "hardening",
    "qa",
    "feedback",
}
RESEARCH_KEYWORDS = {
    "research",
    "investigate",
    "explore",
    "compare",
    "unclear",
    "unknown",
    "figure out",
    "decide",
    "evaluate",
    "analyze",
    "design decisions",
    "architecture decisions",
    "technical spike",
    "spike",
    "consolidate",
    "synthesis",
}
PLANNING_KEYWORDS = {
    "plan",
    "planning",
    "implementation plan",
    "decision-complete",
    "decision complete",
    "transport choices",
    "fallback order",
    "onboarding model",
    "migration approach",
    "test strategy",
    "architecture",
    "state model",
}
IMPLEMENTATION_KEYWORDS = {
    "build",
    "implement",
    "fix",
    "write",
    "code",
    "refactor",
    "create",
    "ship",
    "develop",
    "edit",
}
BUGFIX_KEYWORDS = {"bug", "fix", "broken", "regression"}
PAUSE_KEYWORDS = {"resume", "continue later", "checkpoint", "pick up later"}
PRE_IMPLEMENTATION_PATTERNS = (
    r"\bpre(?:-|\s)implementation\b",
    r"\bresearch(?:-|\s)?first\b",
    r"\bbefore (?:any )?(?:implementation|coding|execution|development) (?:starts?|begins?)\b",
    r"\bbefore (?:implementing|building|coding)\b",
    r"\bno implementation yet\b",
    r"\bdon['’]?t (?:implement|build|code) yet\b",
    r"\ball decisions must be made before any implementation starts\b",
    r"\bimplementation-ready brief\b",
)
OUT_OF_SCOPE_PATTERNS = (
    r"\bout of scope\s*:\s*.*",
    r"\bnot in scope\s*:\s*.*",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _term_pattern(term: str) -> str:
    escaped = re.escape(term)
    escaped = escaped.replace(r"\ ", r"\s+")
    escaped = escaped.replace(r"\-", r"(?:-|\s)")
    return rf"(?<!\w){escaped}(?!\w)"


def _text_contains_term(text: str, term: str) -> bool:
    return re.search(_term_pattern(term), text) is not None


def _keyword_matches(text: str, keywords: set[str]) -> list[str]:
    return [keyword for keyword in keywords if _text_contains_term(text, keyword)]


def _matches_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _strip_out_of_scope_text(text: str) -> str:
    cleaned = text
    for pattern in OUT_OF_SCOPE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    return cleaned


def _task_signal_text(state: dict[str, Any]) -> str:
    task = state["task"]
    parts = [
        task["original"],
        _strip_out_of_scope_text(task.get("scope_boundaries") or ""),
        task.get("definition_of_done") or "",
        task.get("verification") or "",
        task.get("remaining_uncertainty") or "",
    ]
    return " ".join(part for part in parts if part).lower()


def phase_mode_for_classification(classification: dict[str, Any]) -> str:
    if classification["task_type"] == "review-only":
        return "review-phase"
    if classification.get("pre_implementation_research") or (
        classification["flags"]["research"] and not classification["flags"]["implementation"]
    ):
        return "research-phase"
    return "implementation-phase"


def phase_mode_summary(phase_mode: str) -> str:
    if phase_mode == "research-phase":
        return "Research and decisions first. Do not treat implementation as in scope until evidence and synthesis are complete."
    if phase_mode == "review-phase":
        return "Advisory or gate review only. Do not take implementation ownership unless the task is explicitly rerouted."
    return "Implementation is in scope. Research and review may support execution, but the phase is allowed to produce code."


def _delivery_verdict_for_setup(coordination: str, continuity: str) -> str:
    if continuity == "full":
        return "full"
    if coordination == "solo":
        return "lean"
    return "lean"


def _default_capabilities_for_role(role: str, *, phase_mode: str) -> list[str]:
    if phase_mode == "research-phase":
        if role == "researcher":
            return ["research", "evidence", "synthesis"]
        if role == "converger":
            return ["research", "synthesis", "decision-making"]
    mapping = {
        "builder": ["implementation", "repo_edit", "verification"],
        "tester": ["browser", "verification", "frontend"],
        "reviewer": ["review", "verification", "critique"],
        "critic": ["critique", "review"],
        "researcher": ["research", "evidence", "synthesis"],
        "converger": ["research", "synthesis", "decision-making"],
        "orchestrator": ["routing", "checkpointing", "consolidation"],
    }
    return deepcopy(mapping.get(role, ["implementation", "verification"]))


def _default_objective_for_role(role: str, *, phase_mode: str) -> str:
    if phase_mode == "research-phase":
        if role == "researcher":
            return "Gather the missing evidence and reduce uncertainty before execution starts."
        if role == "converger":
            return "Consolidate findings into a decision-ready summary without starting implementation."
    mapping = {
        "builder": "Own the bounded execution slice and keep the scope disciplined.",
        "tester": "Verify the work and catch regressions before it advances.",
        "reviewer": "Review the packet and decide whether it is ready to advance.",
        "critic": "Challenge the plan or output and surface the main risks.",
        "researcher": "Gather the missing evidence before the next execution decision.",
        "converger": "Compare or merge candidate outputs into one final direction.",
        "orchestrator": "Own routing, checkpointing, and next-step coordination.",
    }
    return mapping.get(role, "Continue the bounded task work.")


def output_contract_for_part(part: dict[str, Any], *, phase_mode: str) -> dict[str, Any]:
    role = part.get("role")
    allowed_outputs: list[str]
    disallowed_outputs: list[str] = []
    evidence_required = False
    if phase_mode == "research-phase":
        if role == "researcher":
            allowed_outputs = [
                "verified findings",
                "source-backed endpoint notes",
                "open questions",
                "risks and caveats",
            ]
            disallowed_outputs = [
                "production code",
                "implementation file trees presented as settled",
                "unverified API claims",
            ]
            evidence_required = True
        elif role == "converger":
            allowed_outputs = [
                "decision synthesis",
                "implementation-ready brief grounded in prior lane outputs",
                "tradeoff summary",
            ]
            disallowed_outputs = [
                "new unsupported research claims",
                "production code",
            ]
        else:
            allowed_outputs = [
                "design exploration",
                "wireframes",
                "interaction patterns",
                "architecture options",
            ]
            disallowed_outputs = [
                "production code",
                "implementation plan presented as already executed",
            ]
    elif phase_mode == "review-phase":
        allowed_outputs = ["review findings", "approval or rejection rationale", "risks", "verification notes"]
        disallowed_outputs = ["production code"]
    else:
        allowed_outputs = ["code changes", "implementation notes", "verification evidence"]
    return {
        "phase_mode": phase_mode,
        "allowed_outputs": allowed_outputs,
        "disallowed_outputs": disallowed_outputs,
        "evidence_required": evidence_required,
    }


def _evidence_text(notes: str, artifacts: dict[str, Any] | None, report_markdown: str | None) -> str:
    chunks = [notes or "", report_markdown or ""]
    if artifacts:
        for key in ("findings", "decisions"):
            value = artifacts.get(key)
            if isinstance(value, str):
                chunks.append(value)
        for key in ("files_discovered", "blockers"):
            value = artifacts.get(key)
            if isinstance(value, list):
                chunks.extend(str(item) for item in value)
    return "\n".join(chunk for chunk in chunks if chunk).lower()


def phase_contract_warnings(
    state: dict[str, Any],
    part: dict[str, Any] | None,
    *,
    notes: str,
    artifacts: dict[str, Any] | None,
    report_markdown: str | None,
) -> list[str]:
    recommendation = state.get("confirmed_plan") or state.get("recommendation") or {}
    phase_mode = recommendation.get("phase_mode") or phase_mode_for_classification(state.get("classification") or {})
    if phase_mode not in PHASE_MODES:
        return []
    warnings: list[str] = []
    role = (part or {}).get("assignment", {}).get("role") or (part or {}).get("role")
    text = _evidence_text(notes, artifacts, report_markdown)
    files = [str(item).lower() for item in (artifacts or {}).get("files_discovered", []) if item]
    implementation_markers = (
        ".swift",
        ".ts",
        ".tsx",
        ".js",
        ".py",
        "struct ",
        "class ",
        "protocol ",
        "enum ",
        "func ",
        "implemented",
        "implementation complete",
        "wrote code",
        "created file",
    )
    if phase_mode == "research-phase":
        if any(marker in text for marker in implementation_markers) or any(
            item.endswith((".swift", ".ts", ".tsx", ".js", ".py")) for item in files
        ):
            warnings.append(
                "Research-phase contamination: this checkpoint looks like implementation output. Keep code generation out of a research-first phase or reroute the task."
            )
        if role == "researcher":
            has_source = bool(re.search(r"https?://", text))
            if not has_source:
                warnings.append(
                    "Research evidence is weak: the research lane did not include an explicit source URL or citation-like reference."
                )
    if phase_mode == "review-phase" and (
        any(marker in text for marker in implementation_markers)
        or any(item.endswith((".swift", ".ts", ".tsx", ".js", ".py")) for item in files)
    ):
        warnings.append(
            "Review-phase contamination: review lanes should not produce implementation output unless the task is explicitly rerouted."
        )
    return warnings


def _recent_repo_activity(state: dict[str, Any], *, window_minutes: int = 120) -> list[str]:
    repo_root_value = state.get("project_root") or state.get("workspace_root")
    if not repo_root_value:
        return []
    repo_root = Path(repo_root_value)
    if not repo_root.exists():
        return []
    cutoff = datetime.now(timezone.utc).timestamp() - (window_minutes * 60)
    state_reference = parse_iso(state.get("updated_at") or state.get("created_at"))
    if state_reference is not None:
        cutoff = max(cutoff, state_reference.timestamp() + 1)
    recent: list[tuple[float, str]] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".relaykit", ".git", "__pycache__"} for part in path.parts):
            continue
        if path.name.startswith("."):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime >= cutoff:
            recent.append((stat.st_mtime, str(path)))
    recent.sort(reverse=True)
    return [item[1] for item in recent[:10]]


def state_drift_warnings(state: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    recent_files = _recent_repo_activity(state)
    if state.get("status") == "recommended" and recent_files:
        warnings.append(
            "Repo activity drift: files changed after recommendation, but the task was never confirmed. Either confirm the phase or start a fresh task so RelayKit matches the real work."
        )
    current = current_phase(state)
    phase_mode = (current or {}).get("phase_mode") or (state.get("confirmed_plan") or state.get("recommendation") or {}).get("phase_mode")
    if phase_mode == "research-phase":
        implementation_files = [
            path for path in recent_files
            if path.endswith((".swift", ".ts", ".tsx", ".js", ".py"))
        ]
        if implementation_files:
            warnings.append(
                "Research-phase drift: implementation files are changing while the active RelayKit phase is still research-first."
            )
    if state.get("status") == "active" and current is not None:
        checkpointed = _phase_checkpointed_parts(current)
        if not checkpointed and recent_files:
            warnings.append(
                "Advance overdue: repo activity is happening, but no checkpoint has been recorded for the active phase yet."
            )
    return warnings


def orchestration_guidance(state: dict[str, Any]) -> list[str]:
    guidance: list[str] = []
    status = state.get("status")
    current = current_phase(state)
    recent_files = _recent_repo_activity(state)
    source_statuses = source_artifact_statuses(state)
    if status == "recommended":
        guidance.append("If work is actually starting, run `confirm-task` first so RelayKit owns the phase instead of trailing the repo.")
    if status in {"active", "launched"} and recent_files and current is not None and not _phase_checkpointed_parts(current):
        guidance.append("Checkpoint after the first concrete artifact, blocker, or research finding instead of letting work continue off-ledger.")
    if status in {"blocked", "needs_reroute", "ready_for_next_phase"}:
        guidance.append("Use `advance-task` now. The orchestration layer is waiting for an explicit phase decision.")
    if current is not None and current.get("phase_mode") == "research-phase":
        guidance.append("Do not start implementation output in a research-phase lane unless you explicitly reroute the task with `advance-task` or a change request.")
    if any(item.get("status") in {"partially-addressed", "addressed-unverified"} for item in source_statuses):
        guidance.append("Source critique artifacts have changed state. Resolve or supersede them before using them as fresh backlog again.")
    return dedupe(guidance)


def orchestration_contract(state: dict[str, Any]) -> list[str]:
    task_id = state.get("task_id", "<id>")
    return [
        "Confirm the RelayKit task before real work starts.",
        "Checkpoint after the first concrete artifact, blocker, or verified finding.",
        "Advance immediately when RelayKit reports `blocked`, `needs_reroute`, or `ready_for_next_phase`.",
        f"If work moved ahead without orchestration progress, run `relaykit.py resume-task --task-id {task_id}` and bring the control plane forward before continuing.",
    ]


def orchestration_required_action(state: dict[str, Any]) -> dict[str, Any] | None:
    task_id = state.get("task_id", "<id>")
    status = state.get("status")
    current = current_phase(state)
    recent_files = _recent_repo_activity(state)
    checkpointed = _phase_checkpointed_parts(current) if current else []
    stale_plan = stale_plan_assessment(state)

    if stale_plan:
        suggested = f"relaykit.py resume-task --task-id {task_id}"
        kind = "refresh-plan"
        if status == "recommended":
            suggested = f"relaykit.py confirm-task --task-id {task_id} --accept=false --change \"Refresh the RelayKit recommendation to match current repo activity and source status.\""
            kind = "re-recommend"
        elif status in {"active", "launched", "blocked", "needs_reroute", "ready_for_next_phase"}:
            suggested = f"relaykit.py advance-task --task-id {task_id} --change \"Refresh the active RelayKit plan to match current repo activity and source status.\""
            kind = "advance-refresh"
        return {
            "kind": kind,
            "urgency": "required_now",
            "message": stale_plan["message"],
            "suggested_command": suggested,
        }

    if status == "recommended":
        return {
            "kind": "confirm",
            "urgency": "required_before_work",
            "message": "Confirm or change the setup before any real work starts.",
            "suggested_command": f"relaykit.py confirm-task --task-id {task_id} --accept",
        }
    if status in {"blocked", "needs_reroute", "ready_for_next_phase"}:
        return {
            "kind": "advance",
            "urgency": "required_now",
            "message": "Advance the task now. Do not keep working in the old phase.",
            "suggested_command": f"relaykit.py advance-task --task-id {task_id}",
        }
    if status in {"active", "launched"} and current is not None and recent_files and not checkpointed:
        part_id = None
        parts = current.get("task_parts") or []
        if len(parts) == 1:
            part_id = parts[0].get("part_id")
        suggested = f"relaykit.py checkpoint-task --task-id {task_id}"
        if part_id:
            suggested += f" --part-id {part_id}"
        return {
            "kind": "checkpoint",
            "urgency": "required_now",
            "message": "Work is happening, but RelayKit has no checkpoint yet. Record a checkpoint before continuing.",
            "suggested_command": suggested,
        }
    return None


def stale_plan_assessment(state: dict[str, Any]) -> dict[str, Any] | None:
    if state.get("status") in TERMINAL_STATUSES:
        return None
    reasons: list[str] = []
    recent_files = _recent_repo_activity(state)
    source_statuses = source_artifact_statuses(state)
    status = state.get("status")
    current = current_phase(state)
    checkpointed = _phase_checkpointed_parts(current) if current else []
    if status == "recommended" and recent_files:
        reasons.append("repo activity began before the recommendation was confirmed")
    if status in {"active", "launched"} and current is not None and recent_files and not checkpointed:
        reasons.append("work advanced without a RelayKit checkpoint for the active phase")
    changed_sources = [
        item for item in source_statuses
        if item.get("status") in {"partially-addressed", "addressed-unverified", "superseded", "verified"}
    ]
    if changed_sources:
        reasons.append("source critique artifacts have changed status since this plan was generated")
    if not reasons:
        return None
    return {
        "stale": True,
        "reasons": reasons,
        "message": "The saved RelayKit plan is stale and should be refreshed before continuing.",
        "source_artifacts": changed_sources,
        "recent_files": recent_files[:5],
    }


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "task"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def read_recent_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists() or limit <= 0:
        return []
    chunk_size = 8192
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        buffer = bytearray()
        while position > 0 and buffer.count(b"\n") <= limit:
            read_size = min(chunk_size, position)
            position -= read_size
            handle.seek(position)
            buffer[:0] = handle.read(read_size)
    lines = buffer.decode("utf-8").splitlines()
    if position > 0 and lines:
        lines = lines[1:]
    rows: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def resolve_asset(path: str) -> str:
    return str((REPO_ROOT / path).resolve())


def fail(message: str, *, details: list[str] | None = None) -> None:
    payload: dict[str, Any] = {"error": message}
    if details:
        payload["details"] = details
    raise ValueError(json.dumps(payload))


def parse_failure(error: Exception) -> tuple[str, list[str] | None]:
    try:
        payload = json.loads(str(error))
        return payload["error"], payload.get("details")
    except Exception:
        return str(error), None


def task_root(root: Path, profile_dirname: str) -> Path:
    return root / profile_dirname / TASKS_DIRNAME


def task_dir(root: Path, profile_dirname: str, task_id: str) -> Path:
    return task_root(root, profile_dirname) / task_id


def state_path(root: Path, profile_dirname: str, task_id: str) -> Path:
    return task_dir(root, profile_dirname, task_id) / "state.json"


def summary_path(root: Path, profile_dirname: str, task_id: str) -> Path:
    return task_dir(root, profile_dirname, task_id) / "summary.md"


def scratchpad_path(root: Path, profile_dirname: str, task_id: str) -> Path:
    return task_dir(root, profile_dirname, task_id) / "scratchpad.md"


def _create_scratchpad(state: dict[str, Any], registry: dict[str, Any]) -> Path:
    profile_dirname = registry["defaults"]["profile_dirname"]
    root = Path(state["storage_root"])
    path = scratchpad_path(root, profile_dirname, state["task_id"])
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"# Scratchpad — {state['task_id']}\n"
            f"\n"
            f"Shared context for all task parts working on this task.\n"
            f"Each task part should **read this file before starting** and "
            f"**append key findings before checkpointing**.\n"
            f"\n"
            f"---\n"
            f"\n",
            encoding="utf-8",
        )
    return path


def _append_scratchpad_entry(
    state: dict[str, Any],
    registry: dict[str, Any],
    *,
    part_id: str | None,
    notes: str,
    artifacts: dict[str, Any] | None,
    report_markdown: str | None = None,
) -> Path:
    path = _create_scratchpad(state, registry)
    timestamp = now_iso()
    lines = [
        f"## {timestamp} — `{part_id or 'task'}`",
        "",
    ]
    if notes.strip():
        lines.extend([f"Notes: {notes.strip()}", ""])
    if artifacts:
        findings = artifacts.get("findings") or ""
        decisions = artifacts.get("decisions") or ""
        files_discovered = artifacts.get("files_discovered") or []
        blockers = artifacts.get("blockers") or []
        git_diff = artifacts.get("git_diff")
        if findings:
            lines.extend([f"Findings: {findings}", ""])
        if decisions:
            lines.extend([f"Decisions: {decisions}", ""])
        if files_discovered:
            lines.extend(["Files discovered:", *[f"- `{item}`" for item in files_discovered], ""])
        if blockers:
            lines.extend(["Blockers:", *[f"- {item}" for item in blockers], ""])
        if git_diff:
            stat = git_diff.get("stat") or ""
            if stat:
                lines.extend(["Git diff:", "```text", stat, "```", ""])
    if report_markdown and report_markdown.strip():
        lines.extend(["Report:", "", report_markdown.strip(), ""])
    path.write_text(path.read_text(encoding="utf-8") + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def learning_log_path(root: Path, profile_dirname: str) -> Path:
    return root / profile_dirname / LEARNING_LOG_FILENAME


def learning_summary_path(root: Path, profile_dirname: str) -> Path:
    return root / profile_dirname / LEARNING_SUMMARY_FILENAME


def _duration_label(delta: timedelta) -> str:
    total_seconds = max(0, int(delta.total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    mins, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{mins:02d}m"
    return f"{mins:02d}:{secs:02d}"


def root_for_task(workspace_root: Path | None, project_root: Path | None, task_scope: str | None) -> Path:
    if task_scope == "workspace" and workspace_root is not None:
        return workspace_root
    if project_root is not None:
        return project_root
    if workspace_root is not None:
        return workspace_root
    return Path.cwd().resolve()


def default_inventory(registry: dict[str, Any]) -> dict[str, Any]:
    hosts = registry.get("hosts", {})
    return {
        "available_hosts": sorted(hosts.keys()),
        "allowed_models_by_host": {
            host_name: deepcopy(meta.get("default_models", []))
            for host_name, meta in hosts.items()
        },
        "default_posture": "balanced",
    }


def normalize_workspace_inventory(
    registry: dict[str, Any],
    workspace_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    inventory = deepcopy(default_inventory(registry))
    if workspace_profile is None:
        return inventory
    profile_inventory = workspace_profile.get("inventory")
    if not isinstance(profile_inventory, dict):
        return inventory
    hosts = profile_inventory.get("available_hosts")
    if isinstance(hosts, list) and hosts:
        inventory["available_hosts"] = [host for host in hosts if host in registry["hosts"]]
    models_by_host = profile_inventory.get("allowed_models_by_host")
    if isinstance(models_by_host, dict):
        filtered: dict[str, list[str]] = {}
        for host_name, model_names in models_by_host.items():
            if host_name not in registry["hosts"] or not isinstance(model_names, list):
                continue
            filtered[host_name] = [
                model_name
                for model_name in model_names
                if model_name in registry["models"]
                and host_name in registry["models"][model_name]["hosts"]
            ]
        if filtered:
            inventory["allowed_models_by_host"] = filtered
    posture = profile_inventory.get("default_posture")
    if posture in QUALITY_POSTURES:
        inventory["default_posture"] = posture
    return inventory


def parse_host_mentions(text: str, registry: dict[str, Any]) -> list[str]:
    lowered = text.lower()
    found = [host for host in registry["hosts"] if host in lowered]
    aliases = {
        "claude": "claude-code",
        "codex": "codex",
        "antigravity": "antigravity",
        "gemini": "gemini-cli",
    }
    for alias, host in aliases.items():
        if alias in lowered and host in registry["hosts"]:
            found.append(host)
    return dedupe(found)


def parse_constraint_text(
    text: str,
    registry: dict[str, Any],
    *,
    default_allowed_hosts: list[str],
) -> dict[str, Any]:
    lowered = text.lower().strip()
    mentioned_hosts = parse_host_mentions(lowered, registry)
    excluded_hosts = [
        host
        for host in mentioned_hosts
        if f"avoid {host}" in lowered
        or f"don't use {host}" in lowered
        or f"do not use {host}" in lowered
        or f"no {host}" in lowered
    ]
    posture = "balanced"
    if any(token in lowered for token in ["cheap", "low cost", "budget", "conservative", "lower-cost"]):
        posture = "cost-aware"
    elif any(token in lowered for token in ["premium", "best quality", "highest quality", "quality first"]):
        posture = "quality-first"
    elif any(token in lowered for token in ["fast", "quick", "speed", "ship fast"]):
        posture = "speed-first"

    role_preferences: dict[str, str] = {}
    lane_preferences: dict[str, str] = {}
    host_aliases = {
        "codex": "codex",
        "claude": "claude-code",
        "claude-code": "claude-code",
        "claude code": "claude-code",
        "gemini": "gemini-cli",
        "gemini-cli": "gemini-cli",
        "gemini cli": "gemini-cli",
        "antigravity": "antigravity",
    }
    lane_patterns = {
        "frontend-build": ["frontend", "ui"],
        "ui-repair": ["frontend", "ui"],
        "frontend-test": ["frontend test", "browser verification", "browser test"],
        "core-repair": ["backend", "core", "security", "auth", "cleanup"],
        "implementation": ["implementation", "backend", "core"],
        "verification": ["verification", "verify", "review"],
        "research": ["research", "investigate"],
        "design": ["design", "ux", "visual"],
        "synthesis": ["synthesis", "consolidate"],
    }
    role_patterns = {
        "builder": ["builder", "implementation"],
        "researcher": ["research", "investigate"],
        "reviewer": ["review", "verification", "verify"],
        "critic": ["critique", "critic", "challenge"],
        "tester": ["test", "qa", "browser verification", "browser test"],
    }

    clauses = [
        clause.strip()
        for clause in re.split(r"[\n,;\.:]|\band\b", lowered)
        if clause.strip()
    ]

    for clause in clauses:
        for alias, host_name in host_aliases.items():
            if alias not in clause:
                continue
            for lane_name, phrases in lane_patterns.items():
                if any(_text_contains_term(clause, phrase) for phrase in phrases):
                    lane_preferences[lane_name] = host_name
            for role_name, phrases in role_patterns.items():
                if any(_text_contains_term(clause, phrase) for phrase in phrases):
                    role_preferences[role_name] = host_name

    explicit_split = bool(role_preferences or lane_preferences) or bool(
        re.search(r"\b(split|parallelize|distribute|assign)\b", lowered) and len(mentioned_hosts) >= 2
    )

    if "all" in lowered and "available" in lowered:
        allowed_hosts = list(default_allowed_hosts)
    elif "only" in lowered and mentioned_hosts:
        allowed_hosts = [host for host in mentioned_hosts if host not in excluded_hosts]
    elif mentioned_hosts:
        allowed_hosts = [host for host in default_allowed_hosts if host in mentioned_hosts and host not in excluded_hosts]
        if not allowed_hosts:
            allowed_hosts = [host for host in mentioned_hosts if host not in excluded_hosts]
    else:
        allowed_hosts = [host for host in default_allowed_hosts if host not in excluded_hosts]

    return {
        "raw": text,
        "allowed_hosts": dedupe(allowed_hosts),
        "excluded_hosts": dedupe(excluded_hosts),
        "budget_posture": posture,
        "preferred_hosts_by_role": role_preferences,
        "preferred_hosts_by_lane": lane_preferences,
        "explicit_split": explicit_split,
    }


def effective_allowed_models(
    registry: dict[str, Any],
    inventory: dict[str, Any],
    *,
    allowed_hosts: list[str],
) -> dict[str, list[str]]:
    models_by_host = inventory.get("allowed_models_by_host", {})
    result: dict[str, list[str]] = {}
    for host_name in allowed_hosts:
        configured = models_by_host.get(host_name)
        if isinstance(configured, list) and configured:
            result[host_name] = [
                model_name
                for model_name in configured
                if model_name in registry["models"]
                and host_name in registry["models"][model_name]["hosts"]
            ]
        else:
            result[host_name] = deepcopy(registry["hosts"][host_name].get("default_models", []))
    return result


def merged_defaults(
    workspace_profile: dict[str, Any] | None,
    project_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workspace_preset": workspace_profile.get("preset") if workspace_profile else None,
        "project_preset": project_profile.get("preset") if project_profile else None,
        "default_personas": [],
    }
    personas: list[str] = []
    if workspace_profile and project_profile and not project_profile.get("inherits_workspace_defaults", True):
        personas.extend(project_profile.get("default_personas", []))
    else:
        if workspace_profile:
            personas.extend(workspace_profile.get("default_personas", []))
        if project_profile:
            personas.extend(project_profile.get("default_personas", []))
    payload["default_personas"] = dedupe(personas)
    return payload


def task_summary_text(state: dict[str, Any]) -> str:
    summary = state["task"].get("clarified_summary")
    if summary:
        return summary
    return state["task"]["original"]


def _compact_display_path(path: str | None, state: dict[str, Any]) -> str | None:
    if not path:
        return None
    candidate = Path(path)
    for root_key in ("project_root", "workspace_root"):
        root = state.get(root_key)
        if not root:
            continue
        try:
            relative = candidate.relative_to(Path(root))
        except ValueError:
            continue
        return str(relative)
    return str(candidate)


def _compact_execution_note(execution_context: dict[str, Any]) -> str | None:
    notes = execution_context.get("notes") or []
    if not notes:
        return None
    note = str(notes[0]).strip()
    if not note:
        return None
    command_sources = {
        str(item.get("source") or "").strip()
        for item in execution_context.get("validated_commands", [])
        if isinstance(item, dict)
    }
    if "verification-fallback" in command_sources and "is not runnable here:" in note:
        return "Declared verification target is unavailable locally; use the validated fallback."
    if "Fell back to `" in note and "declared project verification target" in note:
        return "Using a validated local fallback because the declared verification target is unavailable."
    if len(note) > 120:
        return note[:117].rstrip() + "..."
    return note


def _compact_execution_context(execution_context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not execution_context:
        return None
    commands: list[dict[str, str]] = []
    for item in execution_context.get("validated_commands", []):
        if not isinstance(item, dict):
            continue
        command = str(item.get("command") or "").strip()
        if not command:
            continue
        compact_item = {"command": command}
        source = str(item.get("source") or "").strip()
        if source:
            compact_item["source"] = source
        commands.append(compact_item)
    note = _compact_execution_note(execution_context)
    if not commands and not note:
        return None
    payload: dict[str, Any] = {}
    if commands:
        payload["validated_commands"] = commands
    if note:
        payload["note"] = note
    return payload


def issue_status_path(root: Path, profile_dirname: str) -> Path:
    return root / profile_dirname / "issue-status.json"


def _source_doc_candidates(state: dict[str, Any]) -> list[Path]:
    roots = [
        Path(root)
        for root in [state.get("project_root"), state.get("workspace_root"), state.get("storage_root")]
        if root
    ]
    text = " ".join(
        [
            state["task"]["original"],
            state["task"].get("scope_boundaries") or "",
            state["task"].get("definition_of_done") or "",
            state["task"].get("verification") or "",
            state["task"].get("constraints_text") or "",
        ]
    )
    raw_matches = re.findall(r"(?:/[\w .\-/]+\.md|[\w./-]+\.md)", text)
    candidates: list[Path] = []
    seen: set[str] = set()
    for raw in raw_matches:
        raw = raw.strip("`'\".,)")
        path = Path(raw).expanduser()
        options = [path] if path.is_absolute() else [root / path for root in roots]
        for candidate in options:
            resolved = candidate.resolve()
            if resolved.exists() and resolved.is_file():
                key = str(resolved)
                if key not in seen:
                    seen.add(key)
                    candidates.append(resolved)
    return candidates


def load_issue_status_summary(root: Path, profile_dirname: str) -> dict[str, Any]:
    path = issue_status_path(root, profile_dirname)
    if not path.exists():
        return {"version": 1, "sources": {}}
    payload = read_json(path)
    sources = payload.get("sources")
    if not isinstance(sources, dict):
        payload["sources"] = {}
    return payload


def save_issue_status_summary(root: Path, profile_dirname: str, payload: dict[str, Any]) -> Path:
    path = issue_status_path(root, profile_dirname)
    write_json(path, payload)
    return path


def _source_status_from_issue_counts(issues: dict[str, Any]) -> str:
    open_count = 0
    addressed_count = 0
    verified_count = 0
    superseded_count = 0
    for entry in issues.values():
        if not isinstance(entry, dict):
            continue
        status = entry.get("status", "open")
        if status == "open":
            open_count += 1
        elif status == "addressed-unverified":
            addressed_count += 1
        elif status == "verified":
            verified_count += 1
        elif status == "superseded":
            superseded_count += 1
    total = open_count + addressed_count + verified_count + superseded_count
    if total == 0 or open_count == total:
        return "active"
    if open_count == 0 and addressed_count == 0 and verified_count == 0 and superseded_count > 0:
        return "superseded"
    if open_count == 0 and addressed_count == 0 and verified_count > 0:
        return "verified"
    if open_count == 0 and addressed_count > 0:
        return "addressed-unverified"
    return "partially-addressed"


def source_artifact_statuses(state: dict[str, Any]) -> list[dict[str, Any]]:
    profile_dirname = state.get("profile_dirname") or ".relaykit"
    root = Path(state.get("storage_root") or ".")
    status_summary = load_issue_status_summary(root, profile_dirname)
    sources = status_summary.get("sources", {})
    inventory = parse_issue_inventory(state)
    inventory_by_source: dict[str, list[dict[str, Any]]] = {}
    for item in inventory:
        source_path = item.get("source_path")
        if isinstance(source_path, str):
            inventory_by_source.setdefault(source_path, []).append(item)
    summaries: list[dict[str, Any]] = []
    for doc in _source_doc_candidates(state):
        source_key = str(doc)
        source_entry = sources.get(source_key, {}) if isinstance(sources.get(source_key), dict) else {}
        source_items = inventory_by_source.get(source_key, [])
        counts = {
            "open": sum(1 for item in source_items if item.get("status") == "open"),
            "addressed_unverified": sum(1 for item in source_items if item.get("status") == "addressed-unverified"),
            "verified": sum(1 for item in source_items if item.get("status") == "verified"),
            "superseded": sum(1 for item in source_items if item.get("status") == "superseded"),
        }
        explicit_status = source_entry.get("status")
        synthetic_issues = {
            item.get("issue_id", f"issue-{index}"): {"status": item.get("status", "open")}
            for index, item in enumerate(source_items)
        }
        status = explicit_status if isinstance(explicit_status, str) and explicit_status else _source_status_from_issue_counts(synthetic_issues)
        summaries.append(
            {
                "source_path": source_key,
                "status": status,
                "updated_at": source_entry.get("updated_at"),
                "counts": counts,
            }
        )
    return summaries


def _issue_category(section: str, title: str) -> str:
    text = f"{section} {title}".lower()
    if any(token in text for token in ["security", "secret", "credential", "keychain", "oauth", "auth"]):
        return "security"
    if any(token in text for token in ["ui", "menu bar", "icon", "button", "view", "window", "frontend", "swiftui"]):
        return "frontend"
    if any(token in text for token in ["cleanup", "housekeeping", "stale", "empty dir", "remove", "delete"]):
        return "cleanup"
    if any(token in text for token in ["test", "verify", "verification", "review", "critique"]):
        return "verification"
    return "backend"


def parse_issue_inventory(state: dict[str, Any]) -> list[dict[str, Any]]:
    profile_dirname = state.get("profile_dirname") or ".relaykit"
    root = Path(state.get("storage_root") or ".")
    status_summary = load_issue_status_summary(root, profile_dirname)
    sources = status_summary.get("sources", {})
    inventory: list[dict[str, Any]] = []
    for doc in _source_doc_candidates(state):
        source_key = str(doc)
        source_statuses = sources.get(source_key, {}).get("issues", {}) if isinstance(sources.get(source_key), dict) else {}
        section = ""
        for line in doc.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                section = stripped[3:].strip()
                continue
            match = re.match(r"###\s+(?:\d+\.\s+)?(.+)", stripped)
            if not match:
                continue
            title = match.group(1).strip()
            issue_id = slugify(title)
            status = source_statuses.get(issue_id, {}).get("status", "open")
            inventory.append(
                {
                    "issue_id": issue_id,
                    "title": title,
                    "section": section or "general",
                    "category": _issue_category(section, title),
                    "status": status,
                    "source_path": source_key,
                    "source_status": (
                        sources.get(source_key, {}).get("status")
                        if isinstance(sources.get(source_key), dict)
                        else None
                    ),
                }
            )
    return inventory


def _issue_inventory_summary(issue_inventory: list[dict[str, Any]]) -> dict[str, Any]:
    open_issues = [item for item in issue_inventory if item.get("status") == "open"]
    categories = {item.get("category") for item in open_issues if item.get("category")}
    return {
        "count": len(issue_inventory),
        "open_count": len(open_issues),
        "categories": sorted(categories),
        "sources": dedupe([item.get("source_path") for item in issue_inventory if item.get("source_path")]),
        "mixed_packet": len(categories.intersection({"frontend", "backend", "security", "cleanup"})) >= 2,
    }


def mark_issue_inventory_addressed(
    *,
    root: Path,
    profile_dirname: str,
    issue_inventory: list[dict[str, Any]],
    task_id: str,
) -> dict[str, Any]:
    payload = load_issue_status_summary(root, profile_dirname)
    sources = payload.setdefault("sources", {})
    updated: list[dict[str, Any]] = []
    for item in issue_inventory:
        if item.get("status") != "open":
            continue
        source_path = item.get("source_path")
        issue_id = item.get("issue_id")
        if not isinstance(source_path, str) or not isinstance(issue_id, str):
            continue
        source_entry = sources.setdefault(source_path, {"issues": {}, "updated_at": None})
        issues = source_entry.setdefault("issues", {})
        issues[issue_id] = {
            "status": "addressed-unverified",
            "task_id": task_id,
            "updated_at": now_iso(),
            "title": item.get("title"),
            "section": item.get("section"),
            "category": item.get("category"),
        }
        source_entry["updated_at"] = now_iso()
        source_entry["status"] = _source_status_from_issue_counts(issues)
        updated.append({"source_path": source_path, "issue_id": issue_id, "status": "addressed-unverified"})
    save_issue_status_summary(root, profile_dirname, payload)
    return {
        "updated_count": len(updated),
        "updated_issues": updated,
        "state_path": str(issue_status_path(root, profile_dirname)),
    }


def mark_issue_inventory_superseded(
    *,
    root: Path,
    profile_dirname: str,
    issue_inventory: list[dict[str, Any]],
    task_id: str,
) -> dict[str, Any]:
    payload = load_issue_status_summary(root, profile_dirname)
    sources = payload.setdefault("sources", {})
    updated_sources: list[dict[str, Any]] = []
    by_source: dict[str, list[dict[str, Any]]] = {}
    for item in issue_inventory:
        source_path = item.get("source_path")
        if isinstance(source_path, str):
            by_source.setdefault(source_path, []).append(item)
    for source_path, items in by_source.items():
        source_entry = sources.setdefault(source_path, {"issues": {}, "updated_at": None})
        issues = source_entry.setdefault("issues", {})
        for item in items:
            issue_id = item.get("issue_id")
            if not isinstance(issue_id, str):
                continue
            current = issues.get(issue_id, {}) if isinstance(issues.get(issue_id), dict) else {}
            issues[issue_id] = {
                **current,
                "status": "superseded",
                "task_id": task_id,
                "updated_at": now_iso(),
                "title": item.get("title"),
                "section": item.get("section"),
                "category": item.get("category"),
            }
        source_entry["updated_at"] = now_iso()
        source_entry["status"] = "superseded"
        updated_sources.append({"source_path": source_path, "status": "superseded"})
    save_issue_status_summary(root, profile_dirname, payload)
    return {
        "updated_count": len(updated_sources),
        "updated_sources": updated_sources,
        "state_path": str(issue_status_path(root, profile_dirname)),
    }


def _ultra_compact_execution_context(execution_context: dict[str, Any] | None) -> dict[str, Any] | None:
    compact = _compact_execution_context(execution_context)
    if not compact:
        return None
    payload: dict[str, Any] = {}
    commands = compact.get("validated_commands") or []
    if commands:
        payload["command"] = commands[0]["command"]
    note = compact.get("note")
    if note:
        payload["note"] = note
    return payload or None


def classify_task(state: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    text = _task_signal_text(state)
    manual_setup = state.get("manual_overrides", {})
    pre_implementation_research = bool(manual_setup.get("pre_implementation_research")) or _matches_any_pattern(
        text,
        PRE_IMPLEMENTATION_PATTERNS,
    )
    frontend_matches = _keyword_matches(text, FRONTEND_KEYWORDS)
    backend_matches = _keyword_matches(text, BACKEND_KEYWORDS)
    security_matches = _keyword_matches(text, SECURITY_KEYWORDS)
    cleanup_matches = _keyword_matches(text, CLEANUP_KEYWORDS)
    review_matches = _keyword_matches(text, REVIEW_KEYWORDS)
    research_matches = _keyword_matches(text, RESEARCH_KEYWORDS)
    planning_matches = _keyword_matches(text, PLANNING_KEYWORDS)
    implementation_matches = _keyword_matches(text, IMPLEMENTATION_KEYWORDS)
    bugfix_matches = _keyword_matches(text, BUGFIX_KEYWORDS)
    pause_matches = _keyword_matches(text, PAUSE_KEYWORDS)
    cross_project_matches = _keyword_matches(text, CROSS_PROJECT_KEYWORDS)
    issue_inventory = parse_issue_inventory(state)
    issue_summary = _issue_inventory_summary(issue_inventory)
    issue_categories = set(issue_summary["categories"])
    parsed_constraints = _effective_parsed_constraints(state, registry)
    mixed_categories = set(issue_categories.intersection({"frontend", "backend", "security", "cleanup"}))
    if frontend_matches:
        mixed_categories.add("frontend")
    if backend_matches:
        mixed_categories.add("backend")
    if security_matches:
        mixed_categories.add("security")
    if cleanup_matches:
        mixed_categories.add("cleanup")
    flags = {
        "frontend": bool(frontend_matches),
        "backend": bool(backend_matches),
        "review": bool(review_matches),
        "research": bool(research_matches) or pre_implementation_research,
        "planning": bool(planning_matches),
        "implementation": bool(implementation_matches),
        "bugfix": bool(bugfix_matches),
        "pause_sensitive": bool(pause_matches),
        "cross_project": bool(cross_project_matches),
        "security": "security" in issue_categories or bool(security_matches),
        "cleanup": "cleanup" in issue_categories or bool(cleanup_matches),
        "mixed_packet": bool(issue_summary["mixed_packet"]) or len(mixed_categories) >= 2,
    }
    if issue_categories.intersection({"frontend"}):
        flags["frontend"] = True
    if issue_categories.intersection({"backend", "security", "cleanup"}):
        flags["implementation"] = True
        flags["bugfix"] = True
    elif (backend_matches or security_matches or cleanup_matches) and (implementation_matches or bugfix_matches):
        flags["implementation"] = True
    if "verification" in issue_categories:
        flags["review"] = True
    if pre_implementation_research:
        flags["implementation"] = False
        flags["bugfix"] = False
    if flags["planning"] and flags["research"] and not flags["bugfix"]:
        flags["implementation"] = False

    if flags["review"] and not flags["implementation"] and not flags["research"]:
        task_type = "review-only"
        archetype = "review-hardening"
    elif pre_implementation_research or (flags["research"] and not flags["implementation"]):
        task_type = "exploratory"
        archetype = "research-plan"
    elif flags["mixed_packet"]:
        task_type = "execution-ready"
        archetype = "mixed-repair"
    elif flags["frontend"] and flags["implementation"]:
        task_type = "execution-ready"
        archetype = "frontend-polish"
    elif flags["bugfix"]:
        task_type = "execution-ready"
        archetype = "bugfix"
    elif flags["implementation"]:
        task_type = "execution-ready"
        archetype = "feature-build"
    else:
        task_type = "ambiguous"
        archetype = "custom"

    resolved_fields = 0
    for key in ["scope_boundaries", "definition_of_done", "verification"]:
        if state["task"].get(key):
            resolved_fields += 1
    if state["inventory"]["effective_hosts"]:
        resolved_fields += 1

    if task_type == "ambiguous" or resolved_fields <= 2:
        confidence = "low"
    elif resolved_fields == 3:
        confidence = "medium"
    else:
        confidence = "high"

    remaining_uncertainty = state["task"].get("remaining_uncertainty")
    if not remaining_uncertainty:
        if confidence == "low":
            remaining_uncertainty = "scope, verification, or tool constraints are still underspecified"
        elif task_type == "exploratory":
            remaining_uncertainty = "the task still needs evidence before the strongest plan can be chosen"
        else:
            remaining_uncertainty = ""

    return {
        "task_type": task_type,
        "archetype": archetype,
        "confidence": confidence,
        "flags": flags,
        "pre_implementation_research": pre_implementation_research,
        "remaining_uncertainty": remaining_uncertainty,
        "issue_inventory": issue_inventory,
        "issue_summary": issue_summary,
        "mixed_categories": sorted(mixed_categories),
    }


def project_uses_workspace_defaults(project_profile: dict[str, Any] | None) -> bool:
    if project_profile is None:
        return True
    return bool(project_profile.get("inherits_workspace_defaults", True))


def parse_setup_mode(value: str | None) -> tuple[str | None, str | None]:
    if not value or "+" not in value:
        return None, None
    coordination, continuity = value.split("+", 1)
    return coordination, continuity


def apply_lane_overrides(lanes: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(lanes)
    for lane_name, override in overrides.items():
        base = deepcopy(merged.get(lane_name, {}))
        if isinstance(override, dict):
            base.update(deepcopy(override))
        merged[lane_name] = base
    return merged


def resolve_effective_lanes(
    registry: dict[str, Any],
    *,
    preset_name: str,
    workspace_profile: dict[str, Any] | None,
    project_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    preset = deepcopy(registry["presets"][preset_name])
    lanes = preset.get("lanes", {})
    if workspace_profile is not None and project_uses_workspace_defaults(project_profile):
        lanes = apply_lane_overrides(lanes, workspace_profile.get("lane_overrides", {}))
    if project_profile is not None:
        lanes = apply_lane_overrides(lanes, project_profile.get("lane_overrides", {}))
    return lanes


def select_internal_preset(
    registry: dict[str, Any],
    classification: dict[str, Any],
    inventory: dict[str, Any],
    defaults: dict[str, Any],
) -> str:
    allowed_hosts = inventory["effective_hosts"]
    posture = inventory["budget_posture"]
    archetype = classification["archetype"]
    flags = classification["flags"]
    if posture == "cost-aware" and "cost-aware" in registry["presets"]:
        return "cost-aware"
    if archetype == "frontend-polish" and "antigravity" in allowed_hosts and "frontend-heavy" in registry["presets"]:
        return "frontend-heavy"
    if archetype == "review-hardening" and "reality-gate" in registry["presets"]:
        return "reality-gate"
    if defaults.get("project_preset") in registry["presets"]:
        return defaults["project_preset"]
    if defaults.get("workspace_preset") in registry["presets"]:
        return defaults["workspace_preset"]
    if allowed_hosts == ["codex"] and "codex-led" in registry["presets"]:
        return "codex-led"
    if flags["research"] and "claude-code" in allowed_hosts and "claude-led" in registry["presets"]:
        return "claude-led"
    return "balanced-default"


def learned_archetype_preferences(state: dict[str, Any], archetype: str) -> dict[str, Any]:
    tendencies = state.get("layers", {}).get("learned_tendencies", {})
    archetypes = tendencies.get("archetypes", {})
    if not isinstance(archetypes, dict):
        return {}
    bucket = archetypes.get(archetype)
    return bucket if isinstance(bucket, dict) else {}


def preferred_host_for_role(state: dict[str, Any], archetype: str, role: str) -> str | None:
    bucket = learned_archetype_preferences(state, archetype)
    host_map = bucket.get("preferred_hosts_by_role", {})
    if not isinstance(host_map, dict):
        return None
    preferred = host_map.get(role)
    if isinstance(preferred, str) and preferred:
        return preferred
    return None


def avoided_host_for_role(state: dict[str, Any], archetype: str, role: str) -> str | None:
    bucket = learned_archetype_preferences(state, archetype)
    host_map = bucket.get("avoid_hosts_by_role", {})
    if not isinstance(host_map, dict):
        return None
    avoided = host_map.get(role)
    if isinstance(avoided, str) and avoided:
        return avoided
    return None


def preferred_setup_for_archetype(state: dict[str, Any], archetype: str) -> tuple[str | None, str | None]:
    bucket = learned_archetype_preferences(state, archetype)
    preferred_setup = bucket.get("preferred_setup")
    if not isinstance(preferred_setup, str):
        return None, None
    return parse_setup_mode(preferred_setup)


def prefers_frontend_host(classification: dict[str, Any], inventory: dict[str, Any]) -> bool:
    return classification["flags"]["frontend"] and "antigravity" in inventory["effective_hosts"]


def choose_host_model(
    registry: dict[str, Any],
    *,
    role: str,
    capabilities: list[str],
    inventory: dict[str, Any],
    classification: dict[str, Any],
    preferred_lane: dict[str, Any] | None = None,
    learned_preferred_host: str | None = None,
    learned_avoided_host: str | None = None,
) -> dict[str, Any]:
    allowed_hosts = inventory["effective_hosts"]
    allowed_models = inventory["effective_models_by_host"]
    posture = inventory["budget_posture"]

    def model_for(host_name: str, candidates: list[str]) -> tuple[str | None, str | None]:
        supported = [model for model in candidates if model in allowed_models.get(host_name, [])]
        if not supported:
            return None, None
        model_name = supported[0]
        reasoning = None
        if host_name == "codex":
            if posture == "cost-aware":
                reasoning = "medium"
            elif role in {"builder", "orchestrator", "planner"}:
                reasoning = "high"
            else:
                reasoning = "medium"
        return model_name, reasoning

    if preferred_lane:
        host_name = preferred_lane.get("host")
        model_name = preferred_lane.get("model")
        if host_name in allowed_hosts and model_name in allowed_models.get(host_name, []):
            payload = {
                "host": host_name,
                "model": model_name,
                "reasoning_effort": preferred_lane.get("reasoning_effort"),
                "credit_pool": preferred_lane.get("credit_pool"),
            }
            if payload["reasoning_effort"] is None and host_name == "codex":
                payload["reasoning_effort"] = "high" if role in {"builder", "orchestrator"} else "medium"
            return payload
        if host_name in allowed_hosts and model_name is None:
            inferred_model, reasoning = model_for(host_name, list(allowed_models.get(host_name, [])))
            if inferred_model:
                return {
                    "host": host_name,
                    "model": inferred_model,
                    "reasoning_effort": preferred_lane.get("reasoning_effort", reasoning),
                    "credit_pool": preferred_lane.get("credit_pool"),
                }

    candidates: list[tuple[str, list[str], str]] = []
    # Build candidates from registry hosts and their models, ordered by role fit.
    registry_hosts = allowed_models

    def registry_candidates(preferred_order: list[str]) -> list[tuple[str, list[str], str]]:
        """Build candidate list from registry, with preferred hosts first."""
        seen: set[str] = set()
        result: list[tuple[str, list[str], str]] = []
        for host_name in preferred_order:
            if host_name in registry_hosts and host_name not in seen:
                seen.add(host_name)
                result.append((host_name, list(registry_hosts[host_name]), "default"))
        for host_name, models in registry_hosts.items():
            if host_name not in seen:
                seen.add(host_name)
                result.append((host_name, list(models), "default"))
        return result

    if role in {"tester"} or "browser" in capabilities:
        candidates = registry_candidates(["antigravity", "codex", "gemini-cli", "claude-code"])
    elif role in {"critic", "reviewer"}:
        candidates = registry_candidates(["claude-code", "codex", "antigravity"])
    elif role in {"researcher", "planner"}:
        candidates = registry_candidates(["claude-code", "gemini-cli", "codex"])
    elif prefers_frontend_host(classification, inventory) and role == "builder":
        candidates = registry_candidates(["antigravity", "codex", "claude-code"])
    else:
        candidates = registry_candidates(["codex", "claude-code", "gemini-cli", "antigravity"])

    if posture == "cost-aware":
        adjusted: list[tuple[str, list[str], str]] = []
        for host_name, models, pool in candidates:
            low_first = sorted(models, key=lambda name: {"low": 0, "medium": 1, "high": 2}[TOOL_COST.get(name, "medium")])
            adjusted.append((host_name, low_first, pool))
        candidates = adjusted
    if learned_preferred_host:
        candidates = sorted(
            candidates,
            key=lambda item: (0 if item[0] == learned_preferred_host else 1, item[0]),
        )
    if learned_avoided_host:
        candidates = sorted(
            candidates,
            key=lambda item: (1 if item[0] == learned_avoided_host else 0, item[0]),
        )

    for host_name, models, credit_pool in candidates:
        if host_name not in allowed_hosts:
            continue
        model_name, reasoning = model_for(host_name, models)
        if model_name:
            return {
                "host": host_name,
                "model": model_name,
                "reasoning_effort": reasoning,
                "credit_pool": credit_pool,
            }

    fail("no compatible host/model remained after applying task constraints")


def recommended_persona(
    registry: dict[str, Any],
    *,
    role: str,
    host: str,
    classification: dict[str, Any],
) -> str | None:
    personas = registry.get("personas", {})
    if classification["flags"]["frontend"] and role in {"builder", "tester"} and "design-critic" in personas:
        meta = personas["design-critic"]
        if role in meta["compatible_roles"] and host in meta["compatible_hosts"]:
            return "design-critic"
    if role in {"critic", "reviewer"} and classification["archetype"] == "review-hardening" and "reality-checker" in personas:
        meta = personas["reality-checker"]
        if role in meta["compatible_roles"] and host in meta["compatible_hosts"]:
            return "reality-checker"
    return None


def build_part_stack(
    registry: dict[str, Any],
    *,
    skill_name: str,
    host_name: str,
    model_name: str,
    persona_name: str | None,
) -> tuple[list[str], list[dict[str, str]]]:
    components = [
        {
            "kind": "host-guide",
            "id": host_name,
            "path": resolve_asset(registry["hosts"][host_name]["path"]),
        },
        {
            "kind": "skill",
            "id": skill_name,
            "path": resolve_asset(registry["skills"][skill_name]["path"]),
        },
        {
            "kind": "model-note",
            "id": model_name,
            "path": resolve_asset(registry["models"][model_name]["path"]),
        },
    ]
    if persona_name:
        components.append(
            {
                "kind": "persona",
                "id": persona_name,
                "path": resolve_asset(registry["personas"][persona_name]["path"]),
            }
        )
    return [item["path"] for item in components], components


def choose_task_parts(
    classification: dict[str, Any],
    *,
    coordination: str,
    continuity: str,
    force_research: bool = False,
) -> list[dict[str, Any]]:
    flags = classification["flags"]
    research_required = flags["research"] or force_research
    pre_implementation_research = bool(classification.get("pre_implementation_research"))
    task_type = classification["task_type"]
    issue_summary = classification.get("issue_summary") or {}
    if task_type == "review-only":
        return [
            {
                "part_id": "review",
                "name": "review",
                "objective": "Review the target work, find risks, and judge whether it is ready.",
                "role": "reviewer" if coordination == "coordinated" else "critic",
                "capabilities": ["review", "verification"],
                "lane_hint": "reviewer" if coordination == "coordinated" else "critic",
            }
        ]
    if research_required and (pre_implementation_research or not flags["implementation"]):
        parts = [
            {
                "part_id": "research",
                "name": "research",
                "objective": "Gather the missing evidence and reduce uncertainty before committing to execution.",
                "role": "researcher",
                "capabilities": ["research", "evidence", "synthesis"],
                "lane_hint": "planner",
            }
        ]
        if coordination == "coordinated":
            if flags["frontend"]:
                parts.append(
                    {
                        "part_id": "design",
                        "name": "design exploration",
                        "objective": "Explore the UX, visual system, and component choices before implementation starts.",
                        "role": "builder",
                        "capabilities": ["frontend", "design", "research"],
                        "lane_hint": "frontend-builder",
                    }
                )
            if continuity == "full":
                parts.append(
                    {
                        "part_id": "synthesis",
                        "name": "synthesis",
                        "objective": "Consolidate findings into an implementation-ready brief with decisions, tradeoffs, and open questions.",
                        "role": "converger",
                        "capabilities": ["research", "synthesis", "decision-making"],
                        "lane_hint": "planner",
                    }
                )
        return parts

    if flags.get("mixed_packet"):
        parts = [
            {
                "part_id": "core-repair",
                "name": "core repair",
                "objective": "Fix the backend, security, auth, and cleanup items with bounded scope and clear verification.",
                "role": "builder",
                "capabilities": ["implementation", "repo_edit", "verification"],
                "lane_hint": "builder",
            }
        ]
        if flags["frontend"]:
            parts.append(
                {
                    "part_id": "ui-repair",
                    "name": "ui repair",
                    "objective": "Fix the user-facing issues without taking ownership of the whole packet.",
                    "role": "builder",
                    "capabilities": ["frontend", "browser", "implementation"],
                    "lane_hint": "frontend-builder",
                }
            )
        if coordination == "coordinated":
            parts.append(
                {
                    "part_id": "verification",
                    "name": "verification",
                    "objective": "Verify the repaired issue set, challenge any unresolved assumptions, and decide whether the packet can close.",
                    "role": "reviewer" if continuity == "full" else "critic",
                    "capabilities": ["review", "verification", "critique"],
                    "lane_hint": "reviewer" if continuity == "full" else "critic",
                }
            )
        if issue_summary.get("open_count"):
            for part in parts:
                part["objective"] += f" Source issue set currently shows {issue_summary['open_count']} open items."
        return parts

    parts: list[dict[str, Any]] = []
    if flags["frontend"]:
        parts.append(
            {
                "part_id": "frontend-build",
                "name": "frontend build",
                "objective": "Implement the user-facing change with the smallest viable UI scope.",
                "role": "builder",
                "capabilities": ["frontend", "browser", "implementation"],
                "lane_hint": "frontend-builder",
            }
        )
        if coordination == "coordinated":
            parts.append(
                {
                    "part_id": "frontend-test",
                    "name": "frontend test",
                    "objective": "Verify the frontend behavior and catch browser-level regressions.",
                    "role": "tester",
                    "capabilities": ["browser", "verification", "frontend"],
                    "lane_hint": "frontend-tester",
                }
            )
    else:
        parts.append(
            {
                "part_id": "implementation",
                "name": "implementation",
                "objective": "Execute the main code change with bounded scope and verification in mind.",
                "role": "builder",
                "capabilities": ["implementation", "repo_edit", "verification"],
                "lane_hint": "builder",
            }
        )
        if coordination == "coordinated":
            if research_required and continuity == "full":
                parts.append(
                    {
                        "part_id": "research",
                        "name": "research",
                        "objective": "Collect the missing evidence in parallel so the plan can tighten before the next phase.",
                        "role": "researcher",
                        "capabilities": ["research", "evidence"],
                        "lane_hint": "planner",
                    }
                )
            else:
                parts.append(
                    {
                        "part_id": "critique",
                        "name": "critique",
                        "objective": "Independently challenge the plan and execution before the task closes.",
                        "role": "critic",
                        "capabilities": ["critique", "review"],
                        "lane_hint": "critic",
                    }
                )
    return parts


def current_phase(state: dict[str, Any]) -> dict[str, Any] | None:
    current_phase_id = state.get("current_phase_id")
    for phase in state.get("phases", []):
        if phase.get("phase_id") == current_phase_id:
            return phase
    return None


def active_plan(state: dict[str, Any]) -> dict[str, Any] | None:
    plan = deepcopy(state.get("confirmed_plan") or state.get("recommendation"))
    if plan is None:
        return None
    phase = current_phase(state)
    if phase is not None:
        plan["setup"] = deepcopy(phase.get("setup", plan.get("setup", {})))
        plan["task_parts"] = deepcopy(phase.get("task_parts", plan.get("task_parts", [])))
    return plan


def latest_checkpoint_event(state: dict[str, Any]) -> dict[str, Any] | None:
    phase = current_phase(state)
    if phase is None:
        return None
    history = phase.get("history", [])
    for item in reversed(history):
        if item.get("recommended_action"):
            return item
    return None


def phase_label(action: str, index: int) -> str:
    mapping = {
        "move_to_next_phase": f"phase {index:02d}",
        "simplify_setup": f"phase {index:02d} simplification",
        "expand_setup": f"phase {index:02d} expansion",
        "change_setup": f"phase {index:02d} reroute",
        "pause_for_research": f"phase {index:02d} research pause",
    }
    return mapping.get(action, f"phase {index:02d}")


def build_research_recommendation(
    state: dict[str, Any],
    registry: dict[str, Any],
) -> dict[str, Any]:
    classification = state.get("classification") or classify_task(state, registry)
    assignment = choose_host_model(
        registry,
        role="researcher",
        capabilities=["research", "evidence", "synthesis"],
        inventory=state["inventory"],
        classification=classification,
        preferred_lane=None,
        learned_preferred_host=preferred_host_for_role(
            state,
            classification["archetype"],
            "researcher",
        ),
    )
    persona_name = recommended_persona(
        registry,
        role="researcher",
        host=assignment["host"],
        classification=classification,
    )
    prompt_stack, stack_components = build_part_stack(
        registry,
        skill_name="researcher",
        host_name=assignment["host"],
        model_name=assignment["model"],
        persona_name=persona_name,
    )
    return {
        "task_summary": task_summary_text(state),
        "archetype": {
            "value": classification["archetype"],
            "confidence": classification["confidence"],
        },
        "setup": {
            "coordination": "solo",
            "continuity": "full",
            "why_this_is_enough": "",
            "why_not_simpler": "execution is paused because the task needs more evidence before the next step stays trustworthy.",
        },
        "confidence": {
            "level": classification["confidence"],
            "main_uncertainty": classification["remaining_uncertainty"],
        },
        "overhead": {
            "coordination": "low",
            "model_cost": TOOL_COST.get(assignment["model"], "medium"),
            "context_transfer": "low",
        },
        "task_parts": [
            {
                "part_id": "research",
                "name": "research",
                "objective": "Collect the missing evidence before the next execution phase begins.",
                "assignment": {
                    "skill": ROLE_TO_SKILL.get("researcher", "researcher"),
                    "role": "researcher",
                    "host": assignment["host"],
                    "model": assignment["model"],
                    "reasoning_effort": assignment.get("reasoning_effort"),
                    "credit_pool": assignment.get("credit_pool"),
                    "persona": persona_name,
                },
                "reason": f"{assignment['host']} is being used to unblock the task with the smallest dedicated research phase.",
                "prompt_stack": prompt_stack,
                "stack_components": stack_components,
            }
        ],
        "research": {
            "mode": "pre-planning",
            "summary": "Pause execution and gather the missing evidence before the next phase starts.",
        },
        "delivery_mode": {
            "recommended": "relaykit",
            "protocol_setup": "solo+full",
            "gate_required": False,
            "reason": "RelayKit full continuity is recommended because execution is explicitly paused on a dedicated research lane.",
            "override_hint": "",
        },
        "notable_exclusions": [],
        "next_step": "Run the research part, then checkpoint again before returning to execution.",
        "confirm_prompt": "Accept this setup, or tell me what to change.",
        "internal_preset": state.get("recommendation", {}).get("internal_preset", "balanced-default"),
    }


def build_manual_recommendation(
    state: dict[str, Any],
    registry: dict[str, Any],
    *,
    manual_plan: dict[str, Any],
) -> dict[str, Any]:
    phase_mode = manual_plan.get("phase_mode") or "implementation-phase"
    if phase_mode not in PHASE_MODES:
        fail("manual plan has invalid phase_mode")
    setup = manual_plan.get("setup") or {}
    coordination = setup.get("coordination") or ("coordinated" if len(manual_plan.get("task_parts") or []) > 1 else "solo")
    continuity = setup.get("continuity") or "full"
    if coordination not in {"solo", "coordinated"}:
        fail("manual plan has invalid setup.coordination")
    if continuity not in {"lean", "full"}:
        fail("manual plan has invalid setup.continuity")
    raw_parts = manual_plan.get("task_parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        fail("manual plan requires at least one task part")

    classification = state.get("classification") or classify_task(state, registry)
    assigned_parts: list[dict[str, Any]] = []
    selected_hosts: list[str] = []
    selected_models: list[str] = []
    for index, raw_part in enumerate(raw_parts, start=1):
        if not isinstance(raw_part, dict):
            fail(f"manual plan task_parts[{index-1}] must be an object")
        assignment_input = raw_part.get("assignment") if isinstance(raw_part.get("assignment"), dict) else raw_part
        role = str(assignment_input.get("role") or raw_part.get("role") or "builder")
        host_name = assignment_input.get("host")
        if not isinstance(host_name, str) or not host_name:
            fail(f"manual plan task_parts[{index-1}] requires `host`")
        preferred_lane = {
            "host": host_name,
            "model": assignment_input.get("model"),
            "reasoning_effort": assignment_input.get("reasoning_effort"),
            "credit_pool": assignment_input.get("credit_pool") or host_name,
        }
        capabilities = raw_part.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            capabilities = _default_capabilities_for_role(role, phase_mode=phase_mode)
        resolved_assignment = choose_host_model(
            registry,
            role=role,
            capabilities=capabilities,
            inventory=state["inventory"],
            classification=classification,
            preferred_lane=preferred_lane,
        )
        skill_name = str(assignment_input.get("skill") or raw_part.get("skill") or ROLE_TO_SKILL.get(role, "contributor"))
        persona_name = assignment_input.get("persona") or raw_part.get("persona")
        if not isinstance(persona_name, str) or not persona_name:
            persona_name = recommended_persona(
                registry,
                role=role,
                host=resolved_assignment["host"],
                classification=classification,
            )
        prompt_stack, stack_components = build_part_stack(
            registry,
            skill_name=skill_name,
            host_name=resolved_assignment["host"],
            model_name=resolved_assignment["model"],
            persona_name=persona_name,
        )
        checkpoint_policy = raw_part.get("checkpoint_policy") or assignment_input.get("checkpoint_policy") or _default_checkpoint_policy(role)
        if checkpoint_policy not in CHECKPOINT_POLICIES:
            fail(f"manual plan task_parts[{index-1}] has invalid checkpoint_policy")
        part_id = str(raw_part.get("part_id") or f"part-{index:02d}")
        assigned_parts.append(
            {
                "part_id": part_id,
                "name": str(raw_part.get("name") or part_id.replace("-", " ")),
                "objective": str(raw_part.get("objective") or _default_objective_for_role(role, phase_mode=phase_mode)),
                "assignment": {
                    "skill": skill_name,
                    "role": role,
                    "host": resolved_assignment["host"],
                    "model": resolved_assignment["model"],
                    "reasoning_effort": resolved_assignment.get("reasoning_effort"),
                    "credit_pool": resolved_assignment.get("credit_pool"),
                    "persona": persona_name,
                },
                "checkpoint_policy": checkpoint_policy,
                "reason": str(raw_part.get("reason") or f"Manual {phase_mode} plan assigned this lane to {resolved_assignment['host']}."),
                "prompt_stack": prompt_stack,
                "stack_components": stack_components,
                "output_contract": output_contract_for_part(
                    {
                        "role": role,
                        "capabilities": capabilities,
                    },
                    phase_mode=phase_mode,
                ),
            }
        )
        selected_hosts.append(resolved_assignment["host"])
        selected_models.append(resolved_assignment["model"])

    coordination_overhead = "low" if len(assigned_parts) == 1 else "medium"
    if len(set(selected_hosts)) > 1 or len(assigned_parts) > 2:
        coordination_overhead = "high"
    model_cost = max((TOOL_COST.get(model, "medium") for model in selected_models), default="medium")
    context_transfer = "low" if coordination == "solo" else ("medium" if len(set(selected_hosts)) == 1 else "high")
    why_this_is_enough = ""
    why_not_simpler = ""
    if coordination == "solo" and continuity == "lean":
        why_this_is_enough = "the plan is intentionally minimal and RelayKit is only tracking a bounded single-lane packet."
    elif coordination == "coordinated" and continuity == "lean":
        why_this_is_enough = "the plan keeps only the explicit lanes the operator asked for, without paying for full continuity."
    else:
        why_not_simpler = "the operator chose durable orchestration for this packet, so RelayKit is preserving that plan instead of re-routing it."
    verdict = _delivery_verdict_for_setup(coordination, continuity)
    return {
        "task_summary": task_summary_text(state),
        "phase_mode": phase_mode,
        "phase_summary": phase_mode_summary(phase_mode),
        "archetype": {
            "value": "manual-plan",
            "confidence": "operator-defined",
        },
        "setup": {
            "coordination": coordination,
            "continuity": continuity,
            "why_this_is_enough": why_this_is_enough,
            "why_not_simpler": why_not_simpler,
        },
        "confidence": {
            "level": "operator-defined",
            "main_uncertainty": "RelayKit is following an explicit operator plan instead of inferring one.",
        },
        "overhead": {
            "coordination": coordination_overhead,
            "model_cost": model_cost,
            "context_transfer": context_transfer,
        },
        "task_parts": assigned_parts,
        "research": {
            "mode": "manual",
            "summary": "This plan was provided directly by the operator or host agent.",
        },
        "delivery_mode": {
            "verdict": verdict,
            "recommended": "relaykit",
            "protocol_setup": f"{coordination}+{continuity}",
            "gate_required": False,
            "reason": "RelayKit is preserving an explicit operator-defined plan.",
            "override_hint": "",
        },
        "notable_exclusions": [],
        "source_issues": classification.get("issue_summary"),
        "mixed_categories": classification.get("mixed_categories", []),
        "source_artifacts": source_artifact_statuses(state),
        "next_step": "Accept this plan to create the task phase.",
        "confirm_prompt": "Accept this plan, or replace it with an updated one.",
        "internal_preset": "manual-intake",
        "learned_influence": {
            "preferred_setup": None,
            "applied_setup": False,
            "prior_task_count": 0,
            "avoided_setup": None,
            "reasoning": [
                "Operator-defined plan: RelayKit skipped automatic recommendation."
            ],
        },
        "intake_mode": "manual",
    }


def _build_learned_influence(
    state: dict[str, Any],
    archetype: str,
    learned_coordination: str | None,
    learned_continuity: str | None,
    applied_learned_setup: str | None,
    assigned_parts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a human-readable learned_influence block for recommendations."""
    bucket = learned_archetype_preferences(state, archetype)
    count = bucket.get("count", 0)
    reasons: list[str] = []
    avoided_setup = bucket.get("avoid_setup") if isinstance(bucket.get("avoid_setup"), str) else None

    if applied_learned_setup and count >= 2:
        setup_str = "+".join(p for p in [learned_coordination, learned_continuity] if p)
        reasons.append(
            f"Based on {count} prior `{archetype}` tasks, you preferred `{setup_str}` coordination."
        )
    elif avoided_setup:
        reasons.append(
            f"Prior `{archetype}` reflections marked `{avoided_setup}` as a bad fit, so RelayKit avoided treating it as a default preference."
        )

    for part in assigned_parts:
        role = part.get("assignment", {}).get("role", "")
        host = part.get("assignment", {}).get("host", "")
        learned_host = preferred_host_for_role(state, archetype, role)
        if learned_host and learned_host == host:
            reasons.append(
                f"For the `{role}` role, you previously preferred `{host}` on `{archetype}` tasks."
            )

    return {
        "preferred_setup": "+".join(
            p for p in [learned_coordination, learned_continuity] if p
        ) or None,
        "applied_setup": applied_learned_setup is not None,
        "prior_task_count": count,
        "avoided_setup": avoided_setup,
        "reasoning": reasons if reasons else ["No learned preferences applied — using defaults."],
    }


def _default_checkpoint_policy(role: str) -> str:
    """Return the default checkpoint policy for a role."""
    if role in ("reviewer", "critic"):
        return "gate"
    if role == "researcher":
        return "auto"
    return "notify"


def _change_requests_research(change_text: str) -> bool:
    lowered = change_text.lower()
    if re.search(r"\b(no research|without research|skip research)\b", lowered):
        return False
    targeted_patterns = (
        r"\bresearch(?:-|\s)?first\b",
        r"\bneed(?:s)? research\b",
        r"\bresearch before\b",
        r"\bbefore (?:implementation|coding|execution)\b",
        r"\bgather evidence\b",
        r"\bmore evidence\b",
        r"\bvalidate assumptions\b",
    )
    return any(re.search(pattern, lowered) for pattern in targeted_patterns)


def _change_requests_pre_implementation(change_text: str) -> bool:
    lowered = change_text.lower()
    targeted_patterns = (
        r"\bpre(?:-|\s)implementation\b",
        r"\bresearch(?:-|\s)?first\b",
        r"\bno implementation yet\b",
        r"\bdon['’]?t (?:implement|build|code) yet\b",
        r"\bbefore (?:implementation|coding|execution|development)\b",
        r"\ball decisions (?:must|should) be made before any implementation starts\b",
        r"\bdesign decisions?\b",
        r"\barchitecture decisions?\b",
    )
    return any(re.search(pattern, lowered) for pattern in targeted_patterns)


def _manual_mode_candidate(
    classification: dict[str, Any],
    *,
    coordination: str,
    continuity: str,
    parts: list[dict[str, Any]],
    complexity: int,
) -> bool:
    flags = classification["flags"]
    if classification["task_type"] != "execution-ready":
        return False
    if coordination != "coordinated" or continuity != "lean":
        return False
    if len(parts) != 2:
        return False
    if flags["frontend"] or flags["research"] or flags["cross_project"] or flags["pause_sensitive"]:
        return False
    if complexity > 4:
        return False
    return True


def _delivery_mode_recommendation(
    classification: dict[str, Any],
    *,
    coordination: str,
    continuity: str,
    parts: list[dict[str, Any]],
    complexity: int,
) -> dict[str, Any]:
    setup_name = f"{coordination}+{continuity}"
    if _manual_mode_candidate(
        classification,
        coordination=coordination,
        continuity=continuity,
        parts=parts,
        complexity=complexity,
    ):
        return {
            "verdict": "manual",
            "recommended": "manual",
            "protocol_setup": setup_name,
            "gate_required": True,
            "reason": "This is a small bounded two-lane task. RelayKit can still coordinate it, but the protocol is usually heavier than a direct manual handoff here.",
            "override_hint": "If you still want RelayKit state, confirm with force_protocol.",
        }
    if continuity == "full":
        reason = "RelayKit full continuity is recommended because the task shape benefits from durable checkpoints, reroute handling, or a dedicated research lane."
    elif coordination == "coordinated":
        reason = "RelayKit lean coordination is recommended because the task benefits from a second lane without paying for full continuity."
    else:
        reason = "RelayKit is light enough here and keeps the task durable without extra coordination overhead."
    return {
        "verdict": continuity,
        "recommended": "relaykit",
        "protocol_setup": setup_name,
        "gate_required": False,
        "reason": reason,
        "override_hint": "",
    }


def _effective_parsed_constraints(state: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    parsed = state["task"].get("parsed_constraints")
    if isinstance(parsed, dict) and parsed:
        return parsed
    source_text = state["task"].get("constraints_text") or state["task"]["original"]
    default_hosts = state["inventory"].get("workspace_available_hosts") or state["inventory"].get("effective_hosts") or list(registry["hosts"].keys())
    return parse_constraint_text(
        source_text,
        registry,
        default_allowed_hosts=list(default_hosts),
    )


def _explicit_split_requested(state: dict[str, Any], registry: dict[str, Any]) -> bool:
    parsed = _effective_parsed_constraints(state, registry)
    return bool(
        parsed.get("explicit_split")
        or parsed.get("preferred_hosts_by_role")
        or parsed.get("preferred_hosts_by_lane")
    )


def setup_recommendation(
    state: dict[str, Any],
    registry: dict[str, Any],
    workspace_profile: dict[str, Any] | None,
    project_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    classification = classify_task(state, registry)
    phase_mode = phase_mode_for_classification(classification)
    defaults = state["layers"]["defaults"]
    manual_setup = state.get("manual_overrides", {})
    force_research = bool(manual_setup.get("force_research"))
    research_required = classification["flags"]["research"] or force_research
    preset_name = select_internal_preset(registry, classification, state["inventory"], defaults)
    lanes = resolve_effective_lanes(
        registry,
        preset_name=preset_name,
        workspace_profile=workspace_profile,
        project_profile=project_profile,
    )

    flags = classification["flags"]
    explicit_split = _explicit_split_requested(state, registry)
    complexity = 0
    complexity += 1 if flags["implementation"] else 0
    complexity += 1 if flags["review"] else 0
    complexity += 1 if research_required else 0
    complexity += 1 if flags["frontend"] else 0
    complexity += 1 if flags["cross_project"] else 0
    complexity += 1 if flags["pause_sensitive"] else 0
    complexity += 1 if classification["confidence"] == "low" else 0

    coordination = "solo"
    if flags["frontend"] and "antigravity" in state["inventory"]["effective_hosts"]:
        coordination = "coordinated"
    elif flags["implementation"] and flags["review"]:
        coordination = "coordinated"
    elif research_required and flags["implementation"] and complexity >= 3:
        coordination = "coordinated"
    elif complexity >= 4:
        coordination = "coordinated"

    if (
        classification["confidence"] == "low"
        and coordination == "coordinated"
        and not explicit_split
        and not flags["mixed_packet"]
        and not research_required
        and not flags["cross_project"]
        and not flags["pause_sensitive"]
    ):
        coordination = "solo"

    continuity = "lean"
    if research_required or flags["pause_sensitive"] or flags["cross_project"]:
        continuity = "full"
    elif complexity >= 5:
        continuity = "full"

    learned_coordination, learned_continuity = preferred_setup_for_archetype(
        state,
        classification["archetype"],
    )
    avoided_setup = learned_archetype_preferences(state, classification["archetype"]).get("avoid_setup")
    applied_learned_setup = None
    if classification["confidence"] != "low" and learned_coordination in {"solo", "coordinated"}:
        if learned_coordination == "solo":
            if complexity <= 3 and not (flags["review"] and flags["implementation"]):
                coordination = "solo"
                applied_learned_setup = learned_coordination
        elif learned_coordination == "coordinated" and complexity >= 2:
            coordination = "coordinated"
            applied_learned_setup = learned_coordination
    if applied_learned_setup and learned_continuity in {"lean", "full"}:
        continuity = learned_continuity

    current_setup = f"{coordination}+{continuity}"
    if isinstance(avoided_setup, str) and current_setup == avoided_setup:
        if current_setup == "coordinated+full":
            if not research_required and not flags["pause_sensitive"] and not flags["cross_project"]:
                continuity = "lean"
            elif complexity <= 3:
                coordination = "solo"
        elif current_setup == "coordinated+lean" and complexity <= 3:
            coordination = "solo"
        elif current_setup == "solo+full" and not research_required and not flags["pause_sensitive"]:
            continuity = "lean"

    if manual_setup.get("coordination") in {"solo", "coordinated"}:
        coordination = manual_setup["coordination"]
    if manual_setup.get("continuity") in {"lean", "full"}:
        continuity = manual_setup["continuity"]

    parts = choose_task_parts(
        classification,
        coordination=coordination,
        continuity=continuity,
        force_research=force_research,
    )
    manual_full_requested = manual_setup.get("continuity") == "full"
    bounded_coordinated = (
        coordination == "coordinated"
        and len(parts) == 2
        and not research_required
        and not flags["frontend"]
        and not flags["cross_project"]
        and not flags["pause_sensitive"]
        and complexity < 5
    )
    if len(parts) > 2 and continuity != "full":
        continuity = "full"
        parts = choose_task_parts(
            classification,
            coordination=coordination,
            continuity=continuity,
            force_research=force_research,
        )
        bounded_coordinated = False
    elif bounded_coordinated and continuity == "full" and not manual_full_requested:
        continuity = "lean"
        parts = choose_task_parts(
            classification,
            coordination=coordination,
            continuity=continuity,
            force_research=force_research,
        )

    assigned_parts: list[dict[str, Any]] = []
    selected_hosts: list[str] = []
    selected_models: list[str] = []
    parsed_constraints = _effective_parsed_constraints(state, registry)
    for part in parts:
        preferred_lane = deepcopy(lanes.get(part["lane_hint"]) or {})
        lane_host = (parsed_constraints.get("preferred_hosts_by_lane") or {}).get(part["part_id"])
        if not lane_host:
            lane_host = (parsed_constraints.get("preferred_hosts_by_lane") or {}).get(part["lane_hint"])
        role_host = (parsed_constraints.get("preferred_hosts_by_role") or {}).get(part["role"])
        preferred_host = lane_host or role_host
        if preferred_host:
            preferred_lane["host"] = preferred_host
            preferred_lane.setdefault("credit_pool", preferred_host)
            preferred_lane.pop("model", None)
        assignment = choose_host_model(
            registry,
            role=part["role"],
            capabilities=part["capabilities"],
            inventory=state["inventory"],
            classification=classification,
            preferred_lane=preferred_lane,
            learned_preferred_host=preferred_host_for_role(
                state,
                classification["archetype"],
                part["role"],
            ),
            learned_avoided_host=avoided_host_for_role(
                state,
                classification["archetype"],
                part["role"],
            ),
        )
        skill_name = ROLE_TO_SKILL.get(part["role"], "contributor")
        persona_name = recommended_persona(
            registry,
            role=part["role"],
            host=assignment["host"],
            classification=classification,
        )
        prompt_stack, stack_components = build_part_stack(
            registry,
            skill_name=skill_name,
            host_name=assignment["host"],
            model_name=assignment["model"],
            persona_name=persona_name,
        )
        # Determine checkpoint policy: preset lane override > role default
        default_policy = _default_checkpoint_policy(part["role"])
        lane_policy = (preferred_lane or {}).get("checkpoint_policy")
        checkpoint_policy = lane_policy if lane_policy in CHECKPOINT_POLICIES else default_policy
        assigned_parts.append(
            {
                "part_id": part["part_id"],
                "name": part["name"],
                "objective": part["objective"],
                "assignment": {
                    "skill": skill_name,
                    "role": part["role"],
                    "host": assignment["host"],
                    "model": assignment["model"],
                    "reasoning_effort": assignment.get("reasoning_effort"),
                    "credit_pool": assignment.get("credit_pool"),
                    "persona": persona_name,
                },
                "checkpoint_policy": checkpoint_policy,
                "reason": part_reason(part, classification, assignment["host"]),
                "prompt_stack": prompt_stack,
                "stack_components": stack_components,
                "output_contract": output_contract_for_part(part, phase_mode=phase_mode),
            }
        )
        selected_hosts.append(assignment["host"])
        selected_models.append(assignment["model"])

    research_mode = "none"
    research_summary = ""
    if flags["research"] and not flags["implementation"]:
        research_mode = "pre-planning"
        research_summary = "Execution should wait until the missing evidence is gathered."
    elif flags["research"] and coordination == "coordinated":
        research_mode = "parallel"
        research_summary = "A bounded execution slice can start while research resolves the remaining ambiguity."
    elif classification["confidence"] == "low":
        if coordination == "solo" and continuity == "lean":
            research_mode = "none"
            research_summary = "No separate research lane is needed right now."
        else:
            research_mode = "note"
            research_summary = "No separate research lane is planned yet, but uncertainty is still high enough to watch during execution."

    coordination_overhead = "low" if len(assigned_parts) == 1 else "medium"
    if len(set(selected_hosts)) > 1 or len(assigned_parts) > 2:
        coordination_overhead = "high"
    model_cost = max((TOOL_COST.get(model, "medium") for model in selected_models), default="medium")
    context_transfer = "low" if coordination == "solo" else ("medium" if len(set(selected_hosts)) == 1 else "high")

    notable_exclusions: list[dict[str, str]] = []
    for host_name in state["inventory"]["effective_hosts"]:
        if host_name in selected_hosts:
            continue
        reason = None
        if host_name == "antigravity" and not flags["frontend"]:
            reason = "the task is not frontend-heavy enough to justify a browser-backed lane"
        elif host_name == "gemini-cli" and coordination == "solo":
            reason = "the task does not justify an overflow lane"
        elif host_name == "claude-code" and classification["task_type"] == "execution-ready" and coordination == "solo":
            reason = "the task stays bounded enough that a separate orchestration or critique lane is not worth the overhead"
        elif host_name == "codex" and classification["task_type"] == "review-only":
            reason = "this recommendation stays in analysis and critique rather than repo-edit execution"
        if reason:
            notable_exclusions.append({"host": host_name, "reason": reason})

    why_this_is_enough = ""
    why_not_simpler = ""
    if coordination == "solo" and continuity == "lean":
        why_this_is_enough = "scope is bounded, the main task part is clear, and extra coordination would add more overhead than value."
    elif coordination == "coordinated" and continuity == "lean":
        why_this_is_enough = "the task benefits from a second lane, but it stays bounded enough that full continuity would add more overhead than value."
    else:
        why_not_simpler = (
            "the task has enough complexity, uncertainty, or verification pressure that a simpler setup would likely hide risk or overload one lane."
        )
    delivery_mode = _delivery_mode_recommendation(
        classification,
        coordination=coordination,
        continuity=continuity,
        parts=assigned_parts,
        complexity=complexity,
    )
    next_step = "Accept this setup to create the task phase." if continuity == "full" else "Accept this setup to launch the task."
    confirm_prompt = "Accept this setup, or tell me what to change."
    if delivery_mode["recommended"] == "manual":
        next_step = "Manual coordination is recommended. If you still want RelayKit state, confirm with force_protocol."
        confirm_prompt = "Manual coordination is recommended for this task. Confirm with force_protocol to continue in RelayKit anyway, or tell me what to change."

    recommendation = {
        "task_summary": task_summary_text(state),
        "phase_mode": phase_mode,
        "phase_summary": phase_mode_summary(phase_mode),
        "archetype": {
            "value": classification["archetype"],
            "confidence": classification["confidence"],
        },
        "setup": {
            "coordination": coordination,
            "continuity": continuity,
            "why_this_is_enough": why_this_is_enough,
            "why_not_simpler": why_not_simpler,
        },
        "confidence": {
            "level": classification["confidence"],
            "main_uncertainty": classification["remaining_uncertainty"],
        },
        "overhead": {
            "coordination": coordination_overhead,
            "model_cost": model_cost,
            "context_transfer": context_transfer,
        },
        "task_parts": assigned_parts,
        "research": {
            "mode": research_mode,
            "summary": research_summary,
        },
        "delivery_mode": delivery_mode,
        "notable_exclusions": notable_exclusions,
        "source_issues": classification.get("issue_summary"),
        "mixed_categories": classification.get("mixed_categories", []),
        "source_artifacts": source_artifact_statuses(state),
        "next_step": next_step,
        "confirm_prompt": confirm_prompt,
        "internal_preset": preset_name,
        "learned_influence": _build_learned_influence(
            state, classification["archetype"],
            learned_coordination, learned_continuity,
            applied_learned_setup, assigned_parts,
        ),
    }
    state["classification"] = classification
    state["recommendation"] = recommendation
    return recommendation


def part_reason(part: dict[str, Any], classification: dict[str, Any], host_name: str) -> str:
    role = part.get("assignment", {}).get("role")
    if part["part_id"] == "frontend-build":
        return f"{host_name} is a better fit for browser-backed UI work than forcing frontend implementation into the main code lane."
    if part["part_id"] == "frontend-test":
        return f"{host_name} separates browser verification from implementation so the builder lane stays focused."
    if part["part_id"] == "critique":
        return f"{host_name} adds independent judgment without forcing a heavier review gate."
    if part["part_id"] == "research":
        return f"{host_name} can reduce uncertainty without blocking the main execution lane."
    if role == "reviewer":
        return f"{host_name} acts as the explicit review gate so execution and approval stay separated."
    if role == "tester":
        return f"{host_name} owns verification so execution can stay focused on implementation rather than re-checking itself."
    if role == "researcher":
        return f"{host_name} handles uncertainty reduction before more execution time is spent."
    if role == "critic":
        return f"{host_name} provides independent critique without taking over implementation ownership."
    if role == "converger":
        return f"{host_name} is being used to converge outputs and close the phase cleanly."
    if classification["task_type"] == "review-only":
        return f"{host_name} is being used as a pure review lane because the task does not require direct implementation ownership."
    return f"{host_name} is the best available fit for the main execution work under the current task constraints."


def _phase_checkpointed_parts(phase: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for event in phase.get("history", []):
        part_id = event.get("part_id")
        if not part_id or part_id in seen or not event.get("recommended_outcome"):
            continue
        seen.add(part_id)
        ordered.append(part_id)
    return ordered


def list_tasks(
    registry: dict[str, Any],
    *,
    root: Path,
    status_filter: list[str] | None = None,
) -> dict[str, Any]:
    profile_dirname = registry["defaults"]["profile_dirname"]
    tasks_root = task_root(root, profile_dirname)
    statuses = set(status_filter or [])
    tasks: list[dict[str, Any]] = []
    if tasks_root.exists():
        for state_file in sorted(tasks_root.glob("*/state.json")):
            state = _normalize_legacy_state(read_json(state_file), registry)
            status = state.get("status", "unknown")
            if statuses and status not in statuses:
                continue
            task_payload = state.get("task")
            task_summary = task_payload.get("original") if isinstance(task_payload, dict) else task_payload
            tasks.append(
                {
                    "task_id": state.get("task_id"),
                    "status": status,
                    "scope": state.get("scope"),
                    "task": task_summary,
                    "current_phase_id": state.get("current_phase_id"),
                    "updated_at": state.get("updated_at") or state.get("created_at"),
                    "state_path": str(state_file),
                }
            )
    return {
        "count": len(tasks),
        "tasks": tasks,
        "status_filter": sorted(statuses),
        "terminal_statuses": sorted(TERMINAL_STATUSES),
    }


def build_summary_markdown(state: dict[str, Any]) -> str:
    recommendation = state.get("recommendation") or {}
    required_action = orchestration_required_action(state)
    source_statuses = source_artifact_statuses(state)
    stale_plan = stale_plan_assessment(state)
    lines = [
        f"# RelayKit Task {state['task_id']}",
        "",
        f"- Status: `{state['status']}`",
        f"- Scope: `{state['scope']}`",
        f"- Task: {state['task']['original']}",
    ]
    if recommendation:
        drift = state_drift_warnings(state)
        guidance = orchestration_guidance(state)
        lines.extend(
            [
                f"- Archetype: `{recommendation['archetype']['value']}`",
                f"- Phase mode: `{recommendation.get('phase_mode', 'implementation-phase')}`",
                f"- Setup: `{recommendation['setup']['coordination']} + {recommendation['setup']['continuity']}`",
                f"- Confidence: `{recommendation['confidence']['level']}`",
                f"- Coordination overhead: `{recommendation['overhead']['coordination']}`",
            ]
        )
        source_issues = recommendation.get("source_issues") or {}
        if source_issues.get("count"):
            lines.append(f"- Source issues: `{source_issues.get('open_count', 0)}` open / `{source_issues.get('count')}` total")
        if source_statuses:
            lines.append(f"- Source artifacts tracked: `{len(source_statuses)}`")
        lines.extend(["", "## Task Parts", ""])
        for part in recommendation.get("task_parts", []):
            assignment = part["assignment"]
            line = f"- `{part['name']}` -> `{assignment['host']}` / `{assignment['model']}`"
            if assignment.get("reasoning_effort"):
                line += f" / `{assignment['reasoning_effort']}`"
            if assignment.get("persona"):
                line += f" / persona `{assignment['persona']}`"
            lines.append(line)
            lines.append(f"  Objective: {part['objective']}")
            contract = part.get("output_contract") or {}
            if contract.get("allowed_outputs"):
                lines.append(f"  Allowed outputs: {', '.join(contract['allowed_outputs'])}")
        lines.extend(
            [
                "",
                "## Continue",
                "",
                f"- Next best action: {state.get('continuation', {}).get('next_best_action', recommendation.get('next_step', 'Accept or change the setup.'))}",
                f"- Safe stop point: {state.get('continuation', {}).get('safe_stop_point', 'You can stop after the current decision is confirmed.')}",
                f"- Resume instructions: {state.get('continuation', {}).get('resume_instructions', 'Run `relaykit.py resume-task --task-id <id>` to continue.')}",
            ]
        )
        if required_action:
            lines.extend(
                [
                    "",
                    "## Required Action",
                    "",
                    f"- {required_action['message']}",
                    f"- Suggested command: `{required_action['suggested_command']}`",
                ]
            )
        if stale_plan:
            lines.extend(["", "## Plan Health", ""])
            lines.append("- Saved plan is stale and should not be treated as current.")
            lines.extend([f"- {reason}" for reason in stale_plan.get("reasons", [])])
        if drift:
            lines.extend(["", "## Drift Warnings", ""])
            lines.extend([f"- {item}" for item in drift])
        if source_statuses:
            lines.extend(["", "## Source Artifacts", ""])
            for item in source_statuses:
                counts = item.get("counts") or {}
                lines.append(
                    f"- `{item.get('status')}` — {item.get('source_path')} (open: {counts.get('open', 0)}, addressed: {counts.get('addressed_unverified', 0)}, verified: {counts.get('verified', 0)}, superseded: {counts.get('superseded', 0)})"
                )
        if guidance:
            lines.extend(["", "## Orchestration Guidance", ""])
            lines.extend([f"- {item}" for item in guidance])
        lines.extend(["", "## Orchestration Contract", ""])
        lines.extend([f"- {item}" for item in orchestration_contract(state)])
    return "\n".join(lines) + "\n"


def save_task_state(state: dict[str, Any], registry: dict[str, Any]) -> tuple[Path, Path]:
    profile_dirname = registry["defaults"]["profile_dirname"]
    root = Path(state["storage_root"])
    state["updated_at"] = now_iso()
    state_file = state_path(root, profile_dirname, state["task_id"])
    summary_file = summary_path(root, profile_dirname, state["task_id"])
    write_json(state_file, state)
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(build_summary_markdown(state), encoding="utf-8")
    return state_file, summary_file


def _normalize_legacy_part(part: dict[str, Any]) -> dict[str, Any]:
    if "assignment" in part:
        return deepcopy(part)
    assignment = {
        "skill": part.get("skill") or ROLE_TO_SKILL.get(part.get("role", ""), "contributor"),
        "role": part.get("role", "builder"),
        "host": part.get("host", "codex"),
        "model": part.get("model", "gpt-5.4"),
        "reasoning_effort": part.get("reasoning_effort"),
        "credit_pool": part.get("credit_pool"),
        "persona": (part.get("personas") or [None])[0],
    }
    normalized = {
        "part_id": part.get("part_id") or slugify(part.get("role") or "part"),
        "name": part.get("part_id") or part.get("role") or "part",
        "objective": part.get("objective") or "Continue the bounded task work.",
        "assignment": assignment,
        "checkpoint_policy": part.get("checkpoint_policy") or _default_checkpoint_policy(assignment["role"]),
        "reason": part.get("reason") or f"{assignment['host']} is assigned to this legacy task part.",
        "prompt_stack": part.get("prompt_stack") or [],
        "stack_components": part.get("stack_components") or [],
    }
    return normalized


def _normalize_legacy_state(state: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    if isinstance(state.get("task"), str):
        original_task = state["task"]
        legacy_parts = state.get("task_parts") or []
        first_part = legacy_parts[0] if legacy_parts else {}
        state["task"] = {
            "original": original_task,
            "clarified_summary": original_task,
            "scope_boundaries": None,
            "non_goals": first_part.get("excluded_scope"),
            "definition_of_done": None,
            "verification": first_part.get("verification_target"),
            "remaining_uncertainty": None,
            "constraints_text": None,
            "parsed_constraints": None,
        }
    state.setdefault("version", 0)
    state.setdefault("profile_dirname", registry["defaults"]["profile_dirname"])
    state.setdefault("updated_at", state.get("created_at"))
    state.setdefault("scope", "project" if state.get("project_root") else "workspace")
    state.setdefault("storage_root", str(Path(state.get("project_root") or state.get("workspace_root") or ".")))
    state.setdefault("inventory", {
        "workspace_available_hosts": [],
        "workspace_models_by_host": {},
        "allowed_hosts": [],
        "effective_hosts": [],
        "effective_models_by_host": {},
        "needs_task_inventory": False,
        "budget_posture": "balanced",
    })
    state.setdefault("layers", {
        "defaults": {},
        "task_constraints": {},
        "learned_tendencies": {"version": 1, "generated_at": None, "suggestions": [], "archetypes": {}},
    })
    state.setdefault("clarification", {"skipped": True, "question_cap": 6, "questions": []})
    state.setdefault("classification", None)
    state.setdefault("recommendation", None)
    state.setdefault("confirmed_plan", None)
    if isinstance(state.get("reflection"), dict):
        state["reflection"] = [state["reflection"]]
    state.setdefault("reflection", [])
    state.setdefault("continuation", {})
    state.setdefault("execution_context", None)
    legacy_parts = [_normalize_legacy_part(part) for part in state.pop("task_parts", [])]
    legacy_checkpoints = state.pop("checkpoints", [])
    if not state.get("phases") and legacy_parts:
        setup = {
            "coordination": state.pop("coordination", "solo"),
            "continuity": state.pop("continuity", "lean"),
            "why_this_is_enough": "",
            "why_not_simpler": "",
        }
        history: list[dict[str, Any]] = []
        for index, checkpoint in enumerate(legacy_checkpoints, start=1):
            history.append(
                {
                    "checkpoint_id": checkpoint.get("checkpoint_id") or f"legacy-checkpoint-{index:02d}",
                    "at": checkpoint.get("timestamp"),
                    "notes": checkpoint.get("notes", ""),
                    "recommended_outcome": checkpoint.get("outcome") or "on_track",
                    "recommended_action": checkpoint.get("recommended_action"),
                }
            )
        phase_id = state.get("current_phase_id") or "phase-01"
        state["phases"] = [
            {
                "phase_id": phase_id,
                "created_at": state.get("created_at"),
                "label": "legacy imported phase",
                "status": "complete" if state.get("status") in TERMINAL_STATUSES else "active",
                "setup": setup,
                "task_parts": legacy_parts,
                "change_reason": "none",
                "entry_action": "legacy_import",
                "history": history,
            }
        ]
        state["current_phase_id"] = phase_id
        legacy_recommendation = {
            "task_summary": state["task"]["original"],
            "archetype": {
                "value": state.pop("archetype", "custom"),
                "confidence": state.pop("confidence", "unknown"),
            },
            "setup": deepcopy(setup),
            "confidence": {
                "level": state.get("classification", {}).get("confidence") if isinstance(state.get("classification"), dict) else "unknown",
                "main_uncertainty": None,
            },
            "overhead": {
                "coordination": "low" if len(legacy_parts) <= 1 else "medium",
                "model_cost": max((TOOL_COST.get(part["assignment"]["model"], "medium") for part in legacy_parts), default="medium"),
                "context_transfer": "low" if setup["coordination"] == "solo" else "medium",
            },
            "task_parts": deepcopy(legacy_parts),
            "research": {"mode": "none", "summary": ""},
            "delivery_mode": {
                "verdict": setup["continuity"],
                "recommended": "relaykit",
                "protocol_setup": f"{setup['coordination']}+{setup['continuity']}",
                "gate_required": False,
                "reason": "Imported from a legacy RelayKit task state.",
                "override_hint": "",
            },
            "notable_exclusions": [],
            "next_step": "Inspect the imported task state and continue with the next concrete action.",
            "confirm_prompt": "",
            "internal_preset": "legacy-import",
            "learned_influence": {
                "preferred_setup": None,
                "applied_setup": False,
                "prior_task_count": 0,
                "reasoning": ["Imported from a legacy task state."],
            },
        }
        if state.get("recommendation") is None:
            state["recommendation"] = deepcopy(legacy_recommendation)
        if state.get("confirmed_plan") is None:
            state["confirmed_plan"] = deepcopy(legacy_recommendation)
    else:
        state.setdefault("phases", [])
        state.setdefault("current_phase_id", None)
    if not state.get("continuation"):
        task_id = state.get("task_id", "<id>")
        state["continuation"] = {
            "current_state": "This task was loaded from a legacy state file.",
            "next_best_action": "Inspect the task and decide whether to continue, reflect, or archive it.",
            "optional_parallel_follow_up": "",
            "safe_stop_point": "You can stop after reviewing the imported state.",
            "resume_instructions": f"Run `relaykit.py resume-task --task-id {task_id}` to continue.",
        }
    return state


def load_task_state(task_id: str, root: Path, registry: dict[str, Any]) -> dict[str, Any]:
    profile_dirname = registry["defaults"]["profile_dirname"]
    path = state_path(root, profile_dirname, task_id)
    if not path.exists():
        fail(f"task `{task_id}` is missing at `{path}`")
    state = read_json(path)
    return _normalize_legacy_state(state, registry)


def learned_tendencies(root: Path, registry: dict[str, Any]) -> dict[str, Any]:
    path = learning_summary_path(root, registry["defaults"]["profile_dirname"])
    if not path.exists():
        return {"version": 1, "generated_at": None, "suggestions": [], "archetypes": {}}
    return read_json(path)


def generate_learning_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    recent_records = records[-20:]
    summary: dict[str, Any] = {
        "version": 1,
        "generated_at": now_iso(),
        "lookback_count": len(recent_records),
        "archetypes": {},
        "suggestions": [],
    }
    for record in recent_records:
        archetype = record.get("archetype", "custom")
        bucket = summary["archetypes"].setdefault(
            archetype,
            {
                "count": 0,
                "coordination_modes": {},
                "hosts": {},
                "hosts_by_role": {},
                "worth_it": {},
                "tool_fit": {},
                "bad_setup_counts": {},
                "bad_hosts_by_role": {},
            },
        )
        bucket["count"] += 1
        setup = record.get("setup", "")
        bucket["coordination_modes"][setup] = bucket["coordination_modes"].get(setup, 0) + 1
        for host_name in record.get("selected_hosts", []):
            bucket["hosts"][host_name] = bucket["hosts"].get(host_name, 0) + 1
        for assignment in record.get("selected_assignments", []):
            role = assignment.get("role")
            host_name = assignment.get("host")
            if not isinstance(role, str) or not isinstance(host_name, str):
                continue
            role_bucket = bucket["hosts_by_role"].setdefault(role, {})
            role_bucket[host_name] = role_bucket.get(host_name, 0) + 1
        worth_it = record.get("split_worth_it", "unknown")
        bucket["worth_it"][worth_it] = bucket["worth_it"].get(worth_it, 0) + 1
        tool_fit = record.get("tool_fit", "unknown")
        bucket["tool_fit"][tool_fit] = bucket["tool_fit"].get(tool_fit, 0) + 1
        if tool_fit == "bad":
            bucket["bad_setup_counts"][setup] = bucket["bad_setup_counts"].get(setup, 0) + 1
            for assignment in record.get("selected_assignments", []):
                role = assignment.get("role")
                host_name = assignment.get("host")
                if not isinstance(role, str) or not isinstance(host_name, str):
                    continue
                role_bucket = bucket["bad_hosts_by_role"].setdefault(role, {})
                role_bucket[host_name] = role_bucket.get(host_name, 0) + 1
        solo_count = sum(
            count
            for setup, count in bucket["coordination_modes"].items()
            if isinstance(setup, str) and setup.startswith("solo+")
        )
        coordinated_count = sum(
            count
            for setup, count in bucket["coordination_modes"].items()
            if isinstance(setup, str) and setup.startswith("coordinated+")
        )
        simpler_yes = bucket["worth_it"].get("no", 0) + bucket["worth_it"].get("mixed", 0)
        simpler_no = bucket["worth_it"].get("yes", 0)
        good_or_neutral = bucket["tool_fit"].get("good", 0) + bucket["tool_fit"].get("unknown", 0)
        bad = bucket["tool_fit"].get("bad", 0)
        preferred_setup = None
        if good_or_neutral >= bad and solo_count >= 2 and solo_count >= coordinated_count:
            preferred_setup = "solo+lean"
        elif good_or_neutral >= bad and coordinated_count >= 2 and simpler_no >= simpler_yes:
            preferred_setup = "coordinated+full"
        if preferred_setup is not None:
            bucket["preferred_setup"] = preferred_setup
        if good_or_neutral >= bad:
            preferred_hosts_by_role: dict[str, str] = {}
            for role, host_counts in bucket["hosts_by_role"].items():
                total = sum(host_counts.values())
                if total < 2:
                    continue
                preferred_host, preferred_count = max(host_counts.items(), key=lambda item: item[1])
                if preferred_count / total >= 0.6:
                    preferred_hosts_by_role[role] = preferred_host
            if preferred_hosts_by_role:
                bucket["preferred_hosts_by_role"] = preferred_hosts_by_role
        elif bucket["bad_setup_counts"]:
            avoid_setup, _count = max(bucket["bad_setup_counts"].items(), key=lambda item: item[1])
            bucket["avoid_setup"] = avoid_setup
            avoid_hosts_by_role: dict[str, str] = {}
            for role, host_counts in bucket["bad_hosts_by_role"].items():
                avoid_host, _ = max(host_counts.items(), key=lambda item: item[1])
                avoid_hosts_by_role[role] = avoid_host
            if avoid_hosts_by_role:
                bucket["avoid_hosts_by_role"] = avoid_hosts_by_role
    for archetype, bucket in summary["archetypes"].items():
        yes = bucket["worth_it"].get("yes", 0)
        no = bucket["worth_it"].get("no", 0)
        if yes >= 3 and yes > no * 2:
            summary["suggestions"].append(
                {
                    "type": "tendency",
                    "message": f"You often keep coordination for `{archetype}` tasks. Consider promoting that preference into workspace defaults.",
                }
            )
    return summary


def refresh_learning_summary(root: Path, registry: dict[str, Any]) -> dict[str, Any]:
    profile_dirname = registry["defaults"]["profile_dirname"]
    records = read_recent_jsonl(learning_log_path(root, profile_dirname), 20)
    summary = generate_learning_summary(records)
    write_json(learning_summary_path(root, profile_dirname), summary)
    return summary


def next_question(state: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any] | None:
    asked_ids = {item["id"] for item in state["clarification"]["questions"]}
    if state["clarification"].get("skipped"):
        return None
    if len(asked_ids) >= state["clarification"]["question_cap"]:
        return None
    if state["inventory"].get("needs_task_inventory") and "inventory_hosts" not in asked_ids:
        return {
            "id": "inventory_hosts",
            "field": "allowed_hosts",
            "prompt": "Should I stick to your default tools for this task, or should RelayKit consider other hosts too?",
            "required": True,
        }
    if not state["task"].get("scope_boundaries") and "scope_boundaries" not in asked_ids:
        return {
            "id": "scope_boundaries",
            "field": "scope_boundaries",
            "prompt": "What is in scope for this task, and what should stay out of scope?",
            "required": True,
        }
    if not state["task"].get("definition_of_done") and "definition_of_done" not in asked_ids:
        return {
            "id": "definition_of_done",
            "field": "definition_of_done",
            "prompt": "What should count as done for this task?",
            "required": True,
        }
    if not state["task"].get("verification") and "verification" not in asked_ids:
        return {
            "id": "verification",
            "field": "verification",
            "prompt": "How should the result be verified?",
            "required": True,
        }
    if not state["task"].get("constraints_text") and "task_constraints" not in asked_ids:
        return {
            "id": "task_constraints",
            "field": "constraints_text",
            "prompt": "Any tools, models, or budget limits for this task?",
            "required": False,
        }
    if state.get("classification", {}).get("confidence") == "low" and not state["task"].get("remaining_uncertainty") and "remaining_uncertainty" not in asked_ids:
        return {
            "id": "remaining_uncertainty",
            "field": "remaining_uncertainty",
            "prompt": "What still feels uncertain enough that RelayKit should account for it?",
            "required": False,
        }
    return None


def record_question(state: dict[str, Any], question: dict[str, Any]) -> None:
    state["clarification"]["questions"].append(
        {
            "id": question["id"],
            "field": question["field"],
            "prompt": question["prompt"],
            "asked_at": now_iso(),
            "answer": None,
        }
    )


def apply_answer(
    state: dict[str, Any],
    registry: dict[str, Any],
    *,
    answer: str,
    question_id: str | None,
) -> None:
    question = None
    if question_id:
        for item in reversed(state["clarification"]["questions"]):
            if item["id"] == question_id:
                question = item
                break
    elif state["clarification"]["questions"]:
        for item in reversed(state["clarification"]["questions"]):
            if item["answer"] is None:
                question = item
                break
    if question is None:
        fail("no pending clarification question was found for this task")
    question["answer"] = answer
    field = question["field"]
    if field == "allowed_hosts":
        hosts = parse_host_mentions(answer, registry)
        if not hosts and "all" in answer.lower():
            hosts = list(state["inventory"]["workspace_available_hosts"])
        if not hosts:
            hosts = list(state["inventory"]["workspace_available_hosts"])
        state["inventory"]["allowed_hosts"] = hosts
        state["inventory"]["effective_hosts"] = hosts
        state["inventory"]["effective_models_by_host"] = effective_allowed_models(
            registry,
            {
                "allowed_models_by_host": state["inventory"]["workspace_models_by_host"],
            },
            allowed_hosts=hosts,
        )
        state["inventory"]["needs_task_inventory"] = False
    elif field == "scope_boundaries":
        state["task"]["scope_boundaries"] = answer
        if "not " in answer.lower() or "out of scope" in answer.lower():
            state["task"]["non_goals"] = answer
    elif field == "definition_of_done":
        state["task"]["definition_of_done"] = answer
    elif field == "verification":
        state["task"]["verification"] = answer
    elif field == "constraints_text":
        state["task"]["constraints_text"] = answer
        parsed = parse_constraint_text(
            answer,
            registry,
            default_allowed_hosts=state["inventory"]["effective_hosts"],
        )
        state["inventory"]["budget_posture"] = parsed["budget_posture"]
        if parsed["allowed_hosts"]:
            state["inventory"]["allowed_hosts"] = parsed["allowed_hosts"]
            state["inventory"]["effective_hosts"] = parsed["allowed_hosts"]
            state["inventory"]["effective_models_by_host"] = effective_allowed_models(
                registry,
                {
                    "allowed_models_by_host": state["inventory"]["workspace_models_by_host"],
                },
                allowed_hosts=parsed["allowed_hosts"],
            )
        state["task"]["parsed_constraints"] = parsed
    elif field == "remaining_uncertainty":
        state["task"]["remaining_uncertainty"] = answer


def maybe_recommend(
    state: dict[str, Any],
    registry: dict[str, Any],
    workspace_profile: dict[str, Any] | None,
    project_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    classification = classify_task(state, registry)
    state["classification"] = classification
    question = next_question(state, registry)
    if question is not None:
        record_question(state, question)
        state["status"] = "clarifying"
        return {
            "task_id": state["task_id"],
            "stage": "clarification",
            "question": question,
            "asked_count": len(state["clarification"]["questions"]),
            "question_cap": state["clarification"]["question_cap"],
        }
    recommendation = setup_recommendation(state, registry, workspace_profile, project_profile)
    state["status"] = "recommended"
    state["continuation"] = {
        "current_state": "Recommendation ready for confirmation.",
        "next_best_action": recommendation["next_step"],
        "optional_parallel_follow_up": "",
        "safe_stop_point": "You can stop after reviewing the recommendation.",
        "resume_instructions": f"Run `relaykit.py resume-task --task-id {state['task_id']}` to continue.",
    }
    return {
        "task_id": state["task_id"],
        "stage": "recommendation",
        "recommendation": recommendation,
        "required_action": orchestration_required_action(state),
        "orchestration_contract": orchestration_contract(state),
        "summary_path": str(summary_path(Path(state["storage_root"]), registry["defaults"]["profile_dirname"], state["task_id"])),
    }


def start_task(
    registry: dict[str, Any],
    *,
    workspace_root: Path | None,
    project_root: Path | None,
    workspace_profile: dict[str, Any] | None,
    project_profile: dict[str, Any] | None,
    task_text: str,
    task_scope: str | None = None,
    allowed_hosts: list[str] | None = None,
    intake_mode: str = "auto",
    manual_plan: dict[str, Any] | None = None,
    skip_clarification: bool = False,
    dry_run: bool = False,
    execution_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not task_text.strip():
        fail("task text is required")
    if intake_mode not in INTAKE_MODES:
        fail("intake_mode must be one of auto, guided, or manual")
    if intake_mode in {"guided", "manual"} and not isinstance(manual_plan, dict):
        fail("manual or guided intake requires a manual_plan object")

    storage_root = root_for_task(workspace_root, project_root, task_scope)
    inventory = normalize_workspace_inventory(registry, workspace_profile)
    workspace_available_hosts = inventory["available_hosts"]
    effective_hosts = allowed_hosts or list(workspace_available_hosts)
    needs_task_inventory = False
    if workspace_profile is None and not allowed_hosts and task_scope != "workspace":
        needs_task_inventory = True
        effective_hosts = []

    task_id = f"rk-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{slugify(task_text)[:18]}-{secrets.token_hex(2)}"
    state = {
        "version": TASKFLOW_VERSION,
        "task_id": task_id,
        "profile_dirname": registry["defaults"]["profile_dirname"],
        "status": "clarifying",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "storage_root": str(storage_root),
        "scope": task_scope or ("project" if project_root else "workspace"),
        "workspace_root": str(workspace_root) if workspace_root else None,
        "project_root": str(project_root) if project_root else None,
        "task": {
            "original": task_text.strip(),
            "clarified_summary": task_text.strip(),
            "scope_boundaries": None,
            "non_goals": None,
            "definition_of_done": None,
            "verification": None,
            "remaining_uncertainty": None,
            "constraints_text": None,
            "parsed_constraints": None,
        },
        "inventory": {
            "workspace_available_hosts": workspace_available_hosts,
            "workspace_models_by_host": inventory["allowed_models_by_host"],
            "allowed_hosts": effective_hosts,
            "effective_hosts": effective_hosts,
            "effective_models_by_host": effective_allowed_models(
                registry,
                inventory,
                allowed_hosts=effective_hosts,
            ) if effective_hosts else {},
            "needs_task_inventory": needs_task_inventory,
            "budget_posture": inventory["default_posture"],
        },
        "layers": {
            "defaults": merged_defaults(workspace_profile, project_profile),
            "task_constraints": {},
            "learned_tendencies": learned_tendencies(storage_root, registry),
        },
        "clarification": {
            "skipped": bool(skip_clarification),
            "question_cap": 6,
            "questions": [],
        },
        "classification": None,
        "recommendation": None,
        "confirmed_plan": None,
        "phases": [],
        "current_phase_id": None,
        "continuation": {},
        "reflection": [],
        "execution_context": deepcopy(execution_context) if execution_context else None,
        "intake_mode": intake_mode,
    }
    if skip_clarification and not effective_hosts:
        state["inventory"]["effective_hosts"] = workspace_available_hosts
        state["inventory"]["allowed_hosts"] = workspace_available_hosts
        state["inventory"]["effective_models_by_host"] = effective_allowed_models(
            registry,
            inventory,
            allowed_hosts=workspace_available_hosts,
        )
        state["inventory"]["needs_task_inventory"] = False

    if dry_run:
        state["clarification"]["skipped"] = True
        recommendation = (
            build_manual_recommendation(state, registry, manual_plan=manual_plan)
            if intake_mode in {"guided", "manual"}
            else setup_recommendation(state, registry, workspace_profile, project_profile)
        )
        return {
            "task_id": state["task_id"],
            "stage": "dry_run",
            "dry_run": True,
            "recommendation": recommendation,
            "classification": state.get("classification"),
            "note": "Dry run — no state was persisted. Run start-task without --dry-run to begin.",
        }

    if intake_mode in {"guided", "manual"}:
        recommendation = build_manual_recommendation(state, registry, manual_plan=manual_plan)
        state["classification"] = classify_task(state, registry)
        state["recommendation"] = recommendation
        state["status"] = "recommended"
        state["continuation"] = {
            "current_state": "Manual plan ready for confirmation.",
            "next_best_action": recommendation["next_step"],
            "optional_parallel_follow_up": "",
            "safe_stop_point": "You can stop after reviewing the plan.",
            "resume_instructions": f"Run `relaykit.py resume-task --task-id {state['task_id']}` to continue.",
        }
        payload = {
            "task_id": state["task_id"],
            "stage": "recommendation",
            "recommendation": recommendation,
            "required_action": orchestration_required_action(state),
            "orchestration_contract": orchestration_contract(state),
        }
        state_file, summary_file = save_task_state(state, registry)
        _create_scratchpad(state, registry)
        payload["state_path"] = str(state_file)
        payload["summary_path"] = str(summary_file)
        payload["setup_hint"] = "manual-intake"
        return payload

    payload = maybe_recommend(state, registry, workspace_profile, project_profile)
    state_file, summary_file = save_task_state(state, registry)
    _create_scratchpad(state, registry)
    payload["state_path"] = str(state_file)
    payload["summary_path"] = str(summary_file)
    payload["setup_hint"] = "quick-start" if workspace_profile is None else "workspace-profile"
    return payload


def answer_task(
    registry: dict[str, Any],
    *,
    root: Path,
    task_id: str,
    answer: str,
    question_id: str | None,
    workspace_profile: dict[str, Any] | None,
    project_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    state = load_task_state(task_id, root, registry)
    apply_answer(state, registry, answer=answer, question_id=question_id)
    payload = maybe_recommend(state, registry, workspace_profile, project_profile)
    state_file, summary_file = save_task_state(state, registry)
    payload["state_path"] = str(state_file)
    payload["summary_path"] = str(summary_file)
    return payload


def apply_change_request(
    state: dict[str, Any],
    registry: dict[str, Any],
    *,
    change_text: str,
    workspace_profile: dict[str, Any] | None,
    project_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    lowered = change_text.lower()
    state.setdefault("manual_overrides", {})
    if re.search(r"\bsolo\b", lowered):
        state["manual_overrides"]["coordination"] = "solo"
    if re.search(r"\bcoordinated\b", lowered) or re.search(r"\bmulti-tool\b", lowered) or re.search(r"\bmultiple tools\b", lowered):
        state["manual_overrides"]["coordination"] = "coordinated"
    if re.search(r"\blean\b", lowered):
        state["manual_overrides"]["continuity"] = "lean"
    if re.search(r"\bfull\b", lowered):
        state["manual_overrides"]["continuity"] = "full"
    if _change_requests_pre_implementation(change_text):
        state["manual_overrides"]["pre_implementation_research"] = True
        state["manual_overrides"]["force_research"] = True
        state["manual_overrides"]["coordination"] = "coordinated"
        state["manual_overrides"]["continuity"] = "full"
    if _change_requests_research(change_text):
        state["manual_overrides"]["force_research"] = True
        state["manual_overrides"]["coordination"] = "coordinated"
        state["manual_overrides"]["continuity"] = "full"
    elif re.search(r"\b(no research|without research|skip research)\b", lowered):
        state["manual_overrides"]["force_research"] = False
        state["manual_overrides"]["pre_implementation_research"] = False
    parsed = parse_constraint_text(
        change_text,
        registry,
        default_allowed_hosts=state["inventory"]["workspace_available_hosts"],
    )
    if parsed["allowed_hosts"]:
        state["inventory"]["allowed_hosts"] = parsed["allowed_hosts"]
        state["inventory"]["effective_hosts"] = parsed["allowed_hosts"]
        state["inventory"]["effective_models_by_host"] = effective_allowed_models(
            registry,
            {
                "allowed_models_by_host": state["inventory"]["workspace_models_by_host"],
            },
            allowed_hosts=parsed["allowed_hosts"],
        )
    state.setdefault("change_requests", []).append(
        {"at": now_iso(), "text": change_text}
    )
    recommendation = setup_recommendation(state, registry, workspace_profile, project_profile)
    state["recommendation"] = recommendation
    state["status"] = "recommended"
    state["continuation"] = {
        "current_state": "Recommendation updated with the requested changes.",
        "next_best_action": recommendation["next_step"],
        "optional_parallel_follow_up": "",
        "safe_stop_point": "You can stop after reviewing the updated recommendation.",
        "resume_instructions": f"Run `relaykit.py resume-task --task-id {state['task_id']}` to continue.",
    }
    return {
        "task_id": state["task_id"],
        "stage": "recommendation",
        "recommendation": recommendation,
        "required_action": orchestration_required_action(state),
        "orchestration_contract": orchestration_contract(state),
    }


def confirm_task(
    registry: dict[str, Any],
    *,
    root: Path,
    task_id: str,
    accept: bool,
    change_text: str | None,
    workspace_profile: dict[str, Any] | None,
    project_profile: dict[str, Any] | None,
    force_protocol: bool = False,
) -> dict[str, Any]:
    state = load_task_state(task_id, root, registry)
    if change_text:
        payload = apply_change_request(
            state,
            registry,
            change_text=change_text,
            workspace_profile=workspace_profile,
            project_profile=project_profile,
        )
        state_file, summary_file = save_task_state(state, registry)
        payload["state_path"] = str(state_file)
        payload["summary_path"] = str(summary_file)
        return payload
    if not accept:
        fail("confirm_task requires either accept=true or a non-empty change_text")
    recommendation = state.get("recommendation")
    if not recommendation:
        fail("task has no recommendation to confirm yet")
    delivery_mode = recommendation.get("delivery_mode") or {}
    if delivery_mode.get("recommended") == "manual" and not force_protocol:
        details = [str(delivery_mode.get("reason") or "Manual coordination is recommended for this task.")]
        override_hint = str(delivery_mode.get("override_hint") or "").strip()
        if override_hint:
            details.append(override_hint)
        fail("manual execution is recommended before entering RelayKit protocol", details=details)
    phase_id = f"phase-{len(state['phases']) + 1:02d}"
    phase = {
        "phase_id": phase_id,
        "created_at": now_iso(),
        "label": "initial execution",
        "status": "active",
        "phase_mode": recommendation.get("phase_mode", "implementation-phase"),
        "phase_summary": recommendation.get("phase_summary", ""),
        "setup": recommendation["setup"],
        "task_parts": recommendation["task_parts"],
        "change_reason": "none",
        "entry_action": "confirm",
        "history": [],
    }
    state["phases"].append(phase)
    state["current_phase_id"] = phase_id
    state["confirmed_plan"] = deepcopy(recommendation)
    state["status"] = "active" if recommendation["setup"]["continuity"] == "full" else "launched"
    launch_bundle = None
    if recommendation["setup"]["continuity"] == "lean":
        launch_bundle = build_launch_bundle(state, recommendation["task_parts"], registry, verbosity="ultra-compact")
    state["continuation"] = {
        "current_state": "The task is confirmed and ready to run.",
        "next_best_action": (
            "Launch the bundled task parts, then checkpoint as soon as the first concrete artifact, blocker, or verified finding appears."
            if launch_bundle
            else "Start the first task part with the assigned tool and model, then checkpoint as soon as the first concrete artifact, blocker, or verified finding appears."
        ),
        "optional_parallel_follow_up": "None." if recommendation["setup"]["coordination"] == "solo" else "Start the secondary task part only after the primary lane is clearly underway.",
        "safe_stop_point": "You can stop after the first task part has a concrete result or blocker.",
        "resume_instructions": f"Run `relaykit.py resume-task --task-id {state['task_id']}` to continue.",
    }
    payload = {
        "task_id": task_id,
        "stage": "confirmed",
        "confirmed_plan": recommendation,
        "phase": phase,
        "continuation": state["continuation"],
        "required_action": orchestration_required_action(state),
        "orchestration_contract": orchestration_contract(state),
    }
    if launch_bundle:
        payload["launch_bundle"] = launch_bundle
    if force_protocol and delivery_mode.get("recommended") == "manual":
        payload["protocol_override"] = {
            "forced": True,
            "recommended": "manual",
            "reason": delivery_mode.get("reason"),
        }
    git_enabled = git_module.resolve_git_config(workspace_profile, project_profile)
    repo_root = Path(state.get("project_root") or state.get("workspace_root") or ".")
    if git_enabled and git_module.is_git_repo(repo_root):
        payload["git_integration"] = {
            "enabled": True,
            "requires_confirmation": True,
            "prepared": False,
            "suggested_command": f"relaykit prepare-git --task-id {task_id}",
        }
    state_file, summary_file = save_task_state(state, registry)
    payload["state_path"] = str(state_file)
    payload["summary_path"] = str(summary_file)
    return payload


def infer_checkpoint_outcome(notes: str) -> str:
    lowered = notes.lower()
    if re.search(r"\b(unrecoverable|fatal)\b", lowered):
        return "failed"
    if re.search(r"(^|[.!?\n]\s*)(failed\b|failure\b|gave up\b|giving up\b)", lowered):
        return "failed"
    if re.search(r"\b(abandon(?:ed)?|cancel(?:led)?|scrap(?:ped)?|not worth)\b", lowered):
        return "abandoned"
    if re.search(r"\b(blocked|stuck)\b", lowered):
        return "blocked"
    if re.search(r"\b(can't proceed|cannot proceed|unable to continue|waiting on)\b", lowered):
        return "blocked"
    if re.search(r"\b(reroute|wrong tool|bad fit)\b", lowered):
        return "needs_reroute"
    if re.search(r"\b(next phase|phase 2|ready for next|handoff complete)\b", lowered):
        return "ready_for_next_phase"
    return "on_track"


def recommend_checkpoint_action(state: dict[str, Any], outcome: str, notes: str) -> tuple[str, str]:
    lowered = notes.lower()
    if outcome in ("failed", "abandoned"):
        return "stop", "none"
    if outcome == "blocked" and any(token in lowered for token in ["unclear", "unknown", "need research", "missing context"]):
        return "pause_for_research", "new_information"
    if outcome == "needs_reroute":
        if any(token in lowered for token in ["too many tools", "overhead", "simpler"]):
            return "simplify_setup", "setup_underperformed"
        return "change_setup", "setup_underperformed"
    if outcome == "ready_for_next_phase":
        return "move_to_next_phase", "stage_change"
    if outcome == "on_track" and any(token in lowered for token in ["one lane is enough", "critic unnecessary", "simplify"]):
        return "simplify_setup", "stage_change"
    if outcome == "on_track" and any(token in lowered for token in ["need more help", "add testing", "add critic"]):
        return "expand_setup", "stage_change"
    return "keep_setup", "none"


def checkpoint_task(
    registry: dict[str, Any],
    *,
    root: Path,
    task_id: str,
    outcome: str | None,
    notes: str,
    artifacts: dict[str, Any] | None = None,
    part_id: str | None = None,
    report_markdown: str | None = None,
    verbosity: str = "compact",
) -> dict[str, Any]:
    if verbosity not in RESULT_VERBOSITIES:
        fail(f"invalid checkpoint verbosity `{verbosity}`")
    state = load_task_state(task_id, root, registry)
    recommendation = state.get("confirmed_plan") or state.get("recommendation")
    if recommendation is None:
        fail("task must be confirmed before checkpointing")
    final_outcome = outcome or infer_checkpoint_outcome(notes)
    if final_outcome not in CHECKPOINT_OUTCOMES:
        fail(f"invalid checkpoint outcome `{final_outcome}`")
    action, reason = recommend_checkpoint_action(state, final_outcome, notes)
    current_phase_id = state.get("current_phase_id")
    phase = None
    for item in state.get("phases", []):
        if item["phase_id"] == current_phase_id:
            phase = item
            break
    if phase is None:
        fail("current phase is missing")
    _event, matched_part = _record_checkpoint_event(
        state,
        registry,
        phase=phase,
        task_id=task_id,
        part_id=part_id,
        notes=notes,
        artifacts=artifacts,
        report_markdown=report_markdown,
        final_outcome=final_outcome,
        action=action,
        reason=reason,
    )
    state["status"] = final_outcome
    state["continuation"] = {
        "current_state": f"Checkpoint recorded with outcome `{final_outcome}`.",
        "next_best_action": checkpoint_next_step(action),
        "optional_parallel_follow_up": optional_follow_up(action),
        "safe_stop_point": "Safe to stop now." if final_outcome in {"blocked", "ready_for_next_phase", "failed", "abandoned"} else "Better to continue until the current task part has another concrete result.",
        "resume_instructions": f"Run `relaykit.py resume-task --task-id {task_id}` to continue from the latest checkpoint.",
    }
    payload = {
        "task_id": task_id,
        "phase_id": current_phase_id,
        "verbosity": verbosity,
        "recommended_outcome": final_outcome,
        "change_reason": reason,
        "current_state": state["continuation"]["current_state"],
        "recommended_action": action,
        "next_best_action": state["continuation"]["next_best_action"],
        "safe_stop_point": state["continuation"]["safe_stop_point"],
        "resume_instructions": state["continuation"]["resume_instructions"],
        "apply_command": f"relaykit.py advance-task --task-id {task_id}",
        "checkpoint_policy": matched_part.get("checkpoint_policy", "gate") if matched_part else "gate",
        "report_markdown_captured": bool(report_markdown),
        "required_action": orchestration_required_action(state),
        "orchestration_contract": orchestration_contract(state),
    }
    latest_event = phase["history"][-1] if phase.get("history") else {}
    if latest_event.get("phase_warnings"):
        payload["phase_warnings"] = latest_event["phase_warnings"]
    optional_parallel_follow_up = state["continuation"]["optional_parallel_follow_up"]
    if optional_parallel_follow_up:
        payload["optional_parallel_follow_up"] = optional_parallel_follow_up
    state_file, summary_file = save_task_state(state, registry)
    if verbosity == "verbose":
        payload["remaining_uncertainty"] = state.get("classification", {}).get("remaining_uncertainty", "")
        payload["estimated_overhead"] = recommendation["overhead"]["coordination"]
        payload["observed_payoff"] = "unknown"
        payload["state_path"] = str(state_file)
        payload["summary_path"] = str(summary_file)
    return payload


def _checkpoint_event_artifacts(artifacts: dict[str, Any] | None) -> dict[str, Any] | None:
    if not artifacts:
        return None
    return {
        "findings": artifacts.get("findings", ""),
        "files_discovered": artifacts.get("files_discovered", []),
        "decisions": artifacts.get("decisions", ""),
        "blockers": artifacts.get("blockers", []),
    }


def _record_checkpoint_event(
    state: dict[str, Any],
    registry: dict[str, Any],
    *,
    phase: dict[str, Any],
    task_id: str,
    part_id: str | None,
    notes: str,
    artifacts: dict[str, Any] | None,
    report_markdown: str | None,
    final_outcome: str,
    action: str,
    reason: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    event: dict[str, Any] = {
        "at": now_iso(),
        "notes": notes,
        "recommended_outcome": final_outcome,
        "recommended_action": action,
        "change_reason": reason,
    }
    if part_id:
        event["part_id"] = part_id
    normalized_artifacts = _checkpoint_event_artifacts(artifacts)
    if normalized_artifacts:
        event["artifacts"] = normalized_artifacts
    if report_markdown:
        event["report_markdown"] = report_markdown

    matched_part = None
    if part_id:
        matched_part = next(
            (tp for tp in phase.get("task_parts", []) if tp.get("part_id") == part_id),
            None,
        )
    if matched_part and matched_part.get("git_branch"):
        git_branch = matched_part["git_branch"]
        if git_branch:
            repo_root = Path(state.get("project_root") or state.get("workspace_root") or ".")
            diff = git_module.part_diff_stat(repo_root, task_id, part_id)
            if diff:
                event.setdefault("artifacts", {})["git_diff"] = diff

    warnings = phase_contract_warnings(
        state,
        matched_part,
        notes=notes,
        artifacts=event.get("artifacts"),
        report_markdown=report_markdown,
    )
    if warnings:
        event["phase_warnings"] = warnings

    if notes.strip() or event.get("artifacts") or report_markdown:
        _append_scratchpad_entry(
            state,
            registry,
            part_id=part_id,
            notes=notes,
            artifacts=event.get("artifacts"),
            report_markdown=report_markdown,
        )
    phase["history"].append(event)
    return event, matched_part


def _aggregate_phase_outcome(outcomes: list[str]) -> str:
    precedence = [
        "failed",
        "abandoned",
        "needs_reroute",
        "blocked",
        "ready_for_next_phase",
        "on_track",
    ]
    for candidate in precedence:
        if candidate in outcomes:
            return candidate
    return "on_track"


def checkpoint_phase(
    registry: dict[str, Any],
    *,
    root: Path,
    task_id: str,
    reports: list[dict[str, Any]],
    phase_id: str | None = None,
    verbosity: str = "compact",
) -> dict[str, Any]:
    if verbosity not in RESULT_VERBOSITIES:
        fail(f"invalid checkpoint verbosity `{verbosity}`")
    state = load_task_state(task_id, root, registry)
    recommendation = state.get("confirmed_plan") or state.get("recommendation")
    if recommendation is None:
        fail("task must be confirmed before checkpointing")
    if not reports:
        fail("checkpoint-phase requires at least one report")

    target_phase_id = phase_id or state.get("current_phase_id")
    phase = next((item for item in state.get("phases", []) if item.get("phase_id") == target_phase_id), None)
    if phase is None:
        fail("current phase is missing")

    checkpoint_policies: dict[str, str] = {}
    report_summaries: list[dict[str, Any]] = []
    final_outcomes: list[str] = []
    aggregate_notes: list[str] = []
    aggregate_warnings: list[str] = []
    for report in reports:
        part_id = report.get("part_id")
        if not part_id:
            fail("each checkpoint-phase report requires part_id")
        notes = (report.get("notes") or "").strip()
        artifacts = report.get("artifacts")
        report_markdown = report.get("report_markdown")
        final_outcome = report.get("outcome") or infer_checkpoint_outcome(notes)
        if final_outcome not in CHECKPOINT_OUTCOMES:
            fail(f"invalid checkpoint outcome `{final_outcome}`")
        action, reason = recommend_checkpoint_action(state, final_outcome, notes)
        event, matched_part = _record_checkpoint_event(
            state,
            registry,
            phase=phase,
            task_id=task_id,
            part_id=part_id,
            notes=notes,
            artifacts=artifacts,
            report_markdown=report_markdown,
            final_outcome=final_outcome,
            action=action,
            reason=reason,
        )
        final_outcomes.append(final_outcome)
        aggregate_notes.append(notes)
        if matched_part:
            checkpoint_policies[part_id] = matched_part.get("checkpoint_policy", "gate")
        report_summary = {
            "part_id": part_id,
            "recommended_outcome": final_outcome,
            "recommended_action": action,
            "change_reason": reason,
            "checkpoint_policy": checkpoint_policies.get(part_id, "gate"),
            "has_report_markdown": bool(report_markdown),
        }
        if verbosity == "verbose":
            report_summary["notes"] = notes
            report_summary["artifact_keys"] = sorted((artifacts or {}).keys())
            report_summary["recorded_at"] = event.get("at")
        if event.get("phase_warnings"):
            report_summary["phase_warnings"] = event["phase_warnings"]
            aggregate_warnings.extend(event["phase_warnings"])
        report_summaries.append(report_summary)

    aggregate_outcome = _aggregate_phase_outcome(final_outcomes)
    aggregate_action, aggregate_reason = recommend_checkpoint_action(
        state,
        aggregate_outcome,
        "\n".join(note for note in aggregate_notes if note),
    )
    phase["history"].append(
        {
            "at": now_iso(),
            "notes": "\n".join(note for note in aggregate_notes if note),
            "recommended_outcome": aggregate_outcome,
            "recommended_action": aggregate_action,
            "change_reason": aggregate_reason,
            "phase_checkpoint": True,
            "report_count": len(report_summaries),
            "part_ids": [item["part_id"] for item in report_summaries],
        }
    )
    state["status"] = aggregate_outcome
    state["continuation"] = {
        "current_state": f"Phase checkpoint recorded with outcome `{aggregate_outcome}`.",
        "next_best_action": checkpoint_next_step(aggregate_action),
        "optional_parallel_follow_up": optional_follow_up(aggregate_action),
        "safe_stop_point": "Safe to stop now." if aggregate_outcome in {"blocked", "ready_for_next_phase", "failed", "abandoned"} else "Better to continue until the current phase has another concrete result.",
        "resume_instructions": f"Run `relaykit.py resume-task --task-id {task_id}` to continue from the latest checkpoint.",
    }
    payload = {
        "task_id": task_id,
        "phase_id": target_phase_id,
        "verbosity": verbosity,
        "report_count": len(report_summaries),
        "reports": report_summaries,
        "recommended_outcome": aggregate_outcome,
        "change_reason": aggregate_reason,
        "current_state": state["continuation"]["current_state"],
        "recommended_action": aggregate_action,
        "next_best_action": state["continuation"]["next_best_action"],
        "safe_stop_point": state["continuation"]["safe_stop_point"],
        "resume_instructions": state["continuation"]["resume_instructions"],
        "apply_command": f"relaykit.py advance-task --task-id {task_id}",
        "required_action": orchestration_required_action(state),
        "orchestration_contract": orchestration_contract(state),
    }
    if aggregate_warnings:
        payload["phase_warnings"] = dedupe(aggregate_warnings)
    optional_parallel_follow_up = state["continuation"]["optional_parallel_follow_up"]
    if optional_parallel_follow_up:
        payload["optional_parallel_follow_up"] = optional_parallel_follow_up
    state_file, summary_file = save_task_state(state, registry)
    if verbosity == "verbose":
        payload["remaining_uncertainty"] = state.get("classification", {}).get("remaining_uncertainty", "")
        payload["estimated_overhead"] = recommendation["overhead"]["coordination"]
        payload["observed_payoff"] = "unknown"
        payload["checkpoint_policies"] = checkpoint_policies
        payload["state_path"] = str(state_file)
        payload["summary_path"] = str(summary_file)
    return payload


def checkpoint_next_step(action: str) -> str:
    mapping = {
        "keep_setup": "Continue with the current setup and check back in after the next concrete result.",
        "simplify_setup": "Keep going, but plan to remove extra coordination at the next phase boundary.",
        "expand_setup": "Add the missing task part before the next risky step.",
        "change_setup": "Reroute the task before continuing.",
        "move_to_next_phase": "Start the next phase with a fresh setup review.",
        "pause_for_research": "Pause execution and gather the missing evidence first.",
        "stop": "Task is terminated. Run reflect-task to record learnings before moving on.",
    }
    return mapping[action]


def optional_follow_up(action: str) -> str:
    if action == "pause_for_research":
        return "If a safe execution slice still exists, isolate it before pausing."
    if action == "move_to_next_phase":
        return "Review whether the current tool assignments still fit the next phase."
    if action == "expand_setup":
        return "Add only the smallest extra task part that addresses the current gap."
    return ""


def _resume_part_summary(part: dict[str, Any]) -> dict[str, Any]:
    assignment = part.get("assignment", {})
    summary = {
        "part_id": part.get("part_id"),
        "name": part.get("name"),
        "role": assignment.get("role"),
        "host": assignment.get("host"),
        "model": assignment.get("model"),
        "checkpoint_policy": part.get("checkpoint_policy", "gate"),
    }
    if part.get("git_branch"):
        summary["git_branch"] = part["git_branch"]
    return summary


def _phase_task_part_summary(part: dict[str, Any]) -> dict[str, Any]:
    assignment = part.get("assignment", {})
    payload = {
        "part_id": part.get("part_id"),
        "name": part.get("name"),
        "checkpoint_policy": part.get("checkpoint_policy", "gate"),
        "assignment": {
            "role": assignment.get("role"),
            "host": assignment.get("host"),
            "model": assignment.get("model"),
        },
    }
    if part.get("git_branch"):
        payload["git_branch"] = part["git_branch"]
    return payload


def _phase_summary(phase: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase_id": phase.get("phase_id"),
        "label": phase.get("label"),
        "status": phase.get("status"),
        "phase_mode": phase.get("phase_mode"),
        "phase_summary": phase.get("phase_summary"),
        "setup": deepcopy(phase.get("setup", {})),
        "change_reason": phase.get("change_reason"),
        "entry_action": phase.get("entry_action"),
        "task_parts": [_phase_task_part_summary(part) for part in phase.get("task_parts", [])],
    }


TERMINAL_STATUSES = {"failed", "abandoned", "reflected"}
CHECKPOINT_POLICIES = {"auto", "notify", "gate"}


def _compact_setup_summary(setup: dict[str, Any]) -> dict[str, Any]:
    return {
        "coordination": setup.get("coordination"),
        "continuity": setup.get("continuity"),
    }


def _compact_continuation_summary(
    continuation: dict[str, Any],
    *,
    has_launch_bundle: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in ("current_state", "next_best_action", "safe_stop_point"):
        value = continuation.get(key)
        if value:
            payload[key] = value
    follow_up = continuation.get("optional_parallel_follow_up")
    if follow_up:
        payload["optional_parallel_follow_up"] = follow_up
    if not has_launch_bundle:
        instructions = continuation.get("resume_instructions")
        if instructions:
            payload["resume_instructions"] = instructions
    return payload


def _active_handoff_parts(
    state: dict[str, Any],
    plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], str]:
    current_parts = list(plan.get("task_parts", []))
    if plan.get("setup", {}).get("continuity") != "lean":
        return current_parts, current_parts, [], "all_current_parts"
    phase = current_phase(state)
    checkpointed_parts = set(_phase_checkpointed_parts(phase)) if phase else set()
    completed_part_ids = [
        part.get("part_id")
        for part in current_parts
        if part.get("part_id") in checkpointed_parts
    ]
    remaining_parts = [
        part for part in current_parts
        if part.get("part_id") not in checkpointed_parts
    ]
    scope = "remaining_parts" if checkpointed_parts else "all_current_parts"
    if not remaining_parts:
        remaining_parts = current_parts
        scope = "all_current_parts"
    return current_parts, remaining_parts, completed_part_ids, scope


def is_stale(state: dict[str, Any]) -> bool:
    if state.get("status") in TERMINAL_STATUSES:
        return False
    updated = parse_iso(state.get("updated_at"))
    if updated is None:
        return False
    if datetime.now(timezone.utc) - updated > timedelta(days=1):
        return True
    if state.get("status") in {"blocked", "needs_reroute", "ready_for_next_phase"}:
        return True
    if state.get("classification", {}).get("remaining_uncertainty"):
        return True
    return False


def resume_task(
    registry: dict[str, Any],
    *,
    root: Path,
    task_id: str,
    verbosity: str = "compact",
) -> dict[str, Any]:
    if verbosity not in RESUME_VERBOSITIES:
        fail(f"invalid resume verbosity `{verbosity}`")
    state = load_task_state(task_id, root, registry)
    payload: dict[str, Any] = {
        "task_id": task_id,
        "stage": "resume",
        "verbosity": verbosity,
        "status": state.get("status"),
        "current_phase_id": state.get("current_phase_id"),
        "resume_questions": [],
    }
    drift = state_drift_warnings(state)
    guidance = orchestration_guidance(state)
    stale_plan = stale_plan_assessment(state)
    required_action = orchestration_required_action(state)
    if drift:
        payload["drift_warnings"] = drift
    if guidance:
        payload["orchestration_guidance"] = guidance
    if stale_plan:
        payload["stale_plan"] = stale_plan
    if required_action:
        payload["required_action"] = required_action
    payload["orchestration_contract"] = orchestration_contract(state)
    payload["source_artifacts"] = source_artifact_statuses(state)
    if verbosity == "verbose":
        payload["summary"] = state.get("continuation", {})
        active_recommendation = state.get("confirmed_plan") or state.get("recommendation")
        if stale_plan:
            payload["stale_recommendation"] = active_recommendation
        else:
            payload["recommendation"] = active_recommendation
    if is_stale(state):
        payload["resume_questions"] = [
            "What changed since the last checkpoint?",
            "Should RelayKit keep the current setup or recommend a new one?",
        ]
    plan = active_plan(state)
    if stale_plan and plan:
        payload["stale_part_ids"] = [part.get("part_id") for part in plan.get("task_parts", []) if part.get("part_id")]
        return payload
    if plan and state.get("status") not in TERMINAL_STATUSES:
        if verbosity == "verbose":
            payload["setup"] = deepcopy(plan.get("setup", {}))
            parts_with_stacks: list[dict[str, Any]] = []
            for part in plan.get("task_parts", []):
                assignment = part.get("assignment", {})
                stack_paths, stack_components = build_part_stack(
                    registry,
                    skill_name=assignment.get("skill", ""),
                    host_name=assignment.get("host", ""),
                    model_name=assignment.get("model", ""),
                    persona_name=assignment.get("persona"),
                )
                parts_with_stacks.append({
                    "part_id": part.get("part_id"),
                    "name": part.get("name"),
                    "objective": part.get("objective"),
                    "prompt_stack": stack_paths,
                    "stack_components": stack_components,
                    "git_branch": part.get("git_branch"),
                    "prior_artifacts": collect_prior_artifacts(state, part.get("part_id", "")),
                })
            payload["task_parts"] = parts_with_stacks
        else:
            payload["setup"] = _compact_setup_summary(plan.get("setup", {}))
        current_parts, handoff_parts, completed_part_ids, handoff_scope = _active_handoff_parts(state, plan)
        handoff_part_ids = [part.get("part_id") for part in handoff_parts if part.get("part_id")]
        if verbosity == "compact":
            payload["task_parts"] = [
                _resume_part_summary(part)
                for part in (handoff_parts if plan.get("setup", {}).get("continuity") == "lean" else current_parts)
            ]
            handoff_available: dict[str, Any] = {
                "available": True,
                "suggested_command": f"relaykit.py resume-handoff --task-id {task_id}",
                "launch_bundle_scope": handoff_scope,
                "part_ids": handoff_part_ids,
            }
            if completed_part_ids:
                payload["completed_part_ids"] = completed_part_ids
                handoff_available["completed_part_ids"] = completed_part_ids
            payload["handoff_available"] = handoff_available
        else:
            if not payload.get("task_parts"):
                payload["task_parts"] = [
                    _resume_part_summary(part)
                    for part in current_parts
                ]
            payload["handoff_available"] = {
                "available": True,
                "suggested_command": f"relaykit.py resume-handoff --task-id {task_id}",
                "launch_bundle_scope": handoff_scope,
                "part_ids": handoff_part_ids,
            }
            if completed_part_ids:
                payload["completed_part_ids"] = completed_part_ids
        if verbosity == "compact":
            payload["summary"] = _compact_continuation_summary(
                state.get("continuation", {}),
                has_launch_bundle=False,
            )
        profile_dirname = registry["defaults"]["profile_dirname"]
        sp = scratchpad_path(root, profile_dirname, task_id)
        if sp.exists():
            payload["scratchpad_path"] = (
                _compact_display_path(str(sp), state)
                if verbosity == "compact"
                else str(sp)
            )
    elif verbosity == "compact":
        payload["summary"] = _compact_continuation_summary(
            state.get("continuation", {}),
            has_launch_bundle=False,
        )
    return payload


def resume_handoff(
    registry: dict[str, Any],
    *,
    root: Path,
    task_id: str,
    part_id: str | None = None,
    verbosity: str = "ultra-compact",
) -> dict[str, Any]:
    if verbosity not in HANDOFF_VERBOSITIES:
        fail(f"invalid handoff verbosity `{verbosity}`")
    state = load_task_state(task_id, root, registry)
    if state.get("status") in TERMINAL_STATUSES:
        fail("task is terminal; there is no active handoff to resume")
    plan = active_plan(state)
    if plan is None:
        fail("task has no active plan to resume")
    _current_parts, handoff_parts, completed_part_ids, handoff_scope = _active_handoff_parts(state, plan)
    if part_id:
        handoff_parts = [part for part in handoff_parts if part.get("part_id") == part_id]
        if not handoff_parts:
            fail(f"task part `{part_id}` is not active in the current handoff scope")
        handoff_scope = "requested_part"
    part_ids = [part.get("part_id") for part in handoff_parts if part.get("part_id")]
    payload: dict[str, Any] = {
        "task_id": task_id,
        "stage": "resume_handoff",
        "status": state.get("status"),
        "phase_id": state.get("current_phase_id"),
        "verbosity": verbosity,
        "launch_bundle_scope": handoff_scope,
        "part_ids": part_ids,
        "launch_bundle": build_launch_bundle(state, handoff_parts, registry, verbosity=verbosity),
    }
    if completed_part_ids:
        payload["completed_part_ids"] = completed_part_ids
    continuation = state.get("continuation", {})
    if continuation.get("current_state"):
        payload["current_state"] = continuation["current_state"]
    if continuation.get("safe_stop_point"):
        payload["safe_stop_point"] = continuation["safe_stop_point"]
    if state.get("storage_root"):
        sp = scratchpad_path(
            Path(state["storage_root"]),
            state.get("profile_dirname") or ".relaykit",
            task_id,
        )
        if sp.exists():
            payload["scratchpad_path"] = _compact_display_path(str(sp), state) if verbosity != "verbose" else str(sp)
    return payload


def advance_task(
    registry: dict[str, Any],
    *,
    root: Path,
    task_id: str,
    action: str | None,
    change_reason: str | None,
    notes: str | None,
    change_text: str | None,
    workspace_profile: dict[str, Any] | None,
    project_profile: dict[str, Any] | None,
    verbosity: str = "compact",
) -> dict[str, Any]:
    if verbosity not in RESULT_VERBOSITIES:
        fail(f"invalid advance verbosity `{verbosity}`")
    state = load_task_state(task_id, root, registry)
    current = current_phase(state)
    if current is None:
        fail("task must have an active phase before it can advance")
    checkpoint = latest_checkpoint_event(state)
    effective_action = action or (checkpoint or {}).get("recommended_action")
    if effective_action not in CHECKPOINT_ACTIONS:
        fail("advance-task requires an action or a prior checkpoint with a recommended action")
    effective_reason = change_reason or (checkpoint or {}).get("change_reason") or "none"
    if effective_reason not in CHANGE_REASONS:
        fail(f"invalid change reason `{effective_reason}`")

    if effective_action == "stop":
        current["status"] = "completed"
        current["history"].append(
            {
                "at": now_iso(),
                "applied_action": "stop",
                "change_reason": effective_reason,
                "notes": notes or "",
            }
        )
        state["status"] = state.get("status", "abandoned")  # preserve failed/abandoned from checkpoint
        state["continuation"] = {
            "current_state": f"Task terminated with status `{state['status']}`.",
            "next_best_action": "Run reflect-task to record learnings.",
            "optional_parallel_follow_up": "",
            "safe_stop_point": "Task is done.",
            "resume_instructions": "This task is terminated. Start a new task if needed.",
        }
        state_file, summary_file = save_task_state(state, registry)
        payload = {
            "task_id": task_id,
            "stage": "stopped",
            "verbosity": verbosity,
            "action": "stop",
            "phase_id": current["phase_id"],
            "continuation": state["continuation"],
        }
        if verbosity == "verbose":
            payload["state_path"] = str(state_file)
            payload["summary_path"] = str(summary_file)
        return payload

    if effective_action == "keep_setup":
        current["history"].append(
            {
                "at": now_iso(),
                "applied_action": effective_action,
                "change_reason": effective_reason,
                "notes": notes or "",
            }
        )
        state["status"] = "active"
        state["continuation"] = {
            "current_state": "Setup kept in place after the latest checkpoint.",
            "next_best_action": "Continue with the current task part, then checkpoint again at the next concrete result, blocker, or verified finding.",
            "optional_parallel_follow_up": "",
            "safe_stop_point": "Safe to stop now.",
            "resume_instructions": f"Run `relaykit.py resume-task --task-id {task_id}` to continue.",
        }
        state_file, summary_file = save_task_state(state, registry)
        payload = {
            "task_id": task_id,
            "stage": "continued",
            "verbosity": verbosity,
            "action": effective_action,
            "phase_id": current["phase_id"],
            "continuation": state["continuation"],
            "required_action": orchestration_required_action(state),
            "orchestration_contract": orchestration_contract(state),
        }
        if verbosity == "verbose":
            payload["state_path"] = str(state_file)
            payload["summary_path"] = str(summary_file)
        return payload

    if effective_action == "pause_for_research":
        new_plan = build_research_recommendation(state, registry)
    else:
        if effective_action == "simplify_setup":
            state.setdefault("manual_overrides", {})["coordination"] = "solo"
        elif effective_action == "expand_setup":
            state.setdefault("manual_overrides", {})["coordination"] = "coordinated"
            state["manual_overrides"]["continuity"] = "full"
        elif effective_action == "change_setup" and change_text:
            apply_change_request(
                state,
                registry,
                change_text=change_text,
                workspace_profile=workspace_profile,
                project_profile=project_profile,
            )
        new_plan = state.get("recommendation")
        if new_plan is None or effective_action in {"simplify_setup", "expand_setup", "move_to_next_phase"}:
            new_plan = setup_recommendation(state, registry, workspace_profile, project_profile)

    current["status"] = "superseded" if effective_action in {"simplify_setup", "expand_setup", "change_setup"} else "completed"
    next_phase_id = f"phase-{len(state['phases']) + 1:02d}"
    current["history"].append(
        {
            "at": now_iso(),
            "applied_action": effective_action,
            "change_reason": effective_reason,
            "notes": notes or "",
            "to_phase": next_phase_id,
        }
    )
    new_phase = {
        "phase_id": next_phase_id,
        "created_at": now_iso(),
        "label": phase_label(effective_action, len(state["phases"]) + 1),
        "status": "active",
        "setup": deepcopy(new_plan["setup"]),
        "task_parts": deepcopy(new_plan["task_parts"]),
        "change_reason": effective_reason,
        "entry_action": effective_action,
        "history": [],
    }
    state["phases"].append(new_phase)
    state["current_phase_id"] = next_phase_id
    state["confirmed_plan"] = deepcopy(new_plan)
    state["status"] = "active" if new_plan["setup"]["continuity"] == "full" else "launched"
    state["continuation"] = {
        "current_state": f"Started `{new_phase['label']}` with action `{effective_action}`.",
        "next_best_action": "Start the first task part in the new phase, then checkpoint after the first concrete artifact, blocker, or verified finding.",
        "optional_parallel_follow_up": "None." if new_plan["setup"]["coordination"] == "solo" else "Bring up secondary parts only after the main part is underway.",
        "safe_stop_point": "Safe to stop now." if effective_action == "pause_for_research" else "Better to continue until the new phase has a concrete result.",
        "resume_instructions": f"Run `relaykit.py resume-task --task-id {task_id}` to continue.",
    }
    state_file, summary_file = save_task_state(state, registry)
    payload = {
        "task_id": task_id,
        "stage": "advanced",
        "verbosity": verbosity,
        "action": effective_action,
        "phase": _phase_summary(new_phase) if verbosity == "compact" else new_phase,
        "continuation": state["continuation"],
        "required_action": orchestration_required_action(state),
        "orchestration_contract": orchestration_contract(state),
    }
    if verbosity == "verbose":
        payload["confirmed_plan"] = new_plan
        payload["state_path"] = str(state_file)
        payload["summary_path"] = str(summary_file)
    return payload


def inspect_task(
    registry: dict[str, Any],
    *,
    root: Path,
    task_id: str,
) -> dict[str, Any]:
    state = load_task_state(task_id, root, registry)
    return {
        "task_id": task_id,
        "defaults": state["layers"]["defaults"],
        "task_constraints": {
            "allowed_hosts": state["inventory"]["effective_hosts"],
            "budget_posture": state["inventory"]["budget_posture"],
            "raw_constraints": state["task"].get("constraints_text"),
        },
        "learned_tendencies": state["layers"]["learned_tendencies"],
        "recommendation": state.get("recommendation"),
        "current_phase": current_phase(state),
        "latest_checkpoint": latest_checkpoint_event(state),
        "drift_warnings": state_drift_warnings(state),
        "orchestration_guidance": orchestration_guidance(state),
        "required_action": orchestration_required_action(state),
        "orchestration_contract": orchestration_contract(state),
    }


def _build_timeline(state: dict[str, Any]) -> list[dict[str, str]]:
    """Build a chronological list of key task events with elapsed times."""
    events: list[tuple[datetime | None, str]] = []
    created = parse_iso(state.get("created_at"))
    if created:
        events.append((created, "Task started"))

    # Clarification completion
    questions = state.get("clarification", {}).get("questions", [])
    if questions:
        last_answered = None
        for q in questions:
            if q.get("answer"):
                ts = parse_iso(q.get("answered_at"))
                if ts and (last_answered is None or ts > last_answered):
                    last_answered = ts
        if last_answered:
            events.append((last_answered, "Clarification complete"))

    # Phase events
    for phase in state.get("phases", []):
        phase_created = parse_iso(phase.get("created_at"))
        if phase_created:
            events.append((phase_created, f"Phase `{phase['phase_id']}` confirmed"))
        for event in phase.get("history", []):
            ts = parse_iso(event.get("at"))
            if ts is None:
                continue
            action = event.get("applied_action") or event.get("recommended_action", "")
            outcome = event.get("recommended_outcome", "")
            part = event.get("part_id", "")
            if outcome:
                label = f"Checkpoint: {outcome}"
                if part:
                    label += f" (part: `{part}`)"
                if action:
                    label += f" → {action}"
                events.append((ts, label))
            elif action:
                events.append((ts, f"Advanced: {action}"))

    reflections = state.get("reflection") or []
    for record in reflections:
        if not isinstance(record, dict):
            continue
        ts = parse_iso(record.get("timestamp"))
        if ts:
            events.append((ts, "Reflection recorded"))

    events.sort(key=lambda e: e[0] or datetime.min.replace(tzinfo=timezone.utc))

    timeline: list[dict[str, str]] = []
    base = events[0][0] if events else None
    prev = base
    for ts, label in events:
        entry: dict[str, str] = {"event": label}
        if ts:
            entry["at"] = ts.isoformat()
            if base:
                elapsed = ts - base
                entry["elapsed"] = _duration_label(elapsed)
            if prev and ts > prev:
                gap = ts - prev
                entry["since_prev"] = f"+{_duration_label(gap)}"
        prev = ts
        timeline.append(entry)

    # Add "now" marker
    if base and state.get("status") not in TERMINAL_STATUSES:
        now = datetime.now(timezone.utc)
        total = now - base
        since = ""
        if prev:
            gap = now - prev
            since = f"+{_duration_label(gap)}"
        timeline.append({
            "event": f"← now ({_duration_label(total)} elapsed)",
            "since_prev": since,
        })

    return timeline


def show_task(
    registry: dict[str, Any],
    *,
    root: Path,
    task_id: str,
) -> dict[str, Any]:
    state = load_task_state(task_id, root, registry)
    payload = {
        "task_id": task_id,
        "status": state["status"],
        "task": state["task"]["original"] if isinstance(state.get("task"), dict) else state.get("task"),
        "continuation": state.get("continuation"),
        "current_phase_id": state.get("current_phase_id"),
        "latest_checkpoint": latest_checkpoint_event(state),
        "timeline": _build_timeline(state),
        "drift_warnings": state_drift_warnings(state),
        "orchestration_guidance": orchestration_guidance(state),
        "required_action": orchestration_required_action(state),
        "orchestration_contract": orchestration_contract(state),
        "source_artifacts": source_artifact_statuses(state),
    }
    stale_plan = stale_plan_assessment(state)
    if stale_plan:
        payload["stale_plan"] = stale_plan
        payload["stale_recommendation"] = state.get("recommendation")
        payload["stale_confirmed_plan"] = state.get("confirmed_plan")
        payload["stale_current_phase"] = current_phase(state)
        payload["recommendation"] = None
        payload["confirmed_plan"] = None
        payload["current_phase"] = None
    else:
        payload["recommendation"] = state.get("recommendation")
        payload["confirmed_plan"] = state.get("confirmed_plan")
        payload["current_phase"] = current_phase(state)
    phase = current_phase(state)
    if phase is not None:
        checkpointed_parts = _phase_checkpointed_parts(phase)
        if len(checkpointed_parts) >= 2:
            payload["consolidation_packet"] = {
                "available": True,
                "phase_id": phase["phase_id"],
                "checkpointed_parts": checkpointed_parts,
                "suggested_command": f"relaykit render-consolidation-packet --task-id {task_id}",
            }
    return payload


def build_handoff_card(
    state: dict[str, Any],
    part: dict[str, Any],
    *,
    verbosity: str = "compact",
) -> dict[str, Any]:
    if verbosity not in HANDOFF_VERBOSITIES:
        fail(f"invalid handoff verbosity `{verbosity}`")
    assignment = part["assignment"]
    policy = part.get("checkpoint_policy", "gate")
    stop_condition = "Checkpoint when you reach a concrete result, blocker, or setup-change signal."
    if policy == "auto":
        stop_condition = "Checkpoint automatically after a concrete result; do not wait for a human gate."
    elif policy == "notify":
        stop_condition = "Checkpoint after a concrete result and notify; no human gate is required to continue."
    scratchpad = None
    if state.get("storage_root"):
        scratchpad = str(
            scratchpad_path(
                Path(state["storage_root"]),
                state.get("profile_dirname") or ".relaykit",
                state["task_id"],
            )
        )
    execution_context = state.get("execution_context")
    output_contract = part.get("output_contract") or {}
    if verbosity == "ultra-compact":
        payload = {
            "task_id": state["task_id"],
            "phase_id": state.get("current_phase_id"),
            "part_id": part["part_id"],
            "role": assignment["role"],
            "host": assignment["host"],
            "model": assignment["model"],
            "goal": part["objective"],
            "stop_condition": stop_condition,
            "stack_ids": [
                {"kind": item["kind"], "id": item["id"]}
                for item in part.get("stack_components", [])
            ],
        }
        if state.get("project_root"):
            payload["project_root"] = state["project_root"]
        if state.get("workspace_root"):
            payload["workspace_root"] = state["workspace_root"]
        if state["task"].get("verification"):
            payload["verification_target"] = state["task"]["verification"]
        if output_contract.get("allowed_outputs"):
            payload["allowed_outputs"] = output_contract["allowed_outputs"]
        if scratchpad:
            payload["scratchpad_path"] = _compact_display_path(scratchpad, state)
        ultra_execution_context = _ultra_compact_execution_context(execution_context)
        if ultra_execution_context:
            payload["execution_context"] = ultra_execution_context
        return payload
    if verbosity == "verbose":
        payload = {
            "task_id": state["task_id"],
            "phase_id": state.get("current_phase_id"),
            "part_id": part["part_id"],
            "part_name": part["name"],
            "role": assignment["role"],
            "host": assignment["host"],
            "model": assignment["model"],
            "workspace_root": state.get("workspace_root"),
            "project_root": state.get("project_root"),
            "goal": part["objective"],
            "task_summary": task_summary_text(state),
            "scope_boundaries": state["task"].get("scope_boundaries") or "Not set.",
            "definition_of_done": state["task"].get("definition_of_done") or "Not set.",
            "verification_target": state["task"].get("verification") or "Not set.",
            "remaining_uncertainty": state["task"].get("remaining_uncertainty") or "None noted.",
            "phase_mode": (state.get("confirmed_plan") or state.get("recommendation") or {}).get("phase_mode"),
            "phase_summary": (state.get("confirmed_plan") or state.get("recommendation") or {}).get("phase_summary"),
            "output_contract": deepcopy(output_contract),
            "stop_condition": stop_condition,
            "scratchpad_path": scratchpad,
            "stack_components": deepcopy(part.get("stack_components", [])),
        }
        if execution_context and (execution_context.get("validated_commands") or execution_context.get("notes")):
            payload["execution_context"] = deepcopy(execution_context)
        return payload

    payload = {
        "task_id": state["task_id"],
        "phase_id": state.get("current_phase_id"),
        "part_id": part["part_id"],
        "part_name": part["name"],
        "role": assignment["role"],
        "host": assignment["host"],
        "model": assignment["model"],
        "goal": part["objective"],
        "task_summary": task_summary_text(state),
        "phase_mode": (state.get("confirmed_plan") or state.get("recommendation") or {}).get("phase_mode"),
        "stop_condition": stop_condition,
        "stack_ids": [
            {"kind": item["kind"], "id": item["id"]}
            for item in part.get("stack_components", [])
        ],
    }
    if state.get("project_root"):
        payload["project_root"] = state["project_root"]
    if state.get("workspace_root"):
        payload["workspace_root"] = state["workspace_root"]
    if state["task"].get("verification"):
        payload["verification_target"] = state["task"]["verification"]
    if state["task"].get("scope_boundaries"):
        payload["scope_boundaries"] = state["task"]["scope_boundaries"]
    if state["task"].get("definition_of_done"):
        payload["definition_of_done"] = state["task"]["definition_of_done"]
    if state["task"].get("remaining_uncertainty"):
        payload["remaining_uncertainty"] = state["task"]["remaining_uncertainty"]
    if output_contract:
        payload["output_contract"] = deepcopy(output_contract)
    if scratchpad:
        payload["scratchpad_path"] = _compact_display_path(scratchpad, state)
    compact_execution_context = _compact_execution_context(execution_context)
    if compact_execution_context:
        payload["execution_context"] = compact_execution_context
    return payload


def prepare_git(
    registry: dict[str, Any],
    *,
    root: Path,
    task_id: str,
    workspace_profile: dict[str, Any] | None,
    project_profile: dict[str, Any] | None,
    dry_run: bool,
) -> dict[str, Any]:
    state = load_task_state(task_id, root, registry)
    if not git_module.resolve_git_config(workspace_profile, project_profile):
        fail("git integration is disabled for this workspace/project")
    phase = current_phase(state)
    if phase is None:
        fail("task must have an active phase before git preparation")
    repo_root = Path(state.get("project_root") or state.get("workspace_root") or ".")
    if not git_module.is_git_repo(repo_root):
        fail(f"`{repo_root}` is not inside a git working tree")
    base = git_module.current_branch(repo_root)
    planned: list[dict[str, str]] = []
    created_branches: list[dict[str, str]] = []
    failed_branches: list[dict[str, str]] = []
    for part in phase.get("task_parts", []):
        branch = git_module.part_branch_name(task_id, part["part_id"])
        planned.append({"part_id": part["part_id"], "branch": branch})
        if not dry_run:
            created = git_module.create_part_branch(repo_root, task_id, part["part_id"], base)
            if created:
                part["git_branch"] = created
                created_branches.append({"part_id": part["part_id"], "branch": created})
            else:
                failed_branches.append({"part_id": part["part_id"], "branch": branch})
    payload = {
        "task_id": task_id,
        "stage": "git_prepared" if not dry_run and not failed_branches else ("git_prepared_partial" if not dry_run else "git_preview"),
        "dry_run": dry_run,
        "repo_root": str(repo_root),
        "base_branch": base,
        "git_branches": planned if dry_run else created_branches,
    }
    if not dry_run:
        payload["git_branches_created"] = created_branches
        payload["git_branches_failed"] = failed_branches
    if not dry_run:
        state_file, summary_file = save_task_state(state, registry)
        payload["state_path"] = str(state_file)
        payload["summary_path"] = str(summary_file)
    return payload


def collect_prior_artifacts(state: dict[str, Any], current_part_id: str) -> list[dict[str, Any]]:
    """Collect checkpoint artifacts from all phases, excluding the current part."""
    artifacts: list[dict[str, Any]] = []
    for phase in state.get("phases", []):
        for event in phase.get("history", []):
            if not event.get("artifacts"):
                continue
            if event.get("part_id") == current_part_id:
                continue
            artifacts.append({
                "part_id": event.get("part_id", "unknown"),
                "at": event.get("at", ""),
                "artifacts": event["artifacts"],
            })
    return artifacts


def render_prior_context(
    state: dict[str, Any],
    current_part_id: str,
    *,
    verbosity: str = "compact",
) -> list[str]:
    """Render prior artifacts and scratchpad pointer as markdown lines."""
    lines: list[str] = []
    prior = collect_prior_artifacts(state, current_part_id)
    scratchpad = None
    storage_root = state.get("storage_root")
    if storage_root:
        candidate = scratchpad_path(
            Path(storage_root),
            state.get("profile_dirname") or ".relaykit",
            state["task_id"],
        )
        if candidate.exists():
            scratchpad = str(candidate)

    if not prior and not scratchpad:
        return lines

    lines.extend(["## Prior Context", ""])

    if scratchpad:
        display_path = _compact_display_path(scratchpad, state) if verbosity == "compact" else scratchpad
        lines.append(f"Scratchpad: `{display_path}`")
        lines.append("")

    for entry in prior:
        a = entry["artifacts"]
        lines.append(f"### From `{entry['part_id']}` ({entry['at']})")
        lines.append("")
        if a.get("findings"):
            lines.append(f"**Findings:** {a['findings']}")
            lines.append("")
        if a.get("decisions"):
            lines.append(f"**Decisions:** {a['decisions']}")
            lines.append("")
        if a.get("files_discovered"):
            lines.append("**Files discovered:** " + ", ".join(f"`{f}`" for f in a["files_discovered"]))
            lines.append("")
        if a.get("blockers"):
            lines.append("**Blockers:** " + ", ".join(a["blockers"]))
            lines.append("")
        if verbosity == "compact":
            continue

    return lines


def _compact_task_context_lines(state: dict[str, Any]) -> list[str]:
    lines = [f"- Summary: {task_summary_text(state)}"]
    optional_fields = (
        ("scope_boundaries", "Scope boundaries"),
        ("definition_of_done", "Definition of done"),
        ("verification", "Verification"),
        ("remaining_uncertainty", "Remaining uncertainty"),
    )
    for key, label in optional_fields:
        value = state["task"].get(key)
        if value:
            lines.append(f"- {label}: {value}")
    return lines


def _report_markdown_excerpt(markdown: str, *, limit: int = 900) -> str:
    text = (markdown or "").strip()
    if not text:
        return ""
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    if not blocks:
        return ""
    excerpt_blocks: list[str] = []
    for block in blocks:
        excerpt_blocks.append(block)
        if len(excerpt_blocks) >= 2:
            break
    excerpt = "\n\n".join(excerpt_blocks)
    if len(excerpt) <= limit:
        return excerpt
    return excerpt[: limit - 3].rstrip() + "..."


def _tail_text_excerpt(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    tail = text[-limit:]
    newline_index = tail.find("\n")
    if newline_index != -1:
        trimmed = tail[newline_index + 1 :].lstrip()
        if trimmed:
            return trimmed
    return tail


def render_task_part_markdown(
    state: dict[str, Any],
    part: dict[str, Any],
    *,
    verbosity: str = "compact",
) -> str:
    assignment = part["assignment"]
    handoff_card = build_handoff_card(state, part, verbosity=verbosity)
    execution_context = state.get("execution_context") or {}
    policy = part.get("checkpoint_policy", "gate")
    policy_labels = {
        "auto": "auto (log only, no human pause)",
        "notify": "notify (record and notify, does not block)",
        "gate": "gate (requires human approval)",
    }
    if verbosity == "ultra-compact":
        lines = [
            f"# RelayKit Task Part: {part['name']}",
            "",
            f"- `{assignment['host']}` / `{assignment['model']}` / `{policy}` checkpoint",
            f"- Task: `{state['task_id']}` · Phase: `{state.get('current_phase_id') or 'unconfirmed'}`",
            "",
            "## Goal",
            "",
            part["objective"],
            "",
        ]
        phase_mode = (state.get("confirmed_plan") or state.get("recommendation") or {}).get("phase_mode")
        if phase_mode:
            lines.extend(["## Phase Mode", "", f"`{phase_mode}`", ""])
        if state["task"].get("verification"):
            lines.extend(["## Verify", "", state["task"]["verification"], ""])
    elif verbosity == "verbose":
        lines = [
            f"# RelayKit Task Part: {part['name']}",
            "",
            f"- Task id: `{state['task_id']}`",
            f"- Scope: `{state['scope']}`",
            f"- Phase: `{state.get('current_phase_id') or 'unconfirmed'}`",
            f"- Part id: `{part['part_id']}`",
            f"- Host: `{assignment['host']}`",
            f"- Model: `{assignment['model']}`",
        ]
        if assignment.get("reasoning_effort"):
            lines.append(f"- Reasoning effort: `{assignment['reasoning_effort']}`")
        if assignment.get("persona"):
            lines.append(f"- Persona: `{assignment['persona']}`")
        if part.get("git_branch"):
            lines.append(f"- Git branch: `{part['git_branch']}`")
        lines.append(f"- Checkpoint policy: `{policy_labels.get(policy, policy)}`")
        lines.extend(["", "## Objective", "", part["objective"], "", "## Why This Assignment", "", part["reason"], "", "## Task Context", ""])
        lines.extend(
            [
                f"- Summary: {task_summary_text(state)}",
                f"- Scope boundaries: {state['task'].get('scope_boundaries') or 'Not set.'}",
                f"- Definition of done: {state['task'].get('definition_of_done') or 'Not set.'}",
                f"- Verification: {state['task'].get('verification') or 'Not set.'}",
                f"- Remaining uncertainty: {state['task'].get('remaining_uncertainty') or 'None noted.'}",
                "",
            ]
        )
    else:
        lines = [
            f"# RelayKit Task Part: {part['name']}",
            "",
            f"- `{assignment['host']}` / `{assignment['model']}` / `{policy}` checkpoint",
            f"- Task: `{state['task_id']}` · Phase: `{state.get('current_phase_id') or 'unconfirmed'}`",
            "",
            "## Objective",
            "",
            part["objective"],
            "",
            f"Assignment fit: {part['reason']}",
            "",
            "## Task Context",
            "",
        ]
        lines.extend(_compact_task_context_lines(state))
        lines.append("")
    phase_mode = (state.get("confirmed_plan") or state.get("recommendation") or {}).get("phase_mode")
    phase_summary = (state.get("confirmed_plan") or state.get("recommendation") or {}).get("phase_summary")
    output_contract = part.get("output_contract") or {}
    if phase_mode and verbosity != "ultra-compact":
        lines.extend(["## Phase Contract", "", f"- Mode: `{phase_mode}`"])
        if phase_summary:
            lines.append(f"- Summary: {phase_summary}")
        if output_contract.get("allowed_outputs"):
            lines.append(f"- Allowed outputs: {', '.join(output_contract['allowed_outputs'])}")
        if output_contract.get("disallowed_outputs"):
            lines.append(f"- Disallowed outputs: {', '.join(output_contract['disallowed_outputs'])}")
        if output_contract.get("evidence_required"):
            lines.append("- Evidence required: include explicit source links or citation-like references.")
        lines.append("")
    if verbosity != "ultra-compact":
        prior_lines = render_prior_context(state, part["part_id"], verbosity=verbosity)
        if prior_lines:
            lines.extend(prior_lines)
    compact_execution_context = _compact_execution_context(execution_context)
    ultra_execution_context = _ultra_compact_execution_context(execution_context)
    if verbosity == "ultra-compact" and ultra_execution_context:
        lines.extend(["## Runtime", ""])
        command = ultra_execution_context.get("command")
        if command:
            lines.append(f"- Run: `{command}`")
        note = ultra_execution_context.get("note")
        if note:
            lines.append(f"- Note: {note}")
        scratchpad_path = handoff_card.get("scratchpad_path")
        if scratchpad_path:
            lines.append(f"- Scratchpad: `{scratchpad_path}`")
        lines.append("")
    elif verbosity == "compact" and compact_execution_context:
        lines.extend(["## Runtime", ""])
        for item in compact_execution_context.get("validated_commands", []):
            label = "Validated command"
            if item.get("source") == "verification-fallback":
                label = "Validated fallback"
            elif item.get("source") == "verification-target":
                label = "Validated verification"
            lines.append(f"- {label}: `{item['command']}`")
        if compact_execution_context.get("note"):
            lines.append(f"- Note: {compact_execution_context['note']}")
        lines.append("")
    elif verbosity == "verbose" and (execution_context.get("validated_commands") or execution_context.get("notes")):
        lines.extend(["## Validated Runtime Context", ""])
        for item in execution_context.get("validated_commands", []):
            description = item.get("description") or item.get("source") or "validated command"
            lines.append(f"- {description}: `{item['command']}`")
        notes = execution_context.get("notes") or []
        if notes:
            if execution_context.get("validated_commands"):
                lines.append("")
                lines.append("Validated notes:")
            lines.extend([f"- {note}" for note in notes])
        lines.append("")
    lines.extend(["## Prompt Stack", ""])
    for component in part.get("stack_components", []):
        if verbosity == "verbose":
            lines.append(f"- `{component['kind']}` `{component['id']}` -> `{component['path']}`")
        else:
            lines.append(f"- `{component['kind']}` `{component['id']}`")
    lines.extend(["", "## Structured Handoff", ""])
    if verbosity == "verbose":
        lines.extend(
            [
                "Use this machine-readable handoff card to confirm the receiving host has the required task context before starting:",
                "",
                "```json",
                json.dumps(handoff_card, indent=2),
                "```",
                "",
                "## RelayKit Tools for This Phase",
                "",
                "During execution, use only these RelayKit tools:",
                "",
                "- `relaykit_checkpoint_task` — record progress, findings, or blockers",
                "- `relaykit_show_task` — check current task state",
                "- `relaykit_resume_task` — recover context if session is interrupted",
                "",
                "After completion, the orchestrator uses:",
                "",
                "- `relaykit_advance_task` — apply checkpoint action and move forward",
                "- `relaykit_reflect_task` — record learnings when the task is done",
                "",
                "Other RelayKit tools (`setup`, `doctor`, `bootstrap_host`, etc.) are for initial configuration only.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "The machine-readable handoff card is attached separately in this payload.",
                f"- Stop condition: {handoff_card['stop_condition']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Start Here",
            "",
            "Load the prompt stack, execute only this part, then checkpoint with `relaykit_checkpoint_task`.",
            "If the session is interrupted, use `relaykit_resume_handoff` to recover the next ready packet.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def _build_task_part_payload(
    state: dict[str, Any],
    part: dict[str, Any],
    *,
    verbosity: str,
) -> dict[str, Any]:
    markdown = render_task_part_markdown(state, part, verbosity=verbosity)
    handoff_card = build_handoff_card(state, part, verbosity=verbosity)
    sp = None
    if state.get("storage_root"):
        candidate = scratchpad_path(
            Path(state["storage_root"]),
            state.get("profile_dirname") or ".relaykit",
            state["task_id"],
        )
        if candidate.exists():
            sp = str(candidate)
    payload = {
        "task_id": state["task_id"],
        "phase_id": state.get("current_phase_id"),
        "part_id": part["part_id"],
        "part": part,
        "verbosity": verbosity,
        "markdown": markdown,
        "task_context": {
            "summary": task_summary_text(state),
            "scope_boundaries": state["task"].get("scope_boundaries"),
            "definition_of_done": state["task"].get("definition_of_done"),
            "verification": state["task"].get("verification"),
            "remaining_uncertainty": state["task"].get("remaining_uncertainty"),
        },
        "scratchpad_path": sp,
        "prior_artifacts": collect_prior_artifacts(state, part["part_id"]),
        "handoff_card": handoff_card,
    }
    if verbosity == "ultra-compact":
        payload["task_context"] = {
            key: value
            for key, value in {
                "verification": state["task"].get("verification"),
                "scope_boundaries": state["task"].get("scope_boundaries"),
            }.items()
            if value
        }
        payload["scratchpad_path"] = _compact_display_path(sp, state) if sp else None
        payload["prior_artifacts"] = []
    return payload


def build_launch_bundle(
    state: dict[str, Any],
    task_parts: list[dict[str, Any]],
    registry: dict[str, Any],
    *,
    verbosity: str = "ultra-compact",
) -> list[dict[str, Any]]:
    bundle: list[dict[str, Any]] = []
    for part in task_parts:
        rendered = _build_task_part_payload(state, part, verbosity=verbosity)
        bundle.append(
            {
                "part_id": part["part_id"],
                "checkpoint_policy": part.get("checkpoint_policy", "gate"),
                "handoff_card": rendered["handoff_card"],
                "markdown": rendered["markdown"],
            }
        )
    return bundle


def render_task_part(
    registry: dict[str, Any],
    *,
    root: Path,
    task_id: str,
    part_id: str,
    verbosity: str = "compact",
) -> dict[str, Any]:
    state = load_task_state(task_id, root, registry)
    plan = active_plan(state)
    if plan is None:
        fail("task has no recommendation or confirmed plan to render")
    part = next((item for item in plan.get("task_parts", []) if item.get("part_id") == part_id), None)
    if part is None:
        fail(f"task part `{part_id}` is not present in the current plan")
    return _build_task_part_payload(state, part, verbosity=verbosity)


def render_consolidation_packet(
    registry: dict[str, Any],
    *,
    root: Path,
    task_id: str,
    phase_id: str | None = None,
    verbosity: str = "compact",
) -> dict[str, Any]:
    if verbosity not in HANDOFF_VERBOSITIES:
        fail(f"invalid consolidation verbosity `{verbosity}`")
    state = load_task_state(task_id, root, registry)
    recommendation = state.get("confirmed_plan") or state.get("recommendation") or {}
    phase = current_phase(state) if phase_id is None else next(
        (item for item in state.get("phases", []) if item.get("phase_id") == phase_id),
        None,
    )
    if phase is None:
        fail("phase is missing")

    latest_by_part: dict[str, dict[str, Any]] = {}
    for event in phase.get("history", []):
        part_id = event.get("part_id")
        if part_id:
            latest_by_part[part_id] = event
    reports: list[dict[str, Any]] = []
    policy_by_part = {
        item.get("part_id"): item.get("checkpoint_policy", "gate")
        for item in phase.get("task_parts", [])
    }
    ordered_part_ids = [
        item.get("part_id")
        for item in phase.get("task_parts", [])
        if item.get("part_id") in latest_by_part
    ]
    ordered_part_ids.extend(
        part_id for part_id in latest_by_part if part_id not in ordered_part_ids
    )
    for part_id in ordered_part_ids:
        event = latest_by_part[part_id]
        reports.append(
            {
                "part_id": part_id,
                "recommended_outcome": event.get("recommended_outcome"),
                "recommended_action": event.get("recommended_action"),
                "change_reason": event.get("change_reason"),
                "notes": event.get("notes"),
                "artifacts": deepcopy(event.get("artifacts", {})),
                "report_markdown": event.get("report_markdown"),
                "checkpoint_policy": policy_by_part.get(part_id, "gate"),
            }
        )
    scratchpad_text = ""
    profile_dirname = registry["defaults"]["profile_dirname"]
    sp = scratchpad_path(root, profile_dirname, task_id)
    if sp.exists():
        scratchpad_text = sp.read_text(encoding="utf-8")
    scratchpad_limit = 4000 if verbosity == "verbose" else (700 if verbosity == "ultra-compact" else 1200)
    scratchpad_excerpt = _tail_text_excerpt(scratchpad_text, limit=scratchpad_limit)

    lines = [
        "# RelayKit Consolidation Packet",
        "",
        f"- Task id: `{task_id}`",
        f"- Phase: `{phase['phase_id']}`",
        f"- Task status: `{state.get('status')}`",
        f"- Phase mode: `{phase.get('phase_mode') or (state.get('confirmed_plan') or state.get('recommendation') or {}).get('phase_mode', 'implementation-phase')}`",
        f"- Setup: `{phase.get('setup', {}).get('coordination', 'unknown')} + {phase.get('setup', {}).get('continuity', 'unknown')}`",
        "",
        "## Phase Summary",
        "",
        f"- Task summary: {task_summary_text(state)}",
        f"- Latest checkpointed parts: {', '.join(f'`{item['part_id']}`' for item in reports) if reports else 'None yet.'}",
        "",
    ]
    phase_warnings = dedupe(
        [
            warning
            for report in reports
            for warning in (latest_by_part.get(report["part_id"], {}) or {}).get("phase_warnings", [])
        ]
    )
    if phase.get("phase_summary"):
        lines.append(f"- Phase contract: {phase['phase_summary']}")
        lines.append("")
    if phase_warnings:
        lines.extend(["## Phase Warnings", "", *[f"- {warning}" for warning in phase_warnings], ""])
    if scratchpad_excerpt:
        lines.extend(["## Scratchpad Excerpt", "", scratchpad_excerpt, ""])
    lines.extend(["## Latest Per-Part Reports", ""])
    for report in reports:
        lines.append(f"### `{report['part_id']}`")
        lines.append("")
        lines.append(f"- Outcome: `{report.get('recommended_outcome') or 'unknown'}`")
        lines.append(f"- Action: `{report.get('recommended_action') or 'unknown'}`")
        lines.append(f"- Checkpoint policy: `{report.get('checkpoint_policy') or 'gate'}`")
        if report.get("notes"):
            lines.extend(["", report["notes"], ""])
        if report.get("report_markdown"):
            if verbosity == "verbose":
                lines.extend(["#### Report", "", report["report_markdown"], ""])
            else:
                lines.extend(
                    [
                        "#### Report Summary",
                        "",
                        _report_markdown_excerpt(
                            report["report_markdown"],
                            limit=450 if verbosity == "ultra-compact" else 900,
                        ),
                        "",
                    ]
                )
        artifacts = report.get("artifacts") or {}
        warnings = latest_by_part.get(report["part_id"], {}).get("phase_warnings") or []
        if warnings:
            lines.extend(["#### Warnings", "", *[f"- {warning}" for warning in warnings], ""])
        if verbosity == "verbose" and artifacts:
            lines.extend(["#### Artifacts", "", "```json", json.dumps(artifacts, indent=2), "```", ""])
    lines.extend(
        [
            "## Consolidation Objective",
            "",
            "Synthesize the latest per-part results into one agreed recommendation, one required change set, one verification gate, and any remaining open risks.",
            "",
        ]
    )
    markdown = "\n".join(lines).strip() + "\n"
    return {
        "task_id": task_id,
        "phase_id": phase["phase_id"],
        "verbosity": verbosity,
        "phase_summary": {
            "status": state.get("status"),
            "phase_mode": phase.get("phase_mode") or recommendation.get("phase_mode"),
            "setup": deepcopy(phase.get("setup", {})),
            "task_summary": task_summary_text(state),
        },
        "reports": reports,
        "phase_warnings": phase_warnings,
        "scratchpad_path": (
            _compact_display_path(str(sp), state)
            if sp.exists() and verbosity != "verbose"
            else (str(sp) if sp.exists() else None)
        ),
        "scratchpad_excerpt": scratchpad_excerpt or None,
        "markdown": markdown,
    }


def reflect_task(
    registry: dict[str, Any],
    *,
    root: Path,
    task_id: str,
    split_worth_it: str | None,
    tool_fit: str | None,
    simpler_better: str | None,
    notes: str | None,
    apply: bool,
) -> dict[str, Any]:
    state = load_task_state(task_id, root, registry)
    recommendation = state.get("confirmed_plan") or state.get("recommendation")
    if recommendation is None:
        fail("task has no recommendation to reflect on")
    proposed = {
        "split_worth_it": "unknown" if recommendation["setup"]["coordination"] == "solo" else "mixed",
        "tool_fit": "unknown",
        "simpler_better": "no" if recommendation["setup"]["coordination"] == "solo" else "unknown",
    }
    payload = {
        "task_id": task_id,
        "proposed_reflection": proposed,
        "applied": False,
    }
    if not apply:
        return payload

    final_record = {
        "at": now_iso(),
        "task_id": task_id,
        "archetype": recommendation["archetype"]["value"],
        "setup": f"{recommendation['setup']['coordination']}+{recommendation['setup']['continuity']}",
        "selected_hosts": dedupe([part["assignment"]["host"] for part in recommendation["task_parts"]]),
        "selected_assignments": [
            {
                "part_id": part["part_id"],
                "role": part["assignment"]["role"],
                "host": part["assignment"]["host"],
                "model": part["assignment"]["model"],
            }
            for part in recommendation["task_parts"]
        ],
        "split_worth_it": split_worth_it or proposed["split_worth_it"],
        "tool_fit": tool_fit or proposed["tool_fit"],
        "simpler_better": simpler_better or proposed["simpler_better"],
        "notes": notes or "",
    }
    if final_record["split_worth_it"] not in REFLECTION_VALUES:
        fail(f"reflection field `split_worth_it` must be one of {sorted(REFLECTION_VALUES)}")
    if final_record["tool_fit"] not in TOOL_FIT_VALUES:
        fail(f"reflection field `tool_fit` must be one of {sorted(TOOL_FIT_VALUES)}")
    if final_record["simpler_better"] not in REFLECTION_VALUES:
        fail(f"reflection field `simpler_better` must be one of {sorted(REFLECTION_VALUES)}")

    profile_dirname = registry["defaults"]["profile_dirname"]
    log_path = learning_log_path(root, profile_dirname)
    append_jsonl(log_path, final_record)
    summary = refresh_learning_summary(root, registry)
    issue_updates = None
    source_supersession = None
    issue_inventory = (state.get("classification") or {}).get("issue_inventory") or []
    task_text = task_summary_text(state).lower()
    if issue_inventory and any(token in task_text for token in ["fix", "address", "resolve"]):
        issue_updates = mark_issue_inventory_addressed(
            root=root,
            profile_dirname=profile_dirname,
            issue_inventory=issue_inventory,
            task_id=task_id,
        )
    notes_text = (notes or "").lower()
    if issue_inventory and any(token in notes_text for token in ["supersede", "superseded", "obsolete", "stale source"]):
        source_supersession = mark_issue_inventory_superseded(
            root=root,
            profile_dirname=profile_dirname,
            issue_inventory=issue_inventory,
            task_id=task_id,
        )
    state["reflection"].append(final_record)
    state["layers"]["learned_tendencies"] = summary
    state["status"] = "reflected"
    state_file, summary_file = save_task_state(state, registry)
    payload.update(
        {
            "applied": True,
            "reflection": final_record,
            "learning_summary": summary,
            "state_path": str(state_file),
            "summary_path": str(summary_file),
        }
    )
    if issue_updates:
        payload["source_artifact_updates"] = issue_updates
    if source_supersession:
        payload["source_artifact_supersession"] = source_supersession
    return payload
