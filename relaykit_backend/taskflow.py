from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import secrets
from typing import Any


TASKFLOW_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_DIRNAME = "tasks"
LEARNING_LOG_FILENAME = "learning-log.jsonl"
LEARNING_SUMMARY_FILENAME = "learned-tendencies.json"

QUALITY_POSTURES = {"balanced", "cost-aware", "quality-first", "speed-first"}
CHECKPOINT_OUTCOMES = {"on_track", "blocked", "needs_reroute", "ready_for_next_phase"}
CHECKPOINT_ACTIONS = {
    "keep_setup",
    "simplify_setup",
    "expand_setup",
    "change_setup",
    "move_to_next_phase",
    "pause_for_research",
}
CHANGE_REASONS = {"stage_change", "setup_underperformed", "new_information", "scope_change", "none"}
REFLECTION_VALUES = {"yes", "no", "mixed", "unknown"}
TOOL_FIT_VALUES = {"good", "bad", "mixed", "unknown"}
TOOL_COST = {
    "claude-opus-4": "high",
    "claude-sonnet-4": "medium",
    "claude-haiku-4": "low",
    "gpt-4.1": "high",
    "gpt-4.1-mini": "low",
    "gemini-2.5-pro": "medium",
    "gemini-2.5-flash": "low",
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
REVIEW_KEYWORDS = {
    "review",
    "critic",
    "critique",
    "audit",
    "hardening",
    "qa",
    "verify",
    "verification",
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
BUGFIX_KEYWORDS = {"bug", "fix", "broken", "regression", "error", "issue"}
PAUSE_KEYWORDS = {"later", "resume", "continue later", "checkpoint", "phase"}


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


def learning_log_path(root: Path, profile_dirname: str) -> Path:
    return root / profile_dirname / LEARNING_LOG_FILENAME


def learning_summary_path(root: Path, profile_dirname: str) -> Path:
    return root / profile_dirname / LEARNING_SUMMARY_FILENAME


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


def classify_task(state: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(
        [
            state["task"]["original"],
            state["task"].get("scope_boundaries") or "",
            state["task"].get("definition_of_done") or "",
            state["task"].get("verification") or "",
            state["task"].get("remaining_uncertainty") or "",
        ]
    ).lower()
    flags = {
        "frontend": any(token in text for token in FRONTEND_KEYWORDS),
        "review": any(token in text for token in REVIEW_KEYWORDS),
        "research": any(token in text for token in RESEARCH_KEYWORDS),
        "implementation": any(token in text for token in IMPLEMENTATION_KEYWORDS),
        "bugfix": any(token in text for token in BUGFIX_KEYWORDS),
        "pause_sensitive": any(token in text for token in PAUSE_KEYWORDS),
        "cross_project": state["scope"] == "workspace",
    }

    if flags["review"] and not flags["implementation"] and not flags["research"]:
        task_type = "review-only"
        archetype = "review-hardening"
    elif flags["research"] and not flags["implementation"]:
        task_type = "exploratory"
        archetype = "research-plan"
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
        "remaining_uncertainty": remaining_uncertainty,
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
        if (
            host_name in allowed_hosts
            and model_name in allowed_models.get(host_name, [])
        ):
            payload = {
                "host": host_name,
                "model": model_name,
                "reasoning_effort": preferred_lane.get("reasoning_effort"),
                "credit_pool": preferred_lane.get("credit_pool"),
            }
            if payload["reasoning_effort"] is None and host_name == "codex":
                payload["reasoning_effort"] = "high" if role in {"builder", "orchestrator"} else "medium"
            return payload

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
) -> list[dict[str, Any]]:
    flags = classification["flags"]
    task_type = classification["task_type"]
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
    if flags["research"] and not flags["implementation"]:
        return [
            {
                "part_id": "research",
                "name": "research",
                "objective": "Gather the missing evidence and reduce uncertainty before committing to execution.",
                "role": "researcher",
                "capabilities": ["research", "evidence", "synthesis"],
                "lane_hint": "planner",
            }
        ]

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
            if flags["research"] and continuity == "full":
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
                    "skill": "researcher",
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
        "notable_exclusions": [],
        "next_step": "Run the research part, then checkpoint again before returning to execution.",
        "confirm_prompt": "Accept this setup, or tell me what to change.",
        "internal_preset": state.get("recommendation", {}).get("internal_preset", "balanced-default"),
    }


def setup_recommendation(
    state: dict[str, Any],
    registry: dict[str, Any],
    workspace_profile: dict[str, Any] | None,
    project_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    classification = classify_task(state, registry)
    defaults = state["layers"]["defaults"]
    preset_name = select_internal_preset(registry, classification, state["inventory"], defaults)
    lanes = resolve_effective_lanes(
        registry,
        preset_name=preset_name,
        workspace_profile=workspace_profile,
        project_profile=project_profile,
    )

    flags = classification["flags"]
    complexity = 0
    complexity += 1 if flags["implementation"] else 0
    complexity += 1 if flags["review"] else 0
    complexity += 1 if flags["research"] else 0
    complexity += 1 if flags["frontend"] else 0
    complexity += 1 if flags["cross_project"] else 0
    complexity += 1 if flags["pause_sensitive"] else 0
    complexity += 1 if classification["confidence"] == "low" else 0

    coordination = "solo"
    if flags["frontend"] and "antigravity" in state["inventory"]["effective_hosts"]:
        coordination = "coordinated"
    elif flags["implementation"] and flags["review"]:
        coordination = "coordinated"
    elif flags["research"] and flags["implementation"] and complexity >= 3:
        coordination = "coordinated"
    elif complexity >= 4:
        coordination = "coordinated"

    continuity = "lean"
    if coordination == "coordinated" and (classification["confidence"] != "high" or flags["research"] or flags["pause_sensitive"]):
        continuity = "full"
    elif complexity >= 5:
        continuity = "full"
    elif flags["cross_project"]:
        continuity = "full"

    learned_coordination, learned_continuity = preferred_setup_for_archetype(
        state,
        classification["archetype"],
    )
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

    manual_setup = state.get("manual_overrides", {})
    if manual_setup.get("coordination") in {"solo", "coordinated"}:
        coordination = manual_setup["coordination"]
    if manual_setup.get("continuity") in {"lean", "full"}:
        continuity = manual_setup["continuity"]

    parts = choose_task_parts(classification, coordination=coordination, continuity=continuity)
    assigned_parts: list[dict[str, Any]] = []
    selected_hosts: list[str] = []
    selected_models: list[str] = []
    for part in parts:
        preferred_lane = lanes.get(part["lane_hint"])
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
                "reason": part_reason(part, classification, assignment["host"]),
                "prompt_stack": prompt_stack,
                "stack_components": stack_components,
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
        research_mode = "note"
        research_summary = "Research is still recommended before the task closes because uncertainty remains high."

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
    else:
        why_not_simpler = (
            "the task has enough complexity, uncertainty, or verification pressure that a simpler setup would likely hide risk or overload one lane."
        )

    next_step = "Accept this setup to create the task phase." if continuity == "full" else "Accept this setup to launch the task."

    recommendation = {
        "task_summary": task_summary_text(state),
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
        "notable_exclusions": notable_exclusions,
        "next_step": next_step,
        "confirm_prompt": "Accept this setup, or tell me what to change.",
        "internal_preset": preset_name,
        "learned_influence": {
            "preferred_setup": "+".join(
                part
                for part in [learned_coordination, learned_continuity]
                if part
            ) or None,
            "applied_setup": applied_learned_setup is not None,
        },
    }
    state["classification"] = classification
    state["recommendation"] = recommendation
    return recommendation


def part_reason(part: dict[str, Any], classification: dict[str, Any], host_name: str) -> str:
    if part["part_id"] == "frontend-build":
        return f"{host_name} is a better fit for browser-backed UI work than forcing frontend implementation into the main code lane."
    if part["part_id"] == "frontend-test":
        return f"{host_name} separates browser verification from implementation so the builder lane stays focused."
    if part["part_id"] == "critique":
        return f"{host_name} adds independent judgment without forcing a heavier review gate."
    if part["part_id"] == "research":
        return f"{host_name} can reduce uncertainty without blocking the main execution lane."
    if classification["task_type"] == "review-only":
        return f"{host_name} is being used as a pure review lane because the task does not require direct implementation ownership."
    return f"{host_name} is the best available fit for the main execution work under the current task constraints."


def build_summary_markdown(state: dict[str, Any]) -> str:
    recommendation = state.get("recommendation") or {}
    lines = [
        f"# RelayKit Task {state['task_id']}",
        "",
        f"- Status: `{state['status']}`",
        f"- Scope: `{state['scope']}`",
        f"- Task: {state['task']['original']}",
    ]
    if recommendation:
        lines.extend(
            [
                f"- Archetype: `{recommendation['archetype']['value']}`",
                f"- Setup: `{recommendation['setup']['coordination']} + {recommendation['setup']['continuity']}`",
                f"- Confidence: `{recommendation['confidence']['level']}`",
                f"- Coordination overhead: `{recommendation['overhead']['coordination']}`",
                "",
                "## Task Parts",
                "",
            ]
        )
        for part in recommendation.get("task_parts", []):
            assignment = part["assignment"]
            line = f"- `{part['name']}` -> `{assignment['host']}` / `{assignment['model']}`"
            if assignment.get("reasoning_effort"):
                line += f" / `{assignment['reasoning_effort']}`"
            if assignment.get("persona"):
                line += f" / persona `{assignment['persona']}`"
            lines.append(line)
            lines.append(f"  Objective: {part['objective']}")
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


def load_task_state(task_id: str, root: Path, registry: dict[str, Any]) -> dict[str, Any]:
    profile_dirname = registry["defaults"]["profile_dirname"]
    path = state_path(root, profile_dirname, task_id)
    if not path.exists():
        fail(f"task `{task_id}` is missing at `{path}`")
    return read_json(path)


def learned_tendencies(root: Path, registry: dict[str, Any]) -> dict[str, Any]:
    path = learning_summary_path(root, registry["defaults"]["profile_dirname"])
    if not path.exists():
        return {"version": 1, "generated_at": None, "suggestions": [], "archetypes": {}}
    return read_json(path)


def generate_learning_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "version": 1,
        "generated_at": now_iso(),
        "archetypes": {},
        "suggestions": [],
    }
    for record in records:
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
        preferred_setup = None
        if solo_count >= 2 and solo_count >= coordinated_count:
            preferred_setup = "solo+lean"
        elif coordinated_count >= 2 and simpler_no >= simpler_yes:
            preferred_setup = "coordinated+full"
        if preferred_setup is not None:
            bucket["preferred_setup"] = preferred_setup
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
    records = read_jsonl(learning_log_path(root, profile_dirname))
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
            "prompt": "Which tools should RelayKit consider for this task?",
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
    skip_clarification: bool = False,
) -> dict[str, Any]:
    if not task_text.strip():
        fail("task text is required")

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

    payload = maybe_recommend(state, registry, workspace_profile, project_profile)
    state_file, summary_file = save_task_state(state, registry)
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
    if "solo" in lowered:
        state["manual_overrides"]["coordination"] = "solo"
    if "coordinated" in lowered or "multi-tool" in lowered or "multiple tools" in lowered:
        state["manual_overrides"]["coordination"] = "coordinated"
    if "lean" in lowered:
        state["manual_overrides"]["continuity"] = "lean"
    if "full" in lowered:
        state["manual_overrides"]["continuity"] = "full"
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
    phase_id = f"phase-{len(state['phases']) + 1:02d}"
    phase = {
        "phase_id": phase_id,
        "created_at": now_iso(),
        "label": "initial execution",
        "status": "active",
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
    state["continuation"] = {
        "current_state": "The task is confirmed and ready to run.",
        "next_best_action": "Start the first task part with the assigned tool and model.",
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
    }
    state_file, summary_file = save_task_state(state, registry)
    payload["state_path"] = str(state_file)
    payload["summary_path"] = str(summary_file)
    return payload


def infer_checkpoint_outcome(notes: str) -> str:
    lowered = notes.lower()
    if any(token in lowered for token in ["blocked", "can't", "cannot", "stuck"]):
        return "blocked"
    if any(token in lowered for token in ["reroute", "wrong tool", "bad fit"]):
        return "needs_reroute"
    if any(token in lowered for token in ["next phase", "phase 2", "ready for next", "handoff complete"]):
        return "ready_for_next_phase"
    return "on_track"


def recommend_checkpoint_action(state: dict[str, Any], outcome: str, notes: str) -> tuple[str, str]:
    lowered = notes.lower()
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
) -> dict[str, Any]:
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
    event = {
        "at": now_iso(),
        "notes": notes,
        "recommended_outcome": final_outcome,
        "recommended_action": action,
        "change_reason": reason,
    }
    phase["history"].append(event)
    state["status"] = final_outcome
    state["continuation"] = {
        "current_state": f"Checkpoint recorded with outcome `{final_outcome}`.",
        "next_best_action": checkpoint_next_step(action),
        "optional_parallel_follow_up": optional_follow_up(action),
        "safe_stop_point": "Safe to stop now." if final_outcome in {"blocked", "ready_for_next_phase"} else "Better to continue until the current task part has another concrete result.",
        "resume_instructions": f"Run `relaykit.py resume-task --task-id {task_id}` to continue from the latest checkpoint.",
    }
    payload = {
        "task_id": task_id,
        "phase_id": current_phase_id,
        "recommended_outcome": final_outcome,
        "change_reason": reason,
        "current_state": state["continuation"]["current_state"],
        "recommended_action": action,
        "next_best_action": state["continuation"]["next_best_action"],
        "optional_parallel_follow_up": state["continuation"]["optional_parallel_follow_up"],
        "safe_stop_point": state["continuation"]["safe_stop_point"],
        "resume_instructions": state["continuation"]["resume_instructions"],
        "apply_command": f"relaykit.py advance-task --task-id {task_id}",
        "remaining_uncertainty": state.get("classification", {}).get("remaining_uncertainty", ""),
        "estimated_overhead": recommendation["overhead"]["coordination"],
        "observed_payoff": "unknown",
    }
    state_file, summary_file = save_task_state(state, registry)
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


def is_stale(state: dict[str, Any]) -> bool:
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
) -> dict[str, Any]:
    state = load_task_state(task_id, root, registry)
    payload = {
        "task_id": task_id,
        "stage": "resume",
        "summary": state.get("continuation", {}),
        "status": state.get("status"),
        "recommendation": state.get("confirmed_plan") or state.get("recommendation"),
        "resume_questions": [],
    }
    if is_stale(state):
        payload["resume_questions"] = [
            "What changed since the last checkpoint?",
            "Should RelayKit keep the current setup or recommend a new one?",
        ]
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
) -> dict[str, Any]:
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
            "next_best_action": "Continue with the current task part until the next concrete result or blocker.",
            "optional_parallel_follow_up": "",
            "safe_stop_point": "Safe to stop now.",
            "resume_instructions": f"Run `relaykit.py resume-task --task-id {task_id}` to continue.",
        }
        state_file, summary_file = save_task_state(state, registry)
        return {
            "task_id": task_id,
            "stage": "continued",
            "action": effective_action,
            "phase_id": current["phase_id"],
            "continuation": state["continuation"],
            "state_path": str(state_file),
            "summary_path": str(summary_file),
        }

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
        "next_best_action": "Start the first task part in the new phase with the assigned tool and model.",
        "optional_parallel_follow_up": "None." if new_plan["setup"]["coordination"] == "solo" else "Bring up secondary parts only after the main part is underway.",
        "safe_stop_point": "Safe to stop now." if effective_action == "pause_for_research" else "Better to continue until the new phase has a concrete result.",
        "resume_instructions": f"Run `relaykit.py resume-task --task-id {task_id}` to continue.",
    }
    state_file, summary_file = save_task_state(state, registry)
    return {
        "task_id": task_id,
        "stage": "advanced",
        "action": effective_action,
        "phase": new_phase,
        "confirmed_plan": new_plan,
        "continuation": state["continuation"],
        "state_path": str(state_file),
        "summary_path": str(summary_file),
    }


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
    }


def show_task(
    registry: dict[str, Any],
    *,
    root: Path,
    task_id: str,
) -> dict[str, Any]:
    state = load_task_state(task_id, root, registry)
    return {
        "task_id": task_id,
        "status": state["status"],
        "task": state["task"],
        "recommendation": state.get("recommendation"),
        "confirmed_plan": state.get("confirmed_plan"),
        "continuation": state.get("continuation"),
        "current_phase_id": state.get("current_phase_id"),
        "current_phase": current_phase(state),
        "latest_checkpoint": latest_checkpoint_event(state),
    }


def render_task_part_markdown(state: dict[str, Any], part: dict[str, Any]) -> str:
    assignment = part["assignment"]
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
    lines.extend(
        [
            "",
            "## Objective",
            "",
            part["objective"],
            "",
            "## Why This Assignment",
            "",
            part["reason"],
            "",
            "## Task Context",
            "",
            f"- Summary: {task_summary_text(state)}",
            f"- Scope boundaries: {state['task'].get('scope_boundaries') or 'Not set.'}",
            f"- Definition of done: {state['task'].get('definition_of_done') or 'Not set.'}",
            f"- Verification: {state['task'].get('verification') or 'Not set.'}",
            f"- Remaining uncertainty: {state['task'].get('remaining_uncertainty') or 'None noted.'}",
            "",
            "## Prompt Stack",
            "",
        ]
    )
    for component in part.get("stack_components", []):
        lines.append(f"- `{component['kind']}` `{component['id']}` -> `{component['path']}`")
    lines.extend(
        [
            "",
            "## Start Here",
            "",
            "Load the prompt stack in order, then execute only this task part against the current task context.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def render_task_part(
    registry: dict[str, Any],
    *,
    root: Path,
    task_id: str,
    part_id: str,
) -> dict[str, Any]:
    state = load_task_state(task_id, root, registry)
    plan = active_plan(state)
    if plan is None:
        fail("task has no recommendation or confirmed plan to render")
    part = next((item for item in plan.get("task_parts", []) if item.get("part_id") == part_id), None)
    if part is None:
        fail(f"task part `{part_id}` is not present in the current plan")
    markdown = render_task_part_markdown(state, part)
    return {
        "task_id": task_id,
        "phase_id": state.get("current_phase_id"),
        "part_id": part_id,
        "part": part,
        "markdown": markdown,
        "task_context": {
            "summary": task_summary_text(state),
            "scope_boundaries": state["task"].get("scope_boundaries"),
            "definition_of_done": state["task"].get("definition_of_done"),
            "verification": state["task"].get("verification"),
            "remaining_uncertainty": state["task"].get("remaining_uncertainty"),
        },
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
    state["reflection"].append(final_record)
    state["layers"]["learned_tendencies"] = summary
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
    return payload
