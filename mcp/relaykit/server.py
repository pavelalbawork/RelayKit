#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
REMOVED_REPO_PATHS: list[str] = []
for candidate in (str(REPO_ROOT),):
    while candidate in sys.path:
        sys.path.remove(candidate)
        REMOVED_REPO_PATHS.append(candidate)

import anyio
import mcp.types as mcp_types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.stdio import stdio_server

ROOT = REPO_ROOT
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import relaykit  # type: ignore
from relaykit_backend import taskflow


SERVER_INFO = {
    "name": "relaykit-mcp",
    "title": "RelayKit MCP Server",
    "version": relaykit.VERSION,
}
LOG_LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}
LOG_LEVEL_NAME = "info"
LOG_FILE_PATH = Path("/tmp/relaykit-mcp.log")
def log_event(message: str, *, level: str = "info") -> None:
    configured = LOG_LEVELS.get(LOG_LEVEL_NAME, 20)
    current = LOG_LEVELS.get(level, 20)
    if current < configured:
        return
    line = f"[{SERVER_INFO['name']}] {level}: {message}"
    print(line, file=sys.stderr, flush=True)
    try:
        with LOG_FILE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except OSError:
        pass


def json_text(payload: Any) -> str:
    return json.dumps(payload, indent=2)


def make_text_result(
    text: str,
    *,
    structured: dict[str, Any] | None = None,
    is_error: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": text,
            }
        ],
        "isError": is_error,
    }
    if structured is not None:
        result["structuredContent"] = structured
    return result


def validate_registry_or_fail() -> dict[str, Any]:
    registry = relaykit.load_registry()
    issues = relaykit.validate_registry(registry)
    if issues:
        raise ValueError(f"RelayKit registry is invalid: {'; '.join(issues)}")
    return registry


def resolve_workspace_and_project(
    registry: dict[str, Any],
    arguments: dict[str, Any],
) -> tuple[Path | None, dict[str, Any] | None, Path | None, dict[str, Any] | None]:
    namespace = type("StackArgs", (), {})()
    namespace.workspace_root = arguments.get("workspace_root")
    namespace.project_root = arguments.get("project_root")
    namespace.workspace_profile = arguments.get("workspace_profile")
    namespace.project_profile = arguments.get("project_profile")
    namespace.start_with_defaults = arguments.get("start_with_defaults", False)
    workspace_path, workspace_profile = relaykit.resolve_workspace_profile_for_stack(namespace, registry)
    project_path, project_profile = relaykit.resolve_project_profile_for_stack(namespace, registry)
    return workspace_path, workspace_profile, project_path, project_profile


def resolve_task_context(
    registry: dict[str, Any],
    arguments: dict[str, Any],
) -> tuple[Path | None, dict[str, Any] | None, Path | None, dict[str, Any] | None, Path]:
    namespace = type("TaskArgs", (), {})()
    namespace.workspace_root = arguments.get("workspace_root", ".")
    namespace.project_root = arguments.get("project_root")
    namespace.workspace_profile = arguments.get("workspace_profile")
    namespace.project_profile = arguments.get("project_profile")
    namespace.task_scope = arguments.get("task_scope")
    workspace_root, workspace_profile, project_root, project_profile, storage_root = relaykit.resolve_task_context(
        namespace,
        registry,
    )
    return workspace_root, workspace_profile, project_root, project_profile, storage_root


def build_doctor_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = relaykit.load_registry()
    registry_issues = relaykit.validate_registry(registry)

    workspace_root = Path(arguments.get("workspace_root", ".")).resolve()
    workspace_candidate = (
        Path(arguments["workspace_profile"]).resolve()
        if arguments.get("workspace_profile")
        else relaykit.workspace_profile_path(workspace_root, registry)
    )
    workspace_path, workspace_profile = relaykit.load_optional_profile(
        workspace_candidate,
        relaykit.PROFILE_KIND_WORKSPACE,
    )
    workspace_issues = (
        ["workspace profile is missing; run RelayKit workspace onboarding"]
        if workspace_profile is None
        else relaykit.validate_profile(
            workspace_profile,
            registry,
            expected_kind=relaykit.PROFILE_KIND_WORKSPACE,
            base_preset=relaykit.registry_defaults(registry)["default_preset"],
            origin="workspace profile",
        )
    )

    project_payload = relaykit.status_payload(None, [], optional=True)
    if arguments.get("project_root") or arguments.get("project_profile"):
        project_root = Path(arguments.get("project_root", ".")).resolve()
        project_candidate = (
            Path(arguments["project_profile"]).resolve()
            if arguments.get("project_profile")
            else relaykit.project_profile_path(project_root, registry)
        )
        project_path, project_profile = relaykit.load_optional_profile(
            project_candidate,
            relaykit.PROFILE_KIND_PROJECT,
        )
        project_issues = (
            []
            if project_profile is None
            else relaykit.validate_profile(
                project_profile,
                registry,
                expected_kind=relaykit.PROFILE_KIND_PROJECT,
                base_preset=relaykit.project_base_preset(
                    registry,
                    workspace_profile=workspace_profile,
                    project_profile=project_profile,
                ),
                origin="project profile",
            )
        )
        project_payload = relaykit.status_payload(project_path, project_issues, optional=True)

    next_actions: list[str] = []
    if workspace_profile is None:
        next_actions.append(
            f"relaykit init-workspace --workspace-root {workspace_root}"
        )
    if arguments.get("project_root") and project_payload["status"] == "missing":
        next_actions.append(
            "relaykit init-project "
            f"--project-root {Path(arguments['project_root']).resolve()} --use-workspace-defaults"
        )
    payload = {
        "product": "RelayKit",
        "registry": {
            "status": "ok" if not registry_issues else "invalid",
            "path": str(relaykit.REGISTRY_PATH),
            "issues": registry_issues,
        },
        "workspace_profile": relaykit.status_payload(workspace_path, workspace_issues, optional=False),
        "project_profile": project_payload,
        "schemas": {
            "workspace_profile": str((relaykit.SCHEMA_ROOT / "workspace-profile.schema.json").resolve()),
            "project_profile": str((relaykit.SCHEMA_ROOT / "project-profile.schema.json").resolve()),
        },
        "persona_layer": relaykit.persona_layer_summary(registry),
        "next_actions": next_actions,
    }
    if arguments.get("host") or arguments.get("current_host"):
        hosts = relaykit.onboarding_hosts(arguments.get("host"), current_host=bool(arguments.get("current_host")))
        payload["host_onboarding"] = {
            "server": relaykit.mcp_server_spec(),
            "hosts": [relaykit.host_onboarding_status(host_name) for host_name in hosts],
        }
    return payload


def tool_doctor(arguments: dict[str, Any]) -> dict[str, Any]:
    payload = build_doctor_payload(arguments)
    return make_text_result(json_text(payload), structured=payload)


def tool_host_status(arguments: dict[str, Any]) -> dict[str, Any]:
    hosts = relaykit.onboarding_hosts(arguments.get("host"), current_host=bool(arguments.get("current_host")))
    hosts_payload = [relaykit.host_onboarding_status(host_name) for host_name in hosts]
    payload = {
        "product": relaykit.PRODUCT_NAME,
        "server": relaykit.mcp_server_spec(),
        "hosts": hosts_payload,
        "actions": relaykit.build_onboarding_actions(hosts_payload),
    }
    return make_text_result(json_text(payload), structured=payload)


def tool_bootstrap_host(arguments: dict[str, Any]) -> dict[str, Any]:
    hosts = relaykit.onboarding_hosts(arguments.get("host"), current_host=bool(arguments.get("current_host")))
    payload = {
        "product": relaykit.PRODUCT_NAME,
        "server": relaykit.mcp_server_spec(),
        "results": [
            relaykit.bootstrap_host(
                host_name,
                install_skills=not bool(arguments.get("skip_skills")),
                configure_mcp=not bool(arguments.get("skip_mcp")),
                force=bool(arguments.get("force")),
                dry_run=bool(arguments.get("dry_run")),
            )
            for host_name in hosts
        ],
    }
    return make_text_result(json_text(payload), structured=payload)


def tool_setup(arguments: dict[str, Any]) -> dict[str, Any]:
    hosts = relaykit.setup_hosts(arguments.get("host"), current_host=bool(arguments.get("current_host")))
    workspace_root = Path(arguments["workspace_root"]).resolve() if arguments.get("workspace_root") else None
    payload = relaykit.build_setup_payload(
        hosts=hosts,
        workspace_root=workspace_root,
        skip_skills=bool(arguments.get("skip_skills")),
        skip_mcp=bool(arguments.get("skip_mcp")),
        skip_smoke=bool(arguments.get("skip_smoke")),
        force=bool(arguments.get("force")),
        dry_run=bool(arguments.get("dry_run")),
    )
    return make_text_result(json_text(payload), structured=payload)


def tool_uninstall_host(arguments: dict[str, Any]) -> dict[str, Any]:
    hosts = relaykit.onboarding_hosts(arguments.get("host"), current_host=bool(arguments.get("current_host")))
    payload = {
        "product": relaykit.PRODUCT_NAME,
        "server": relaykit.mcp_server_spec(),
        "results": [
            relaykit.uninstall_host(
                host_name,
                remove_skills=not bool(arguments.get("skip_skills")),
                remove_mcp=not bool(arguments.get("skip_mcp")),
                dry_run=bool(arguments.get("dry_run")),
            )
            for host_name in hosts
        ],
    }
    return make_text_result(json_text(payload), structured=payload)


def tool_install_self(arguments: dict[str, Any]) -> dict[str, Any]:
    payload = relaykit.build_install_self_payload(
        venv_dir=Path(arguments.get("venv", ".venv")).expanduser().resolve(),
        requested_hosts=arguments.get("host"),
        current_host=bool(arguments.get("current_host")),
        skip_skills=bool(arguments.get("skip_skills")),
        skip_mcp=bool(arguments.get("skip_mcp")),
        force=bool(arguments.get("force")),
    )
    return make_text_result(json_text(payload), structured=payload)


def tool_smoke(arguments: dict[str, Any]) -> dict[str, Any]:
    hosts = relaykit.setup_hosts(arguments.get("host"), current_host=bool(arguments.get("current_host")))
    workspace_root = Path(arguments["workspace_root"]).resolve() if arguments.get("workspace_root") else None
    payload = relaykit.build_smoke_payload(
        hosts=hosts,
        workspace_root=workspace_root,
        force=bool(arguments.get("force")),
    )
    return make_text_result(json_text(payload), structured=payload)


def tool_acknowledge_host(arguments: dict[str, Any]) -> dict[str, Any]:
    hosts = relaykit.onboarding_hosts(arguments.get("host"), current_host=bool(arguments.get("current_host")))
    state = relaykit.load_onboarding_state()
    for host_name in hosts:
        entry = relaykit.host_state(state, host_name)
        entry["dismissed"] = True
    relaykit.save_onboarding_state(state)
    payload = {"product": relaykit.PRODUCT_NAME, "acknowledged_hosts": hosts}
    return make_text_result(json_text(payload), structured=payload)


def tool_list(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = validate_registry_or_fail()
    section = arguments.get("section")
    if section not in {"skills", "skillpacks", "hosts", "models", "presets", "personas", "lanes"}:
        raise ValueError("section must be one of: skills, skillpacks, hosts, models, presets, personas, lanes")
    if section == "lanes":
        preset_name = arguments.get("preset") or relaykit.registry_defaults(registry)["default_preset"]
        if preset_name not in registry["presets"]:
            raise ValueError(f"unknown preset `{preset_name}`")
        payload = {"section": section, section: sorted(registry["presets"][preset_name]["lanes"].keys())}
    elif section == "personas" and arguments.get("detailed"):
        payload = relaykit.build_persona_catalog(registry)
    else:
        payload = {"section": section, section: sorted(registry[section].keys())}
    return make_text_result(json_text(payload), structured=payload)


def tool_preset(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = validate_registry_or_fail()
    preset_name = arguments.get("preset")
    if not preset_name:
        raise ValueError("preset is required")
    presets = registry["presets"]
    if preset_name not in presets:
        raise ValueError(f"unknown preset `{preset_name}`")
    preset = presets[preset_name]
    lane_name = arguments.get("lane")
    if lane_name:
        lane = preset["lanes"].get(lane_name)
        if lane is None:
            raise ValueError(f"preset `{preset_name}` has no lane `{lane_name}`")
        payload = {"product": "RelayKit", "preset": preset_name, "lane": lane_name, "config": lane}
    else:
        payload = {"product": "RelayKit", "preset": preset_name, **preset}
    return make_text_result(json_text(payload), structured=payload)


def resolve_stack_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = validate_registry_or_fail()
    workspace_path, workspace_profile, project_path, project_profile = resolve_workspace_and_project(
        registry,
        arguments,
    )

    if workspace_profile is not None:
        workspace_issues = relaykit.validate_profile(
            workspace_profile,
            registry,
            expected_kind=relaykit.PROFILE_KIND_WORKSPACE,
            base_preset=relaykit.registry_defaults(registry)["default_preset"],
            origin=f"workspace profile `{workspace_path}`",
        )
        if workspace_issues:
            raise ValueError("; ".join(workspace_issues))

    if project_profile is not None:
        project_issues = relaykit.validate_profile(
            project_profile,
            registry,
            expected_kind=relaykit.PROFILE_KIND_PROJECT,
            base_preset=relaykit.project_base_preset(
                registry,
                workspace_profile=workspace_profile,
                project_profile=project_profile,
            ),
            origin=f"project profile `{project_path}`",
        )
        if project_issues:
            raise ValueError("; ".join(project_issues))

    payload = relaykit.build_stack(
        registry,
        lane_name=arguments.get("lane"),
        skill_name=arguments.get("skill"),
        host_name=arguments.get("host"),
        model_name=arguments.get("model"),
        role=arguments.get("role"),
        reasoning_effort=arguments.get("reasoning_effort"),
        packet=arguments.get("packet"),
        repo_guide=arguments.get("repo_guide"),
        preset=arguments.get("preset"),
        workspace_profile=workspace_profile,
        project_profile=project_profile,
        cli_personas=arguments.get("personas") or [],
        extra_persona_paths=arguments.get("persona_paths") or [],
    )
    payload["workspace_profile"] = str(workspace_path) if workspace_path else None
    payload["project_profile"] = str(project_path) if project_path else None
    return payload


def tool_stack(arguments: dict[str, Any]) -> dict[str, Any]:
    payload = resolve_stack_payload(arguments)
    return make_text_result(json_text(payload), structured=payload)


def tool_render_prompt_stack(arguments: dict[str, Any]) -> dict[str, Any]:
    payload = resolve_stack_payload(arguments)
    markdown = relaykit.render_stack_markdown(payload)
    return make_text_result(markdown, structured={"markdown": markdown, "stack": payload})


def build_workspace_profile(
    registry: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    profile = relaykit.default_workspace_profile(registry)
    if arguments.get("preset") is not None:
        profile["preset"] = arguments["preset"]
    if arguments.get("default_personas") is not None:
        profile["default_personas"] = relaykit.ensure_known_personas(
            registry,
            arguments["default_personas"],
            label="workspace default_personas",
        )
    if arguments.get("lane_overrides") is not None:
        profile["lane_overrides"] = arguments["lane_overrides"]
    if arguments.get("notes") is not None:
        profile["notes"] = arguments["notes"]
    return profile


def tool_init_workspace(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = validate_registry_or_fail()
    workspace_root = Path(arguments.get("workspace_root", ".")).resolve()
    path = relaykit.workspace_profile_path(workspace_root, registry)
    relaykit.ensure_profile_write(path, bool(arguments.get("force", False)))
    profile = build_workspace_profile(registry, arguments)
    issues = relaykit.validate_profile(
        profile,
        registry,
        expected_kind=relaykit.PROFILE_KIND_WORKSPACE,
        base_preset=relaykit.registry_defaults(registry)["default_preset"],
        origin="workspace profile",
    )
    if issues:
        raise ValueError("; ".join(issues))
    relaykit.write_json(path, profile)
    payload = {"workspace_profile": str(path), "profile": profile}
    return make_text_result(json_text(payload), structured=payload)


def build_project_profile(
    registry: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    project_root = Path(arguments.get("project_root", ".")).resolve()
    project_name = arguments.get("project_name") or project_root.name
    profile = relaykit.default_project_profile(project_name)
    if arguments.get("inherits_workspace_defaults") is not None:
        profile["inherits_workspace_defaults"] = bool(arguments["inherits_workspace_defaults"])
    if arguments.get("preset") is not None:
        profile["preset"] = arguments["preset"]
    if arguments.get("default_personas") is not None:
        profile["default_personas"] = relaykit.ensure_known_personas(
            registry,
            arguments["default_personas"],
            label="project default_personas",
        )
    if arguments.get("lane_overrides") is not None:
        profile["lane_overrides"] = arguments["lane_overrides"]
    if arguments.get("notes") is not None:
        profile["notes"] = arguments["notes"]
    profile["project_name"] = project_name
    return profile


def tool_init_project(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = validate_registry_or_fail()
    project_root = Path(arguments.get("project_root", ".")).resolve()
    path = relaykit.project_profile_path(project_root, registry)
    relaykit.ensure_profile_write(path, bool(arguments.get("force", False)))
    profile = build_project_profile(registry, arguments)
    issues = relaykit.validate_profile(
        profile,
        registry,
        expected_kind=relaykit.PROFILE_KIND_PROJECT,
        base_preset=relaykit.registry_defaults(registry)["default_preset"],
        origin="project profile",
    )
    if issues:
        raise ValueError("; ".join(issues))
    relaykit.write_json(path, profile)
    payload = {"project_profile": str(path), "profile": profile}
    return make_text_result(json_text(payload), structured=payload)


def tool_init_persona(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = validate_registry_or_fail()
    args = argparse.Namespace(
        id=arguments.get("id"),
        name=arguments.get("name"),
        description=arguments.get("description"),
        summary=arguments.get("summary"),
        kind=arguments.get("kind"),
        role=arguments.get("role"),
        host=arguments.get("host"),
        token_cost=arguments.get("token_cost", "low"),
        tier=arguments.get("tier", "optional"),
        source=arguments.get("source", "local"),
        conflicts_with=arguments.get("conflicts_with"),
        principle=arguments.get("principle"),
        load_order=arguments.get("load_order"),
        dest=arguments.get("dest"),
        dry_run=bool(arguments.get("dry_run", False)),
        force=bool(arguments.get("force", False)),
    )
    payload = relaykit.build_persona_init_payload(registry, args)
    if not args.dry_run:
        relaykit.write_persona_init_payload(registry, payload)
    return make_text_result(json_text(payload), structured=payload)


def tool_start_task(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = validate_registry_or_fail()
    workspace_root, workspace_profile, project_root, project_profile, _storage_root = resolve_task_context(
        registry,
        arguments,
    )
    payload = taskflow.start_task(
        registry,
        workspace_root=workspace_root,
        project_root=project_root,
        workspace_profile=workspace_profile,
        project_profile=project_profile,
        task_text=arguments.get("task", ""),
        task_scope=arguments.get("task_scope"),
        allowed_hosts=arguments.get("allowed_hosts"),
        skip_clarification=bool(arguments.get("skip_clarification", False)),
    )
    return make_text_result(json_text(payload), structured=payload)


def tool_answer_task(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = validate_registry_or_fail()
    _workspace_root, workspace_profile, _project_root, project_profile, storage_root = resolve_task_context(
        registry,
        arguments,
    )
    task_id = arguments.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")
    if arguments.get("skip_clarification"):
        state = taskflow.load_task_state(task_id, storage_root, registry)
        state["clarification"]["skipped"] = True
        payload = taskflow.maybe_recommend(state, registry, workspace_profile, project_profile)
        state_file, summary_file = taskflow.save_task_state(state, registry)
        payload["state_path"] = str(state_file)
        payload["summary_path"] = str(summary_file)
        return make_text_result(json_text(payload), structured=payload)
    answer = arguments.get("answer")
    if not answer:
        raise ValueError("answer is required unless skip_clarification=true")
    payload = taskflow.answer_task(
        registry,
        root=storage_root,
        task_id=task_id,
        answer=answer,
        question_id=arguments.get("question_id"),
        workspace_profile=workspace_profile,
        project_profile=project_profile,
    )
    return make_text_result(json_text(payload), structured=payload)


def tool_show_task(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = validate_registry_or_fail()
    _workspace_root, _workspace_profile, _project_root, _project_profile, storage_root = resolve_task_context(
        registry,
        arguments,
    )
    task_id = arguments.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")
    if arguments.get("debug"):
        payload = taskflow.inspect_task(registry, root=storage_root, task_id=task_id)
    else:
        payload = taskflow.show_task(registry, root=storage_root, task_id=task_id)
    return make_text_result(json_text(payload), structured=payload)


def tool_confirm_task(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = validate_registry_or_fail()
    _workspace_root, workspace_profile, _project_root, project_profile, storage_root = resolve_task_context(
        registry,
        arguments,
    )
    task_id = arguments.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")
    payload = taskflow.confirm_task(
        registry,
        root=storage_root,
        task_id=task_id,
        accept=bool(arguments.get("accept", False)),
        change_text=arguments.get("change"),
        workspace_profile=workspace_profile,
        project_profile=project_profile,
    )
    return make_text_result(json_text(payload), structured=payload)


def tool_checkpoint_task(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = validate_registry_or_fail()
    _workspace_root, _workspace_profile, _project_root, _project_profile, storage_root = resolve_task_context(
        registry,
        arguments,
    )
    task_id = arguments.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")
    payload = taskflow.checkpoint_task(
        registry,
        root=storage_root,
        task_id=task_id,
        outcome=arguments.get("outcome"),
        notes=arguments.get("notes") or "",
    )
    return make_text_result(json_text(payload), structured=payload)


def tool_advance_task(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = validate_registry_or_fail()
    _workspace_root, workspace_profile, _project_root, project_profile, storage_root = resolve_task_context(
        registry,
        arguments,
    )
    task_id = arguments.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")
    payload = taskflow.advance_task(
        registry,
        root=storage_root,
        task_id=task_id,
        action=arguments.get("action"),
        change_reason=arguments.get("change_reason"),
        notes=arguments.get("notes"),
        change_text=arguments.get("change"),
        workspace_profile=workspace_profile,
        project_profile=project_profile,
    )
    return make_text_result(json_text(payload), structured=payload)


def tool_resume_task(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = validate_registry_or_fail()
    _workspace_root, _workspace_profile, _project_root, _project_profile, storage_root = resolve_task_context(
        registry,
        arguments,
    )
    task_id = arguments.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")
    payload = taskflow.resume_task(
        registry,
        root=storage_root,
        task_id=task_id,
    )
    return make_text_result(json_text(payload), structured=payload)


def tool_render_task_part(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = validate_registry_or_fail()
    _workspace_root, _workspace_profile, _project_root, _project_profile, storage_root = resolve_task_context(
        registry,
        arguments,
    )
    task_id = arguments.get("task_id")
    part_id = arguments.get("part_id")
    if not task_id:
        raise ValueError("task_id is required")
    if not part_id:
        raise ValueError("part_id is required")
    payload = taskflow.render_task_part(
        registry,
        root=storage_root,
        task_id=task_id,
        part_id=part_id,
    )
    return make_text_result(payload["markdown"], structured=payload)


def tool_reflect_task(arguments: dict[str, Any]) -> dict[str, Any]:
    registry = validate_registry_or_fail()
    _workspace_root, _workspace_profile, _project_root, _project_profile, storage_root = resolve_task_context(
        registry,
        arguments,
    )
    task_id = arguments.get("task_id")
    if not task_id:
        raise ValueError("task_id is required")
    payload = taskflow.reflect_task(
        registry,
        root=storage_root,
        task_id=task_id,
        split_worth_it=arguments.get("split_worth_it"),
        tool_fit=arguments.get("tool_fit"),
        simpler_better=arguments.get("simpler_better"),
        notes=arguments.get("notes"),
        apply=bool(arguments.get("apply", False)),
    )
    return make_text_result(json_text(payload), structured=payload)


TOOLS: dict[str, dict[str, Any]] = {
    "relaykit_doctor": {
        "description": "Safe first RelayKit MCP call. Validate runtime state and inspect workspace or project profiles. If the workspace profile is missing, this tool still succeeds and reports the missing status plus next_actions instead of failing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_root": {"type": "string"},
                "project_root": {"type": "string"},
                "workspace_profile": {"type": "string"},
                "project_profile": {"type": "string"},
                "local_wrapper_root": {"type": "string"},
                "external_control_plane": {"type": "string"},
                "host": {"type": "array", "items": {"type": "string"}},
                "current_host": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "handler": tool_doctor,
    },
    "relaykit_host_status": {
        "description": "Report whether one or more harnesses are ready for RelayKit and return recommended onboarding actions before any task flow starts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "array", "items": {"type": "string"}},
                "current_host": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "handler": tool_host_status,
    },
    "relaykit_bootstrap_host": {
        "description": "Install RelayKit skills and auto-configurable wiring for one or more supported harnesses. Prefer this over manual config edits when MCP is available.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "array", "items": {"type": "string"}},
                "current_host": {"type": "boolean"},
                "skip_skills": {"type": "boolean"},
                "skip_mcp": {"type": "boolean"},
                "dry_run": {"type": "boolean"},
                "force": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "handler": tool_bootstrap_host,
    },
    "relaykit_setup": {
        "description": "Run the first-use RelayKit setup flow: wire the harness, optionally run the local smoke test, and return the exact next prompt to paste into the host.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "array", "items": {"type": "string"}},
                "current_host": {"type": "boolean"},
                "workspace_root": {"type": "string"},
                "skip_skills": {"type": "boolean"},
                "skip_mcp": {"type": "boolean"},
                "skip_smoke": {"type": "boolean"},
                "dry_run": {"type": "boolean"},
                "force": {"type": "boolean"}
            },
            "additionalProperties": False,
        },
        "handler": tool_setup,
    },
    "relaykit_uninstall_host": {
        "description": "Remove RelayKit skills and auto-configurable wiring for one or more supported harnesses.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "array", "items": {"type": "string"}},
                "current_host": {"type": "boolean"},
                "skip_skills": {"type": "boolean"},
                "skip_mcp": {"type": "boolean"},
                "dry_run": {"type": "boolean"}
            },
            "additionalProperties": False,
        },
        "handler": tool_uninstall_host,
    },
    "relaykit_acknowledge_host": {
        "description": "Record that harness onboarding was offered and explicitly deferred for one or more harnesses.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "array", "items": {"type": "string"}},
                "current_host": {"type": "boolean"}
            },
            "additionalProperties": False,
        },
        "handler": tool_acknowledge_host,
    },
    "relaykit_install_self": {
        "description": "Create a local venv, install RelayKit into it, and optionally wire supported harnesses.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "venv": {"type": "string"},
                "host": {"type": "array", "items": {"type": "string"}},
                "current_host": {"type": "boolean"},
                "skip_skills": {"type": "boolean"},
                "skip_mcp": {"type": "boolean"},
                "force": {"type": "boolean"}
            },
            "additionalProperties": False,
        },
        "handler": tool_install_self,
    },
    "relaykit_smoke": {
        "description": "Run the reusable RelayKit lifecycle smoke flow and return the next host prompt without shelling out to the CLI.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "host": {"type": "array", "items": {"type": "string"}},
                "current_host": {"type": "boolean"},
                "workspace_root": {"type": "string"},
                "force": {"type": "boolean"}
            },
            "additionalProperties": False,
        },
        "handler": tool_smoke,
    },
    "relaykit_list": {
        "description": "List registered skills, hosts, models, presets, personas, or preset lanes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": ["skills", "skillpacks", "hosts", "models", "presets", "personas", "lanes"],
                },
                "preset": {"type": "string"},
                "detailed": {"type": "boolean"},
            },
            "required": ["section"],
            "additionalProperties": False,
        },
        "handler": tool_list,
    },
    "relaykit_preset": {
        "description": "Show one RelayKit preset or one lane inside a preset.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "preset": {"type": "string"},
                "lane": {"type": "string"},
            },
            "required": ["preset"],
            "additionalProperties": False,
        },
        "handler": tool_preset,
    },
    "relaykit_stack": {
        "description": "Resolve the effective RelayKit lane stack as structured data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lane": {"type": "string"},
                "skill": {"type": "string"},
                "host": {"type": "string"},
                "model": {"type": "string"},
                "role": {"type": "string"},
                "reasoning_effort": {"type": "string"},
                "preset": {"type": "string"},
                "personas": {"type": "array", "items": {"type": "string"}},
                "persona_paths": {"type": "array", "items": {"type": "string"}},
                "packet": {"type": "string"},
                "repo_guide": {"type": "string"},
                "workspace_root": {"type": "string"},
                "project_root": {"type": "string"},
                "workspace_profile": {"type": "string"},
                "project_profile": {"type": "string"},
                "start_with_defaults": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "handler": tool_stack,
    },
    "relaykit_render_prompt_stack": {
        "description": "Render the effective RelayKit lane stack as Markdown for direct prompt loading.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lane": {"type": "string"},
                "skill": {"type": "string"},
                "host": {"type": "string"},
                "model": {"type": "string"},
                "role": {"type": "string"},
                "reasoning_effort": {"type": "string"},
                "preset": {"type": "string"},
                "personas": {"type": "array", "items": {"type": "string"}},
                "persona_paths": {"type": "array", "items": {"type": "string"}},
                "packet": {"type": "string"},
                "repo_guide": {"type": "string"},
                "workspace_root": {"type": "string"},
                "project_root": {"type": "string"},
                "workspace_profile": {"type": "string"},
                "project_profile": {"type": "string"},
                "start_with_defaults": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "handler": tool_render_prompt_stack,
    },
    "relaykit_init_workspace": {
        "description": "Write a RelayKit workspace profile with defaults or explicit overrides. Use this after relaykit_doctor when workspace_profile.status is missing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_root": {"type": "string"},
                "start_with_defaults": {"type": "boolean"},
                "force": {"type": "boolean"},
                "preset": {"type": "string"},
                "default_personas": {"type": "array", "items": {"type": "string"}},
                "lane_overrides": {"type": "object"},
                "notes": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "handler": tool_init_workspace,
    },
    "relaykit_init_project": {
        "description": "Write a RelayKit project profile with explicit overrides or workspace-default inheritance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_root": {"type": "string"},
                "force": {"type": "boolean"},
                "project_name": {"type": "string"},
                "inherits_workspace_defaults": {"type": "boolean"},
                "preset": {"type": ["string", "null"]},
                "default_personas": {"type": "array", "items": {"type": "string"}},
                "lane_overrides": {"type": "object"},
                "notes": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "handler": tool_init_project,
    },
    "relaykit_init_persona": {
        "description": "Scaffold and optionally register a new repo-backed persona add-in.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "summary": {"type": "string"},
                "kind": {"type": "string", "enum": sorted(relaykit.PERSONA_KINDS)},
                "role": {"type": "array", "items": {"type": "string"}},
                "host": {"type": "array", "items": {"type": "string"}},
                "token_cost": {"type": "string", "enum": sorted(relaykit.PERSONA_TOKEN_COSTS)},
                "tier": {"type": "string", "enum": sorted(relaykit.PERSONA_TIERS)},
                "source": {"type": "string"},
                "conflicts_with": {"type": "array", "items": {"type": "string"}},
                "principle": {"type": "array", "items": {"type": "string"}},
                "load_order": {"type": "integer"},
                "dest": {"type": "string"},
                "dry_run": {"type": "boolean"},
                "force": {"type": "boolean"}
            },
            "required": ["name", "description", "kind", "role"],
            "additionalProperties": False,
        },
        "handler": tool_init_persona,
    },
    "relaykit_start_task": {
        "description": "Start a RelayKit intake flow for a task and return the next clarification question or recommendation. Prefer this MCP tool over shelling out to the relaykit CLI when available.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_root": {"type": "string"},
                "project_root": {"type": "string"},
                "workspace_profile": {"type": "string"},
                "project_profile": {"type": "string"},
                "task_scope": {"type": "string", "enum": ["workspace", "project"]},
                "task": {"type": "string"},
                "allowed_hosts": {"type": "array", "items": {"type": "string"}},
                "skip_clarification": {"type": "boolean"}
            },
            "required": ["task"],
            "additionalProperties": False
        },
        "handler": tool_start_task,
    },
    "relaykit_answer_task": {
        "description": "Answer the current clarification question for a RelayKit task or skip remaining clarification to get a recommendation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_root": {"type": "string"},
                "project_root": {"type": "string"},
                "workspace_profile": {"type": "string"},
                "project_profile": {"type": "string"},
                "task_scope": {"type": "string", "enum": ["workspace", "project"]},
                "task_id": {"type": "string"},
                "question_id": {"type": "string"},
                "answer": {"type": "string"},
                "skip_clarification": {"type": "boolean"}
            },
            "required": ["task_id"],
            "additionalProperties": False
        },
        "handler": tool_answer_task,
    },
    "relaykit_show_task": {
        "description": "Show the current state of a RelayKit task and lane-planning instance, with optional debug reasoning layers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_root": {"type": "string"},
                "project_root": {"type": "string"},
                "workspace_profile": {"type": "string"},
                "project_profile": {"type": "string"},
                "task_scope": {"type": "string", "enum": ["workspace", "project"]},
                "task_id": {"type": "string"},
                "debug": {"type": "boolean"}
            },
            "required": ["task_id"],
            "additionalProperties": False
        },
        "handler": tool_show_task,
    },
    "relaykit_confirm_task": {
        "description": "Accept a RelayKit lane recommendation or request setup changes after clarification is complete.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_root": {"type": "string"},
                "project_root": {"type": "string"},
                "workspace_profile": {"type": "string"},
                "project_profile": {"type": "string"},
                "task_scope": {"type": "string", "enum": ["workspace", "project"]},
                "task_id": {"type": "string"},
                "accept": {"type": "boolean"},
                "change": {"type": "string"}
            },
            "required": ["task_id"],
            "additionalProperties": False
        },
        "handler": tool_confirm_task,
    },
    "relaykit_checkpoint_task": {
        "description": "Record a checkpoint and get continuation guidance for a RelayKit task after work begins.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_root": {"type": "string"},
                "project_root": {"type": "string"},
                "workspace_profile": {"type": "string"},
                "project_profile": {"type": "string"},
                "task_scope": {"type": "string", "enum": ["workspace", "project"]},
                "task_id": {"type": "string"},
                "outcome": {"type": "string", "enum": sorted(taskflow.CHECKPOINT_OUTCOMES)},
                "notes": {"type": "string"}
            },
            "required": ["task_id"],
            "additionalProperties": False
        },
        "handler": tool_checkpoint_task,
    },
    "relaykit_advance_task": {
        "description": "Apply the latest checkpoint action or an explicit setup change and start the next task phase.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_root": {"type": "string"},
                "project_root": {"type": "string"},
                "workspace_profile": {"type": "string"},
                "project_profile": {"type": "string"},
                "task_scope": {"type": "string", "enum": ["workspace", "project"]},
                "task_id": {"type": "string"},
                "action": {"type": "string", "enum": sorted(taskflow.CHECKPOINT_ACTIONS)},
                "change_reason": {"type": "string", "enum": sorted(taskflow.CHANGE_REASONS)},
                "notes": {"type": "string"},
                "change": {"type": "string"}
            },
            "required": ["task_id"],
            "additionalProperties": False
        },
        "handler": tool_advance_task,
    },
    "relaykit_resume_task": {
        "description": "Resume a RelayKit task and get summary plus targeted resume questions when needed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_root": {"type": "string"},
                "project_root": {"type": "string"},
                "workspace_profile": {"type": "string"},
                "project_profile": {"type": "string"},
                "task_scope": {"type": "string", "enum": ["workspace", "project"]},
                "task_id": {"type": "string"}
            },
            "required": ["task_id"],
            "additionalProperties": False
        },
        "handler": tool_resume_task,
    },
    "relaykit_render_task_part": {
        "description": "Render the current launch bundle for one task part, including its prompt stack and execution brief.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_root": {"type": "string"},
                "project_root": {"type": "string"},
                "workspace_profile": {"type": "string"},
                "project_profile": {"type": "string"},
                "task_scope": {"type": "string", "enum": ["workspace", "project"]},
                "task_id": {"type": "string"},
                "part_id": {"type": "string"}
            },
            "required": ["task_id", "part_id"],
            "additionalProperties": False
        },
        "handler": tool_render_task_part,
    },
    "relaykit_reflect_task": {
        "description": "Record a post-task reflection so RelayKit can learn from overhead and tool fit after the task is done.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_root": {"type": "string"},
                "project_root": {"type": "string"},
                "workspace_profile": {"type": "string"},
                "project_profile": {"type": "string"},
                "task_scope": {"type": "string", "enum": ["workspace", "project"]},
                "task_id": {"type": "string"},
                "split_worth_it": {"type": "string", "enum": sorted(taskflow.REFLECTION_VALUES)},
                "tool_fit": {"type": "string", "enum": sorted(taskflow.TOOL_FIT_VALUES)},
                "simpler_better": {"type": "string", "enum": sorted(taskflow.REFLECTION_VALUES)},
                "notes": {"type": "string"},
                "apply": {"type": "boolean"}
            },
            "required": ["task_id"],
            "additionalProperties": False
        },
        "handler": tool_reflect_task,
    },
}


def build_tool_definitions() -> list[mcp_types.Tool]:
    return [
        mcp_types.Tool(
            name=name,
            title="RelayKit " + " ".join(part.capitalize() for part in name.split("_")[1:]),
            description=meta["description"],
            inputSchema=meta["inputSchema"],
        )
        for name, meta in TOOLS.items()
    ]


def to_call_tool_result(result: dict[str, Any]) -> mcp_types.CallToolResult:
    content_blocks: list[mcp_types.ContentBlock] = []
    for item in result.get("content", []):
        if item.get("type") == "text":
            content_blocks.append(mcp_types.TextContent(type="text", text=item.get("text", "")))
    return mcp_types.CallToolResult(
        content=content_blocks,
        structuredContent=result.get("structuredContent"),
        isError=bool(result.get("isError", False)),
    )


SDK_SERVER = Server(
    name=SERVER_INFO["name"],
    version=SERVER_INFO["version"],
    instructions=(
        "RelayKit harness augmentation tools for multi-tool, human-in-the-loop parallel execution."
    ),
)


@SDK_SERVER.list_tools()
async def handle_list_tools() -> list[mcp_types.Tool]:
    log_event("tools/list request", level="info")
    tools = build_tool_definitions()
    log_event(f"tools/list response count={len(tools)}", level="info")
    return tools


@SDK_SERVER.call_tool(validate_input=True)
async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> mcp_types.CallToolResult:
    tool_name = name
    tool_arguments = arguments or {}
    log_event(f"tools/call request tool={tool_name!r}", level="info")
    if tool_name not in TOOLS:
        return to_call_tool_result(
            make_text_result(
                json_text({"error": f"unknown tool `{tool_name}`"}),
                structured={"error": f"unknown tool `{tool_name}`"},
                is_error=True,
            )
        )
    try:
        result = TOOLS[tool_name]["handler"](tool_arguments)
    except Exception as exc:
        log_event(f"tools/call error tool={tool_name!r} error={exc}", level="error")
        result = make_text_result(
            json_text({"error": str(exc)}),
            structured={"error": str(exc)},
            is_error=True,
        )
    log_event(f"tools/call response tool={tool_name!r}", level="info")
    return to_call_tool_result(result)


async def run_stdio_server() -> None:
    init_options = SDK_SERVER.create_initialization_options(
        notification_options=NotificationOptions(),
        experimental_capabilities={},
    )
    log_event(
        f"server starting root={ROOT} cwd={Path.cwd()} argv={sys.argv[1:]}",
        level="info",
    )
    async with stdio_server() as (read_stream, write_stream):
        await SDK_SERVER.run(
            read_stream,
            write_stream,
            init_options,
        )


def main() -> int:
    argv = sys.argv[1:]
    passthrough_argv = [arg for arg in argv if arg != "-"]
    if any(arg in {"-h", "--help", "help"} for arg in passthrough_argv):
        print(f"{SERVER_INFO['title']} ({SERVER_INFO['name']})")
        print("Usage: relaykit-mcp")
        print("Runs a long-lived MCP server over stdio.")
        print("Use this as an MCP command, not as an interactive shell command.")
        print("Flags:")
        print("  --help     Show this message and exit.")
        print("  --version  Show the server version and exit.")
        print("  -          Accepted as a no-op stdio marker for MCP clients.")
        return 0
    if "--version" in passthrough_argv:
        print(f"{SERVER_INFO['name']} {SERVER_INFO['version']}")
        return 0
    if passthrough_argv:
        print(
            f"{SERVER_INFO['name']}: unexpected arguments: {' '.join(passthrough_argv)}",
            file=sys.stderr,
        )
        print("Run with --help for usage.", file=sys.stderr)
        return 2
    try:
        anyio.run(run_stdio_server)
    except KeyboardInterrupt:
        log_event("server interrupted; exiting", level="info")
        return 0
    except Exception as exc:
        log_event(f"server failure error={exc}", level="error")
        raise
    log_event("stdio closed; server exiting", level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
