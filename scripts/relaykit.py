#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from copy import deepcopy
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from relaykit_backend import taskflow
from relaykit_runtime.layout import runtime_root

REPO_ROOT = runtime_root()
REGISTRY_PATH = REPO_ROOT / "config" / "registry.json"
SCHEMA_ROOT = REPO_ROOT / "config" / "schemas"
VERSION = "0.3.0"

PROFILE_KIND_WORKSPACE = "workspace-profile"
PROFILE_KIND_PROJECT = "project-profile"

ALLOWED_LANE_OVERRIDE_KEYS = {
    "skill",
    "role",
    "host",
    "model",
    "reasoning_effort",
    "capabilities",
    "credit_pool",
    "personas",
}
PERSONA_TIERS = {"recommended", "optional"}
PERSONA_ACTIVATIONS = {"optional-addon"}
PERSONA_KINDS = {"style", "expertise", "hybrid"}
PERSONA_TOKEN_COSTS = {"low", "medium", "high"}
SUPPORTED_ONBOARDING_HOSTS = ("codex", "claude-code", "gemini-cli", "antigravity")
HOST_SKILL_HOMES = {
    "codex": Path("~/.codex/skills"),
    "claude-code": Path("~/.claude/skills"),
    "gemini-cli": Path("~/.gemini/skills"),
}
HOST_MCP_TARGETS = {
    "codex": {"kind": "toml", "path": Path("~/.codex/config.toml")},
    "claude-code": {"kind": "claude-cli", "path": Path("~/.claude/settings.json")},
    "gemini-cli": {"kind": "json", "path": Path("~/.gemini/settings.json")},
    "antigravity": {"kind": "json", "path": Path("~/.gemini/antigravity/mcp_config.json")},
}
PRODUCT_NAME = "RelayKit"
MCP_SERVER_NAME = "relaykit"
MCP_SERVER_PATH = (REPO_ROOT / "mcp" / "relaykit" / "server.py").resolve()
MCP_SERVER_ENTRYPOINT = "relaykit-mcp"
MCP_SERVER_COMMAND = sys.executable
SKILLS_ROOT = REPO_ROOT / "skills"
ONBOARDING_STATE_PATH = Path("~/.relaykit/relaykit-onboarding-state.json")
SUPPORTED_MCP_AUTO_HOSTS = tuple(HOST_MCP_TARGETS.keys())
SUPPORTED_SKILL_AUTO_HOSTS = tuple(HOST_SKILL_HOMES.keys())
SMOKE_TASK_TEXT = "Make a tiny login validation tweak and verify it"
SMOKE_FIRST_ANSWER = "In scope: login validation only. Out of scope: backend and styling."
EXECUTION_CONTEXT_FILENAME = "execution-context.json"


def fail(message: str, *, details: list[str] | None = None) -> None:
    payload: dict[str, object] = {"error": message}
    if details:
        payload["details"] = details
    print(json.dumps(payload, indent=2))
    raise SystemExit(1)


def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        fail(f"missing registry: {REGISTRY_PATH}")
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def resolve_relative(path: str) -> str:
    if not path:
        raise ValueError("registry-relative path must not be empty")
    return str((REPO_ROOT / path).resolve())


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def execution_context_path(root: Path, registry: dict) -> Path:
    return root / registry["defaults"]["profile_dirname"] / EXECUTION_CONTEXT_FILENAME


def validated_command(
    command: str,
    *,
    source: str,
    description: str,
) -> dict[str, str]:
    return {
        "command": command,
        "source": source,
        "description": description,
        "validated_at": taskflow.now_iso(),
    }


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _normalize_path_token(token: str, *, root: Path) -> str:
    candidate = Path(token)
    if not candidate.is_absolute():
        candidate = root / candidate
    return str(candidate.resolve())


def _extract_verification_targets(text: str) -> list[str]:
    commands: list[str] = []
    seen: set[str] = set()
    patterns = (
        r"verification(?:\s+target)?\s*:\s*`([^`]+)`",
        r"verification(?:\s+target)?\s*:\s*\"([^\"]+)\"",
        r"verification(?:\s+target)?\s*:\s*'([^']+)'",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            command = match.group(1).strip()
            if command and command not in seen:
                seen.add(command)
                commands.append(command)
    return commands


def _project_guidance_files(*, workspace_root: Path | None, project_root: Path | None) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()
    for root in (project_root, workspace_root):
        if root is None:
            continue
        for name in ("AGENTS.md", "README.md"):
            candidate = root / name
            if candidate.exists() and candidate not in seen:
                seen.add(candidate)
                files.append(candidate)
    return files


def _run_probe_command(command: list[str], *, cwd: Path) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return False, str(error)
    if completed.returncode == 0:
        return True, ""
    summary = _first_nonempty_line(completed.stderr) or _first_nonempty_line(completed.stdout) or f"exit code {completed.returncode}"
    return False, summary


def _validate_command_targets(tokens: list[str], *, cwd: Path) -> tuple[bool, str]:
    path_like_tokens = [
        token
        for token in tokens
        if token
        and not token.startswith("-")
        and ("/" in token or token.startswith(".") or token.endswith((".py", ".js", ".ts")))
    ]
    for token in path_like_tokens:
        candidate = Path(token)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        if not candidate.exists():
            return False, f"missing target `{token}`"
    return True, ""


def _validate_explicit_verification_command(
    command: str,
    *,
    project_root: Path,
) -> tuple[dict[str, str] | None, list[str], bool]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None, [f"Could not parse project verification target `{command}`."], False
    if not tokens:
        return None, [], False

    def success(description: str, note: str | None = None) -> tuple[dict[str, str], list[str], bool]:
        notes = [note] if note else []
        return (
            validated_command(
                command,
                source="verification-target",
                description=description,
            ),
            notes,
            True,
        )

    if len(tokens) >= 3 and tokens[1] == "-m" and tokens[2] == "pytest":
        targets_ok, target_note = _validate_command_targets(tokens[3:], cwd=project_root)
        if not targets_ok:
            return None, [f"Project verification target `{command}` is not runnable here: {target_note}."], True
        available, detail = _run_probe_command([tokens[0], "-m", "pytest", "--version"], cwd=project_root)
        if available:
            return success("Validated project verification target", "Project verification target is available locally and ready to run.")
        return None, [f"Project verification target `{command}` is not runnable here: {detail}."], True

    if tokens[0] == "pytest":
        targets_ok, target_note = _validate_command_targets(tokens[1:], cwd=project_root)
        if not targets_ok:
            return None, [f"Project verification target `{command}` is not runnable here: {target_note}."], True
        available, detail = _run_probe_command(["pytest", "--version"], cwd=project_root)
        if available:
            return success("Validated project verification target", "Project verification target is available locally and ready to run.")
        return None, [f"Project verification target `{command}` is not runnable here: {detail}."], True

    if len(tokens) >= 3 and tokens[1] == "-m" and tokens[2] == "unittest":
        start_dir = None
        for index, token in enumerate(tokens[3:], start=3):
            if token == "-s" and index + 1 < len(tokens):
                start_dir = tokens[index + 1]
                break
        if start_dir:
            target_path = Path(start_dir)
            if not target_path.is_absolute():
                target_path = project_root / target_path
            if not target_path.exists():
                return None, [f"Project verification target `{command}` is not runnable here: missing target `{start_dir}`."], True
        available, detail = _run_probe_command([tokens[0], "-m", "unittest", "-h"], cwd=project_root)
        if available:
            return success("Validated project verification target", "Project verification target is available locally and ready to run.")
        return None, [f"Project verification target `{command}` is not runnable here: {detail}."], True

    if tokens[:2] == ["npm", "test"]:
        package_json = project_root / "package.json"
        if not package_json.exists():
            return None, [f"Project verification target `{command}` is not runnable here: missing package.json."], True
        available, detail = _run_probe_command(["npm", "--version"], cwd=project_root)
        if available:
            return success("Validated project verification target", "Project verification target is available locally and ready to run.")
        return None, [f"Project verification target `{command}` is not runnable here: {detail}."], True

    if len(tokens) >= 3 and tokens[:2] == ["npm", "run"]:
        package_json = project_root / "package.json"
        if not package_json.exists():
            return None, [f"Project verification target `{command}` is not runnable here: missing package.json."], True
        available, detail = _run_probe_command(["npm", "--version"], cwd=project_root)
        if available:
            return success("Validated project verification target", "Project verification target is available locally and ready to run.")
        return None, [f"Project verification target `{command}` is not runnable here: {detail}."], True

    if tokens[:2] == ["cargo", "test"]:
        if not (project_root / "Cargo.toml").exists():
            return None, [f"Project verification target `{command}` is not runnable here: missing Cargo.toml."], True
        available, detail = _run_probe_command(["cargo", "--version"], cwd=project_root)
        if available:
            return success("Validated project verification target", "Project verification target is available locally and ready to run.")
        return None, [f"Project verification target `{command}` is not runnable here: {detail}."], True

    if tokens[:2] == ["go", "test"]:
        if not ((project_root / "go.mod").exists() or (project_root / "go.work").exists()):
            return None, [f"Project verification target `{command}` is not runnable here: missing go.mod/go.work."], True
        available, detail = _run_probe_command(["go", "version"], cwd=project_root)
        if available:
            return success("Validated project verification target", "Project verification target is available locally and ready to run.")
        return None, [f"Project verification target `{command}` is not runnable here: {detail}."], True

    return None, [], False


def _discover_unittest_fallback(
    *,
    project_root: Path,
    preferred_python: str = "python3",
) -> tuple[dict[str, str] | None, list[str]]:
    for start_dir in ("tests", "src"):
        root = project_root / start_dir
        if not root.exists():
            continue
        test_files = sorted(root.rglob("test_*.py"))
        if not test_files:
            continue
        if not any(
            "import unittest" in file.read_text(encoding="utf-8", errors="ignore")
            or "unittest.TestCase" in file.read_text(encoding="utf-8", errors="ignore")
            for file in test_files[:10]
        ):
            continue
        available, detail = _run_probe_command([preferred_python, "-m", "unittest", "-h"], cwd=project_root)
        if available:
            command = f"{preferred_python} -m unittest discover -s {start_dir} -v"
            return (
                validated_command(
                    command,
                    source="verification-fallback",
                    description="Validated fallback verification command",
                ),
                [f"Fell back to `{command}` because the declared project verification target is not runnable here."],
            )
        return None, [f"Could not validate fallback unittest command: {detail}."]
    return None, []


def discover_execution_context(
    *,
    workspace_root: Path | None,
    project_root: Path | None,
) -> dict[str, object] | None:
    notes: list[str] = []
    validated_commands: list[dict[str, str]] = []
    if project_root is None:
        return None

    preferred_python = "python3"
    found_candidates = False
    explicit_unavailable = False
    for guidance_path in _project_guidance_files(workspace_root=workspace_root, project_root=project_root):
        text = guidance_path.read_text(encoding="utf-8", errors="ignore")
        for command in _extract_verification_targets(text):
            found_candidates = True
            command_payload, command_notes, handled = _validate_explicit_verification_command(
                command,
                project_root=project_root,
            )
            if command_payload is not None:
                validated_commands.append(command_payload)
            for note in command_notes:
                if note not in notes:
                    notes.append(note)
            if handled and len(command.split()) >= 1:
                try:
                    tokens = shlex.split(command)
                    if len(tokens) >= 1 and tokens[0].startswith("python"):
                        preferred_python = tokens[0]
                except ValueError:
                    pass
            if command_payload is not None:
                return _normalize_execution_context(
                    {
                        "validated_commands": validated_commands,
                        "notes": notes,
                    }
                )
            if handled:
                explicit_unavailable = True

    if explicit_unavailable:
        fallback_payload, fallback_notes = _discover_unittest_fallback(
            project_root=project_root,
            preferred_python=preferred_python,
        )
        if fallback_payload is not None:
            validated_commands.append(fallback_payload)
        for note in fallback_notes:
            if note not in notes:
                notes.append(note)

    if not validated_commands and not notes and not found_candidates:
        return None
    return _normalize_execution_context(
        {
            "validated_commands": validated_commands,
            "notes": notes,
        }
    )


def _normalize_execution_context(payload: dict | None) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    commands_raw = payload.get("validated_commands") or []
    notes_raw = payload.get("notes") or payload.get("runtime_notes") or []
    validated_commands: list[dict[str, str]] = []
    seen_commands: set[str] = set()
    for item in commands_raw:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command") or "").strip()
        if not command or command in seen_commands:
            continue
        seen_commands.add(command)
        normalized = {"command": command}
        for key in ("source", "description", "validated_at"):
            value = str(item.get(key) or "").strip()
            if value:
                normalized[key] = value
        validated_commands.append(normalized)
    notes: list[str] = []
    for item in notes_raw:
        note = str(item).strip()
        if note and note not in notes:
            notes.append(note)
    if not validated_commands and not notes:
        return None
    return {
        "validated_commands": validated_commands,
        "notes": notes,
        "updated_at": str(payload.get("updated_at") or taskflow.now_iso()),
    }


def merge_execution_context(
    base: dict | None,
    extra: dict | None,
) -> dict[str, object] | None:
    normalized_base = _normalize_execution_context(base) or {
        "validated_commands": [],
        "notes": [],
        "updated_at": taskflow.now_iso(),
    }
    normalized_extra = _normalize_execution_context(extra)
    if normalized_extra is None:
        return normalized_base if normalized_base["validated_commands"] or normalized_base["notes"] else None
    merged_commands = list(normalized_base["validated_commands"])
    seen = {item["command"] for item in merged_commands}
    for item in normalized_extra["validated_commands"]:
        if item["command"] in seen:
            continue
        seen.add(item["command"])
        merged_commands.append(item)
    merged_notes = list(normalized_base["notes"])
    for note in normalized_extra["notes"]:
        if note not in merged_notes:
            merged_notes.append(note)
    if not merged_commands and not merged_notes:
        return None
    return {
        "validated_commands": merged_commands,
        "notes": merged_notes,
        "updated_at": taskflow.now_iso(),
    }


def load_execution_context_for_root(root: Path | None, registry: dict) -> dict[str, object] | None:
    if root is None:
        return None
    path = execution_context_path(root, registry)
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except json.JSONDecodeError:
        return None
    return _normalize_execution_context(payload)


def persist_execution_context(
    registry: dict,
    *,
    workspace_root: Path | None,
    project_root: Path | None = None,
    payload: dict | None,
) -> list[str]:
    normalized = _normalize_execution_context(payload)
    if normalized is None:
        return []
    paths: list[str] = []
    seen_roots: set[Path] = set()
    for root in (workspace_root, project_root):
        if root is None:
            continue
        resolved = root.resolve()
        if resolved in seen_roots:
            continue
        seen_roots.add(resolved)
        path = execution_context_path(resolved, registry)
        merged = merge_execution_context(load_execution_context_for_root(resolved, registry), normalized)
        if merged is None:
            continue
        write_json(path, merged)
        paths.append(str(path))
    return paths


def load_task_execution_context(
    registry: dict,
    *,
    workspace_root: Path | None,
    project_root: Path | None,
) -> dict[str, object] | None:
    merged = merge_execution_context(
        load_execution_context_for_root(workspace_root, registry),
        load_execution_context_for_root(project_root, registry),
    )
    return merged


def doctor_execution_context_payload(
    *,
    workspace_root: Path,
    project_root: Path | None,
) -> dict[str, object]:
    payload = discover_execution_context(
        workspace_root=workspace_root,
        project_root=project_root,
    )
    if payload is not None:
        return payload
    return {"notes": [f"{PRODUCT_NAME} doctor completed successfully for this workspace context."]}


def setup_execution_context_payload(*, hosts: list[str], workspace_root: Path) -> dict[str, object]:
    notes = [f"{PRODUCT_NAME} host setup completed for {', '.join(hosts)}."]
    return {"notes": notes}


def smoke_execution_context_payload(
    *,
    host_name: str,
    workspace_root: Path,
    initialized_workspace: bool,
) -> dict[str, object]:
    notes = [f"{PRODUCT_NAME} smoke flow completed successfully for host `{host_name}`."]
    if initialized_workspace:
        notes.append(f"{PRODUCT_NAME} initialized a default workspace profile during smoke setup.")
    return {"notes": notes}


def onboarding_state_path() -> Path:
    return expand_user_path(ONBOARDING_STATE_PATH)


def load_onboarding_state() -> dict[str, object]:
    path = onboarding_state_path()
    if not path.exists():
        return {"version": 1, "product": PRODUCT_NAME, "hosts": {}}
    payload = read_json(path)
    if not isinstance(payload, dict):
        return {"version": 1, "product": PRODUCT_NAME, "hosts": {}}
    payload.setdefault("version", 1)
    payload.setdefault("product", PRODUCT_NAME)
    payload.setdefault("hosts", {})
    return payload


def save_onboarding_state(payload: dict[str, object]) -> None:
    write_json(onboarding_state_path(), payload)


def host_state(state: dict[str, object], host_name: str) -> dict[str, object]:
    hosts = state.setdefault("hosts", {})
    if not isinstance(hosts, dict):
        fail("onboarding state is invalid: `hosts` must be an object")
    entry = hosts.setdefault(host_name, {})
    if not isinstance(entry, dict):
        fail(f"onboarding state is invalid for host `{host_name}`")
    return entry


def expand_user_path(path: Path) -> Path:
    return path.expanduser().resolve()


def detect_current_host() -> str | None:
    explicit = os.environ.get("RELAYKIT_HOST")
    if explicit in SUPPORTED_ONBOARDING_HOSTS:
        return explicit
    if os.environ.get("CODEX_HOME"):
        return "codex"
    return None


def running_from_source_tree() -> bool:
    argv0 = Path(sys.argv[0]).expanduser()
    try:
        resolved = argv0.resolve()
    except OSError:
        return False
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError:
        return False
    return True


def setup_hosts(requested_hosts: list[str] | None, *, current_host: bool) -> list[str]:
    if requested_hosts or current_host:
        return onboarding_hosts(requested_hosts, current_host=current_host)
    detected = detect_current_host()
    if detected:
        return [detected]
    fail(
        "unable to choose a host for setup; pass --host explicitly or set RELAYKIT_HOST",
        details=[f"supported hosts: {', '.join(SUPPORTED_ONBOARDING_HOSTS)}"],
    )


def onboarding_hosts(requested_hosts: list[str] | None, *, current_host: bool) -> list[str]:
    hosts: list[str] = []
    if current_host:
        detected = detect_current_host()
        if detected is None:
            fail(
                "unable to detect the current host; Codex auto-detection is built in, otherwise pass --host explicitly or set RELAYKIT_HOST",
            )
        hosts.append(detected)
    hosts.extend(requested_hosts or [])
    if not hosts:
        return list(SUPPORTED_ONBOARDING_HOSTS)
    unique_hosts: list[str] = []
    for host in hosts:
        if host not in SUPPORTED_ONBOARDING_HOSTS:
            fail(f"unsupported host `{host}`", details=[f"supported hosts: {', '.join(SUPPORTED_ONBOARDING_HOSTS)}"])
        if host not in unique_hosts:
            unique_hosts.append(host)
    return unique_hosts


def resolved_onboarding_hosts(requested_hosts: list[str] | None, *, current_host: bool, all_hosts: bool = False) -> list[str]:
    if all_hosts:
        return list(SUPPORTED_ONBOARDING_HOSTS)
    return onboarding_hosts(requested_hosts, current_host=current_host)


def resolved_setup_hosts(requested_hosts: list[str] | None, *, current_host: bool, all_hosts: bool = False) -> list[str]:
    if all_hosts:
        return list(SUPPORTED_ONBOARDING_HOSTS)
    return setup_hosts(requested_hosts, current_host=current_host)


def mcp_server_spec() -> dict[str, object]:
    if os.environ.get("RELAYKIT_PREFER_SOURCE_MCP") == "1" or running_from_source_tree():
        return {
            "name": MCP_SERVER_NAME,
            "command": MCP_SERVER_COMMAND,
            "args": [str(MCP_SERVER_PATH)],
        }
    entrypoint = shutil.which(MCP_SERVER_ENTRYPOINT)
    if entrypoint:
        return {
            "name": MCP_SERVER_NAME,
            "command": entrypoint,
            "args": [],
        }
    pipx_entrypoint = expand_user_path(Path("~/.local/bin") / MCP_SERVER_ENTRYPOINT)
    if pipx_entrypoint.exists():
        return {
            "name": MCP_SERVER_NAME,
            "command": str(pipx_entrypoint),
            "args": [],
        }
    return {
        "name": MCP_SERVER_NAME,
        "command": MCP_SERVER_COMMAND,
        "args": [str(MCP_SERVER_PATH)],
    }


def host_restart_hint(host_name: str) -> str:
    hints = {
        "codex": "Restart Codex so it reloads the RelayKit MCP server and tool catalog.",
        "claude-code": "Restart Claude Code so it reloads the RelayKit MCP server and tool catalog.",
        "gemini-cli": "Restart Gemini CLI so it reloads the RelayKit MCP server and tool catalog.",
        "antigravity": "Restart Antigravity so it reloads the RelayKit MCP server and tool catalog.",
    }
    return hints[host_name]


def first_use_prompt(host_name: str, workspace_root: Path) -> str:
    label_map = {
        "codex": "RelayKit",
        "claude-code": "RelayKit",
        "gemini-cli": "RelayKit",
        "antigravity": "RelayKit",
    }
    label = label_map[host_name]
    return (
        f"Use {label} MCP tools directly. Do not use the relaykit CLI wrapper unless an MCP tool is missing.\n\n"
        f"Run this smoke test in {workspace_root}:\n\n"
        f"1. Call {label} Doctor with:\n"
        f"   - workspace_root: {workspace_root}\n\n"
        f"2. If workspace_profile.status is \"missing\", call {label} Init Workspace with:\n"
        f"   - workspace_root: {workspace_root}\n\n"
        f"3. Call {label} Start Task with:\n"
        f"   - workspace_root: {workspace_root}\n"
        f"   - task: \"{SMOKE_TASK_TEXT}\"\n\n"
        f"4. Answer the first clarification with:\n"
        f"   - \"{SMOKE_FIRST_ANSWER}\"\n\n"
        f"5. Skip any remaining clarification.\n\n"
        f"6. Call {label} Confirm Task and accept the recommendation.\n\n"
        f"7. Call {label} Checkpoint Task with:\n"
        f"   - notes: \"{host_name} MCP-only smoke checkpoint after confirmation.\"\n\n"
        f"8. Call {label} Reflect Task with:\n"
        f"   - split_worth_it: no\n"
        f"   - tool_fit: good\n"
        f"   - simpler_better: no\n"
        f"   - apply: true\n\n"
        "Return:\n"
        "- whether each MCP call succeeded\n"
        "- the task_id\n"
        "- whether any CLI wrapper was used\n"
        "- any error exactly as shown if something fails\n"
    )


def skill_names() -> list[str]:
    return sorted(path.name for path in SKILLS_ROOT.iterdir() if (path / "SKILL.md").exists())


def install_skill_home(destination: Path, *, force: bool) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    for skill_name in skill_names():
        source = SKILLS_ROOT / skill_name
        target = destination / skill_name
        if target.exists():
            if not force:
                continue
            shutil.rmtree(target)
        shutil.copytree(source, target)
        installed.append(str(target.resolve()))
    return installed


def remove_skill_home(destination: Path) -> list[str]:
    removed: list[str] = []
    for skill_name in skill_names():
        target = destination / skill_name
        if target.exists():
            shutil.rmtree(target)
            removed.append(str(target.resolve()))
    return removed


def strip_toml_table(text: str, table_name: str) -> str:
    pattern = re.compile(rf"(?ms)^\[{re.escape(table_name)}\]\n(?:.*\n)*?(?=^\[|\Z)")
    return re.sub(pattern, "", text)


def write_codex_mcp_config(path: Path) -> dict[str, object]:
    server = mcp_server_spec()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = strip_toml_table(existing, f"mcp_servers.{MCP_SERVER_NAME}").rstrip()
    lines = [
        f"[mcp_servers.{MCP_SERVER_NAME}]",
        f'command = "{server["command"]}"',
    ]
    args = server.get("args") or []
    if args:
        rendered_args = ", ".join(f'"{arg}"' for arg in args)
        lines.append(f"args = [{rendered_args}]")
    block = "\n".join(lines)
    final_text = (updated + "\n\n" + block + "\n").lstrip("\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(final_text, encoding="utf-8")
    return {"path": str(path.resolve()), "configured": True}


def write_claude_mcp_config(path: Path) -> dict[str, object]:
    server = mcp_server_spec()
    subprocess.run(
        ["claude", "mcp", "remove", "--scope", "user", MCP_SERVER_NAME],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    command = ["claude", "mcp", "add", "--scope", "user", MCP_SERVER_NAME, "--", str(server["command"])]
    command.extend(str(arg) for arg in (server.get("args") or []))
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        fail(
            "failed to configure Claude Code MCP",
            details=[result.stderr.strip() or result.stdout.strip() or "unknown claude mcp add failure"],
        )
    return {"path": str(path.resolve()), "configured": True}


def remove_codex_mcp_config(path: Path) -> dict[str, object]:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = strip_toml_table(existing, f"mcp_servers.{MCP_SERVER_NAME}").rstrip()
    path.parent.mkdir(parents=True, exist_ok=True)
    if updated:
        path.write_text(updated + "\n", encoding="utf-8")
    else:
        path.write_text("", encoding="utf-8")
    return {"path": str(path.resolve()), "configured": False}


def remove_claude_mcp_config(path: Path) -> dict[str, object]:
    result = subprocess.run(
        ["claude", "mcp", "remove", "--scope", "user", MCP_SERVER_NAME],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode not in {0, 1}:
        fail(
            "failed to remove Claude Code MCP",
            details=[result.stderr.strip() or result.stdout.strip() or "unknown claude mcp remove failure"],
        )
    return {"path": str(path.resolve()), "configured": False}


def write_json_mcp_config(path: Path) -> dict[str, object]:
    server = mcp_server_spec()
    payload = read_json(path) if path.exists() else {}
    mcp_servers = payload.setdefault("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        fail(f"`mcpServers` must be an object in {path}")
    mcp_servers[MCP_SERVER_NAME] = {
        "command": server["command"],
        **({"args": server["args"]} if server.get("args") else {}),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path.resolve()), "configured": True}


def remove_json_mcp_config(path: Path) -> dict[str, object]:
    payload = read_json(path) if path.exists() else {}
    mcp_servers = payload.setdefault("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        fail(f"`mcpServers` must be an object in {path}")
    mcp_servers.pop(MCP_SERVER_NAME, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path.resolve()), "configured": False}


def host_onboarding_status(host_name: str) -> dict[str, object]:
    state = load_onboarding_state()
    persisted = host_state(state, host_name)
    payload: dict[str, object] = {
        "host": host_name,
        "product": PRODUCT_NAME,
        "current_host_detected": detect_current_host() == host_name,
        "recommended": [],
        "state": persisted,
    }
    skill_home = HOST_SKILL_HOMES.get(host_name)
    if skill_home is not None:
        resolved = expand_user_path(skill_home)
        installed = (resolved / "relaykit" / "SKILL.md").exists()
        payload["skills"] = {
            "path": str(resolved),
            "installed": installed,
            "auto_configurable": True,
        }
        if not installed:
            payload["recommended"].append(
                {
                    "action": "install_skills",
                    "host": host_name,
                    "path": str(resolved),
                }
            )
    else:
        payload["skills"] = {
            "path": None,
            "installed": False,
            "auto_configurable": False,
        }

    mcp_target = HOST_MCP_TARGETS.get(host_name)
    if mcp_target is None:
        payload["mcp"] = {
            "path": None,
            "configured": False,
            "auto_configurable": False,
        }
        return payload

    resolved_mcp_path = expand_user_path(mcp_target["path"])
    configured = False
    if mcp_target["kind"] == "toml" and resolved_mcp_path.exists():
        configured = f"[mcp_servers.{MCP_SERVER_NAME}]" in resolved_mcp_path.read_text(encoding="utf-8")
    if mcp_target["kind"] == "json" and resolved_mcp_path.exists():
        configured = MCP_SERVER_NAME in read_json(resolved_mcp_path).get("mcpServers", {})
    if mcp_target["kind"] == "claude-cli":
        result = subprocess.run(
            ["claude", "mcp", "get", MCP_SERVER_NAME],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        configured = result.returncode == 0
    payload["mcp"] = {
        "path": str(resolved_mcp_path),
        "configured": configured,
        "auto_configurable": True,
        "server": mcp_server_spec(),
    }
    if not configured:
        payload["recommended"].append(
            {
                "action": "install_mcp",
                "host": host_name,
                "path": str(resolved_mcp_path),
                "server": mcp_server_spec(),
            }
        )
    return payload


def bootstrap_host(
    host_name: str,
    *,
    install_skills: bool,
    configure_mcp: bool,
    force: bool,
    dry_run: bool,
) -> dict[str, object]:
    payload = {"host": host_name, "product": PRODUCT_NAME, "dry_run": dry_run}
    state = load_onboarding_state()
    entry = host_state(state, host_name)
    if install_skills:
        skill_home = HOST_SKILL_HOMES.get(host_name)
        if skill_home is None:
            payload["skills"] = {"configured": False, "reason": "no known skill home for this host"}
        else:
            resolved_home = expand_user_path(skill_home)
            installed = (
                [str((resolved_home / name).resolve()) for name in skill_names()]
                if dry_run
                else install_skill_home(resolved_home, force=force)
            )
            payload["skills"] = {
                "configured": not dry_run,
                "path": str(resolved_home),
                "installed_paths": installed,
            }
    if configure_mcp:
        mcp_target = HOST_MCP_TARGETS.get(host_name)
        if mcp_target is None:
            payload["mcp"] = {"configured": False, "reason": "no documented auto-configurable MCP surface for this host"}
        else:
            resolved = expand_user_path(mcp_target["path"])
            if dry_run:
                payload["mcp"] = {"configured": False, "path": str(resolved), "preview": mcp_server_spec()}
            elif mcp_target["kind"] == "toml":
                payload["mcp"] = write_codex_mcp_config(resolved)
            elif mcp_target["kind"] == "claude-cli":
                payload["mcp"] = write_claude_mcp_config(resolved)
            else:
                payload["mcp"] = write_json_mcp_config(resolved)
    if not dry_run:
        entry["last_bootstrap"] = payload
        entry["dismissed"] = False
        save_onboarding_state(state)
    return payload


def uninstall_host(
    host_name: str,
    *,
    remove_skills: bool,
    remove_mcp: bool,
    dry_run: bool,
) -> dict[str, object]:
    payload = {"host": host_name, "product": PRODUCT_NAME, "dry_run": dry_run}
    state = load_onboarding_state()
    entry = host_state(state, host_name)
    if remove_skills:
        skill_home = HOST_SKILL_HOMES.get(host_name)
        if skill_home is None:
            payload["skills"] = {"configured": False, "reason": "no known skill home for this host"}
        else:
            resolved = expand_user_path(skill_home)
            payload["skills"] = {
                "configured": False,
                "path": str(resolved),
                "removed_paths": [str((resolved / name).resolve()) for name in skill_names()] if dry_run else remove_skill_home(resolved),
            }
    if remove_mcp:
        mcp_target = HOST_MCP_TARGETS.get(host_name)
        if mcp_target is None:
            payload["mcp"] = {"configured": False, "reason": "no documented auto-configurable MCP surface for this host"}
        else:
            resolved = expand_user_path(mcp_target["path"])
            if dry_run:
                payload["mcp"] = {"configured": True, "path": str(resolved), "preview_remove": MCP_SERVER_NAME}
            elif mcp_target["kind"] == "toml":
                payload["mcp"] = remove_codex_mcp_config(resolved)
            elif mcp_target["kind"] == "claude-cli":
                payload["mcp"] = remove_claude_mcp_config(resolved)
            else:
                payload["mcp"] = remove_json_mcp_config(resolved)
    if not dry_run:
        entry["last_uninstall"] = payload
        save_onboarding_state(state)
    return payload


def build_onboarding_actions(hosts_payload: list[dict[str, object]]) -> dict[str, object]:
    hosts_needing_onboarding = [item["host"] for item in hosts_payload if item.get("recommended")]
    dismissed_hosts = [
        item["host"]
        for item in hosts_payload
        if item.get("recommended") and isinstance(item.get("state"), dict) and item["state"].get("dismissed")
    ]
    return {
        "needs_onboarding": bool(hosts_needing_onboarding),
        "should_prompt": bool(hosts_needing_onboarding) and len(dismissed_hosts) != len(hosts_needing_onboarding),
        "suggested_hosts": hosts_needing_onboarding,
        "dismissed_hosts": dismissed_hosts,
        "prompt_text": (
            "RelayKit is available, but host integration is incomplete. "
            "Install skills and MCP wiring for the suggested host(s)?"
            if hosts_needing_onboarding
            else "RelayKit host integration is already configured for the requested host set."
        ),
        "apply_tool": "relaykit_bootstrap_host",
        "apply_arguments": {
            "host": hosts_needing_onboarding,
            "force": False,
        },
        "skip_tool": "relaykit_acknowledge_host",
        "skip_arguments": {"host": hosts_needing_onboarding},
        "remove_tool": "relaykit_uninstall_host",
        "remove_arguments": {"host": hosts_needing_onboarding, "dry_run": True},
    }


def attach_host_onboarding(
    payload: dict[str, object],
    *,
    requested_hosts: list[str] | None = None,
    current_host: bool = False,
    auto_detect: bool = True,
) -> dict[str, object]:
    use_current_host = current_host or (auto_detect and detect_current_host() is not None)
    if not requested_hosts and not use_current_host:
        return payload
    hosts = onboarding_hosts(requested_hosts, current_host=use_current_host)
    payload["host_onboarding"] = {
        "server": mcp_server_spec(),
        "hosts": [host_onboarding_status(host_name) for host_name in hosts],
    }
    payload["needs_host_onboarding"] = any(item["recommended"] for item in payload["host_onboarding"]["hosts"])
    return payload


def registry_defaults(registry: dict) -> dict:
    return registry["defaults"]


def profile_dir(root: Path, registry: dict) -> Path:
    return root / registry_defaults(registry)["profile_dirname"]


def workspace_profile_path(root: Path, registry: dict) -> Path:
    return profile_dir(root, registry) / registry_defaults(registry)["workspace_profile_filename"]


def project_profile_path(root: Path, registry: dict) -> Path:
    return profile_dir(root, registry) / registry_defaults(registry)["project_profile_filename"]


def find_workspace_profile(start: Path, registry: dict) -> Path | None:
    current = start.resolve()
    for root in [current, *current.parents]:
        candidate = workspace_profile_path(root, registry)
        if candidate.exists():
            return candidate
    return None


def load_optional_profile(path: Path | None, expected_kind: str | None = None) -> tuple[Path | None, dict | None]:
    if path is None or not path.exists():
        return None, None
    payload = read_json(path)
    if expected_kind is not None and payload.get("kind") != expected_kind:
        fail(f"profile `{path}` is not a `{expected_kind}`")
    return path, payload


def default_workspace_profile(registry: dict) -> dict:
    return {
        "version": 1,
        "kind": PROFILE_KIND_WORKSPACE,
        "preset": registry_defaults(registry)["default_preset"],
        "inventory": taskflow.default_inventory(registry),
        "default_personas": deepcopy(registry_defaults(registry)["default_personas"]),
        "lane_overrides": {},
        "notes": "Created by RelayKit workspace onboarding.",
    }


def guided_workspace_profile(
    registry: dict,
    *,
    available_hosts: list[str],
    preset: str,
    git_integration: bool,
) -> dict:
    profile = default_workspace_profile(registry)
    hosts = ensure_known_values(available_hosts, valid=known_hosts(registry), label="available hosts")
    if not hosts:
        fail("guided setup requires at least one valid host")
    if preset not in registry.get("presets", {}):
        fail(f"unknown preset `{preset}`")
    profile["preset"] = preset
    profile["git_integration"] = bool(git_integration)
    profile["inventory"]["available_hosts"] = hosts
    profile["inventory"]["allowed_models_by_host"] = {
        host_name: list(profile["inventory"]["allowed_models_by_host"].get(host_name, []))
        for host_name in hosts
    }
    profile["notes"] = "Created by RelayKit guided setup."
    return profile


def default_project_profile(project_name: str) -> dict:
    return {
        "version": 1,
        "kind": PROFILE_KIND_PROJECT,
        "project_name": project_name,
        "inherits_workspace_defaults": True,
        "preset": None,
        "default_personas": [],
        "lane_overrides": {},
        "notes": "Created by RelayKit project onboarding.",
    }


def prompt_text(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def prompt_csv(label: str, default: list[str] | None = None) -> list[str]:
    default_text = ",".join(default or [])
    raw = prompt_text(label, default_text)
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def prompt_bool(label: str, default: bool) -> bool:
    default_text = "y" if default else "n"
    raw = prompt_text(label, default_text).lower()
    return raw in {"y", "yes", "true", "1"}


def prompt_hosts(registry: dict, label: str, default: list[str]) -> list[str]:
    hosts = ensure_known_values(
        prompt_csv(label, default),
        valid=known_hosts(registry),
        label=label,
    )
    return hosts or default


def prompt_models_for_host(registry: dict, host_name: str, default: list[str]) -> list[str]:
    valid = [
        model_name
        for model_name, meta in registry["models"].items()
        if host_name in meta["hosts"]
    ]
    models = ensure_known_values(
        prompt_csv(f"Models for {host_name}", default),
        valid=sorted(valid),
        label=f"models for {host_name}",
    )
    return models or default


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-")


def known_roles(registry: dict) -> list[str]:
    roles: set[str] = set()
    for meta in registry.get("skills", {}).values():
        role = meta.get("default_role")
        if isinstance(role, str) and role:
            roles.add(role)
    for meta in registry.get("personas", {}).values():
        for role in meta.get("compatible_roles", []):
            if isinstance(role, str) and role:
                roles.add(role)
    for preset in registry.get("presets", {}).values():
        for lane in preset.get("lanes", {}).values():
            role = lane.get("role")
            if isinstance(role, str) and role:
                roles.add(role)
    return sorted(roles)


def known_hosts(registry: dict) -> list[str]:
    return sorted(registry.get("hosts", {}).keys())


def project_uses_workspace_defaults(project_profile: dict | None) -> bool:
    if project_profile is None:
        return True
    return bool(project_profile.get("inherits_workspace_defaults", True))


def project_base_preset(
    registry: dict,
    *,
    workspace_profile: dict | None,
    project_profile: dict | None,
) -> str:
    default_preset = registry_defaults(registry)["default_preset"]
    if not project_uses_workspace_defaults(project_profile):
        return default_preset
    if workspace_profile and workspace_profile.get("preset"):
        return workspace_profile["preset"]
    return default_preset


def persona_conflict_issues(
    registry: dict,
    persona_names: list[str],
    *,
    origin: str,
) -> list[str]:
    issues: list[str] = []
    selected = set(persona_names)
    seen_pairs: set[tuple[str, str]] = set()
    for name in dedupe(persona_names):
        meta = registry["personas"].get(name)
        if meta is None:
            continue
        for conflict in meta.get("conflicts_with", []):
            if conflict not in selected:
                continue
            pair = tuple(sorted((name, conflict)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            issues.append(
                f"{origin} includes conflicting personas `{pair[0]}` and `{pair[1]}`"
            )
    return issues


def parse_override_spec(spec: str, registry: dict) -> dict:
    parts = [part.strip() for part in spec.split(":") if part.strip()]
    if len(parts) not in {2, 3}:
        fail("lane override must use `host:model` or `host:model:reasoning_effort`")
    host_name, model_name = parts[0], parts[1]
    reasoning = parts[2] if len(parts) == 3 else None
    if host_name not in registry["hosts"]:
        fail(f"unknown host `{host_name}`")
    if model_name not in registry["models"]:
        fail(f"unknown model `{model_name}`")
    if host_name not in registry["models"][model_name]["hosts"]:
        fail(f"model `{model_name}` is not available on host `{host_name}`")
    if reasoning and not registry["hosts"][host_name]["supports_reasoning_effort"]:
        fail(f"host `{host_name}` does not expose reasoning effort")
    payload = {"host": host_name, "model": model_name}
    if reasoning:
        payload["reasoning_effort"] = reasoning
    return payload


def ensure_known_personas(registry: dict, persona_names: list[str], *, label: str) -> list[str]:
    unknown = [name for name in persona_names if name not in registry["personas"]]
    if unknown:
        fail(f"unknown personas in {label}", details=sorted(unknown))
    return dedupe(persona_names)


def ensure_known_values(values: list[str], *, valid: list[str], label: str) -> list[str]:
    selected = dedupe(values)
    unknown = sorted(set(selected) - set(valid))
    if unknown:
        fail(f"unknown values in {label}", details=unknown)
    return selected


def persona_catalog_entry(registry: dict, persona_name: str) -> dict:
    meta = registry["personas"][persona_name]
    return {
        "id": persona_name,
        "name": meta["name"],
        "summary": meta["summary"],
        "kind": meta["kind"],
        "tier": meta["tier"],
        "activation": meta["activation"],
        "token_cost": meta["token_cost"],
        "compatible_roles": meta["compatible_roles"],
        "compatible_hosts": meta["compatible_hosts"],
        "conflicts_with": meta["conflicts_with"],
        "path": resolve_relative(meta["path"]),
        "source": meta["source"],
    }


def build_persona_catalog(registry: dict) -> dict:
    entries = [
        persona_catalog_entry(registry, persona_name)
        for persona_name in sorted_personas(registry, list(registry["personas"].keys()))
    ]
    recommended = [entry for entry in entries if entry["tier"] == "recommended"]
    optional = [entry for entry in entries if entry["tier"] == "optional"]
    return {
        "product": "RelayKit",
        "persona_mode": registry_defaults(registry)["persona_mode"],
        "registered_root": str((REPO_ROOT / "personas").resolve()),
        "project_local_overlay_support": True,
        "project_local_overlay_flag": "--persona-path",
        "recommended": recommended,
        "optional": optional,
        "all": entries,
    }


def persona_layer_summary(registry: dict) -> dict:
    personas = registry.get("personas", {})
    recommended = sorted(
        name for name, meta in personas.items() if meta.get("tier") == "recommended"
    )
    optional = sorted(
        name for name, meta in personas.items() if meta.get("tier") == "optional"
    )
    defaults = registry.get("defaults", {})
    return {
        "mode": defaults.get("persona_mode"),
        "recommended": recommended,
        "optional": optional,
        "project_local_overlay_support": True,
        "project_local_overlay_flag": "--persona-path",
        "registered_root": str((REPO_ROOT / "personas").resolve()),
    }


def next_persona_load_order(registry: dict) -> int:
    existing = [
        meta.get("load_order", 0)
        for meta in registry.get("personas", {}).values()
        if isinstance(meta.get("load_order"), int)
    ]
    return (max(existing) if existing else 0) + 5


def persona_scaffold_content(
    *,
    persona_name: str,
    persona_id: str,
    description: str,
    kind: str,
    principles: list[str],
    source: str,
) -> str:
    lines = [
        "---",
        f"name: {persona_id}",
        f"description: {description}",
        f"kind: {kind}",
        "---",
        "",
        f"# {persona_name}",
        "",
    ]
    if source not in {"built-in", "local"}:
        lines.extend(
            [
                "Derived from external inspiration.",
                f"Primary source: `{source}`.",
                "Import mode: rewrite.",
                "RelayKit adapts this persona for its own product context.",
                "",
            ]
        )
    else:
        lines.append("Use this persona when the lane should:")
        lines.append("")
        for principle in principles:
            lines.append(f"- {principle}")
        lines.extend(
            [
                "",
                "Do not let this persona override scope, verification, artifact contracts, or workflow transitions.",
                "",
            ]
        )
        return "\n".join(lines)

    lines.append("Use this persona when the lane should:")
    lines.append("")
    for principle in principles:
        lines.append(f"- {principle}")
    lines.extend(
        [
            "",
            "Do not let this persona override scope, verification, artifact contracts, or workflow transitions.",
            "",
        ]
    )
    return "\n".join(lines)


def build_persona_init_payload(registry: dict, args: argparse.Namespace) -> dict:
    persona_name = args.name.strip()
    persona_id = args.id.strip() if args.id else slugify(persona_name)
    if not persona_id:
        fail("persona id is required; provide --id or a name that can be slugified")
    if persona_id != slugify(persona_id):
        fail("persona id must be lowercase kebab-case")
    if args.kind not in PERSONA_KINDS:
        fail(f"persona kind must be one of: {', '.join(sorted(PERSONA_KINDS))}")
    if args.token_cost not in PERSONA_TOKEN_COSTS:
        fail(f"persona token_cost must be one of: {', '.join(sorted(PERSONA_TOKEN_COSTS))}")
    if args.tier not in PERSONA_TIERS:
        fail(f"persona tier must be one of: {', '.join(sorted(PERSONA_TIERS))}")

    roles = ensure_known_values(
        args.role or [],
        valid=known_roles(registry),
        label="persona compatible_roles",
    )
    if not roles:
        fail("persona must declare at least one compatible role with --role")
    hosts = ensure_known_values(
        args.host or known_hosts(registry),
        valid=known_hosts(registry),
        label="persona compatible_hosts",
    )
    conflicts = ensure_known_personas(
        registry,
        args.conflicts_with or [],
        label="persona conflicts_with",
    )

    relative_path = args.dest or f"personas/{persona_id}.md"
    destination = (REPO_ROOT / relative_path).resolve()
    try:
        destination.relative_to(REPO_ROOT)
    except ValueError:
        fail("registered personas must live inside the RelayKit repo; use --persona-path for external overlays")

    existing = registry["personas"].get(persona_id)
    if existing is not None and not args.force:
        fail(f"persona `{persona_id}` already exists in the registry; rerun with --force to overwrite")
    if destination.exists() and not args.force and not args.dry_run:
        fail(f"persona file already exists at `{destination}`; rerun with --force to overwrite")

    summary = args.summary or args.description
    principles = args.principle or [
        "add one clear operational bias here",
        "make tradeoffs more explicit",
        "improve decisions without taking over the lane",
    ]
    load_order = args.load_order if args.load_order is not None else next_persona_load_order(registry)
    content = persona_scaffold_content(
        persona_name=persona_name,
        persona_id=persona_id,
        description=args.description,
        kind=args.kind,
        principles=principles,
        source=args.source,
    )
    registry_entry = {
        "path": str(destination.relative_to(REPO_ROOT)),
        "name": persona_name,
        "summary": summary,
        "kind": args.kind,
        "tier": args.tier,
        "activation": registry_defaults(registry)["persona_mode"],
        "compatible_roles": roles,
        "compatible_hosts": hosts,
        "token_cost": args.token_cost,
        "conflicts_with": conflicts,
        "load_order": load_order,
        "source": args.source,
    }
    return {
        "product": "RelayKit",
        "persona_mode": registry_defaults(registry)["persona_mode"],
        "dry_run": bool(args.dry_run),
        "persona_id": persona_id,
        "file_path": str(destination),
        "registry_path": str(REGISTRY_PATH),
        "registry_entry": registry_entry,
        "content": content,
        "will_overwrite": bool(existing is not None or destination.exists()),
    }


def write_persona_init_payload(registry: dict, payload: dict) -> None:
    destination = Path(payload["file_path"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(payload["content"], encoding="utf-8")
    registry["personas"][payload["persona_id"]] = payload["registry_entry"]
    write_json(REGISTRY_PATH, registry)


def interactive_workspace_profile(registry: dict) -> dict:
    profile = default_workspace_profile(registry)
    print("RelayKit workspace onboarding")
    print("Press Enter to keep a default. Start by telling RelayKit which tools and models it may consider.")
    print("Personas are optional add-ins. Leave them empty unless you already know you want one.")
    inventory = profile["inventory"]
    inventory["available_hosts"] = prompt_hosts(
        registry,
        "Available hosts",
        inventory["available_hosts"],
    )
    inventory["allowed_models_by_host"] = {
        host_name: prompt_models_for_host(
            registry,
            host_name,
            inventory["allowed_models_by_host"].get(host_name, []),
        )
        for host_name in inventory["available_hosts"]
    }
    inventory["default_posture"] = prompt_text("Default posture", inventory["default_posture"])
    profile["preset"] = prompt_text("Preset", profile["preset"])
    profile["default_personas"] = ensure_known_personas(
        registry,
        prompt_csv("Default personas (optional add-ins)", profile["default_personas"]),
        label="workspace default_personas",
    )
    for lane in ["orchestrator", "builder", "frontend-builder", "frontend-tester", "critic"]:
        spec = prompt_text(f"{lane} override host:model[:reasoning]", "")
        if spec:
            profile["lane_overrides"][lane] = parse_override_spec(spec, registry)
    return profile


def interactive_project_profile(registry: dict, project_name: str) -> dict:
    profile = default_project_profile(project_name)
    print("RelayKit project onboarding")
    print("Press Enter to inherit workspace defaults unless this project really needs an override.")
    print("Project personas are optional add-ins. Skip them unless this project needs a real override.")
    profile["project_name"] = prompt_text("Project name", project_name)
    profile["inherits_workspace_defaults"] = prompt_bool("Use workspace defaults", True)
    if not profile["inherits_workspace_defaults"]:
        preset = prompt_text("Project preset override", "")
        profile["preset"] = preset or None
        profile["default_personas"] = ensure_known_personas(
            registry,
            prompt_csv("Project personas (optional add-ins)", []),
            label="project default_personas",
        )
        for lane in ["orchestrator", "builder", "frontend-builder", "frontend-tester", "critic"]:
            spec = prompt_text(f"{lane} override host:model[:reasoning]", "")
            if spec:
                profile["lane_overrides"][lane] = parse_override_spec(spec, registry)
    return profile


def ensure_profile_write(path: Path, force: bool) -> None:
    if path.exists() and not force:
        fail(f"profile already exists at `{path}`; rerun with `--force` to overwrite")


def merge_lane(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in override.items():
        merged[key] = deepcopy(value)
    return merged


def apply_lane_overrides(lanes: dict, overrides: dict) -> dict:
    for lane_name, override in overrides.items():
        base = lanes.get(lane_name, {})
        lanes[lane_name] = merge_lane(base, override)
    return lanes


def sorted_personas(registry: dict, persona_names: list[str]) -> list[str]:
    return sorted(
        dedupe(persona_names),
        key=lambda name: (
            registry["personas"][name].get("load_order", 100),
            name,
        ),
    )


def validate_lane_definition(
    lane_name: str,
    lane: dict,
    registry: dict,
    *,
    origin: str,
    require_complete: bool,
) -> list[str]:
    issues: list[str] = []
    skills = registry["skills"]
    hosts = registry["hosts"]
    models = registry["models"]
    personas = registry["personas"]

    skill_name = lane.get("skill")
    host_name = lane.get("host")
    model_name = lane.get("model")
    role_name = lane.get("role")
    reasoning = lane.get("reasoning_effort")

    if require_complete and not skill_name:
        issues.append(f"{origin} lane `{lane_name}` is missing `skill`")
    if require_complete and not host_name:
        issues.append(f"{origin} lane `{lane_name}` is missing `host`")
    if require_complete and not model_name:
        issues.append(f"{origin} lane `{lane_name}` is missing `model`")

    if skill_name and skill_name not in skills:
        issues.append(f"{origin} lane `{lane_name}` references unknown skill `{skill_name}`")
    if host_name and host_name not in hosts:
        issues.append(f"{origin} lane `{lane_name}` references unknown host `{host_name}`")
    if model_name and model_name not in models:
        issues.append(f"{origin} lane `{lane_name}` references unknown model `{model_name}`")

    effective_role = role_name or skills.get(skill_name, {}).get("default_role")
    if require_complete and not effective_role:
        issues.append(f"{origin} lane `{lane_name}` is missing `role`")

    if host_name and model_name and host_name in hosts and model_name in models:
        if host_name not in models[model_name]["hosts"]:
            issues.append(
                f"{origin} lane `{lane_name}` uses model `{model_name}` on incompatible host `{host_name}`"
            )

    if reasoning and host_name in hosts and not hosts[host_name]["supports_reasoning_effort"]:
        issues.append(
            f"{origin} lane `{lane_name}` sets `reasoning_effort` on host `{host_name}` which does not support it"
        )

    capabilities = lane.get("capabilities")
    if capabilities is not None and (
        not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities)
    ):
        issues.append(f"{origin} lane `{lane_name}` has invalid `capabilities`")

    lane_personas = lane.get("personas")
    if lane_personas is not None:
        if not isinstance(lane_personas, list) or any(not isinstance(item, str) for item in lane_personas):
            issues.append(f"{origin} lane `{lane_name}` has invalid `personas`")
        else:
            known_lane_personas: list[str] = []
            for persona_name in lane_personas:
                if persona_name not in personas:
                    issues.append(
                        f"{origin} lane `{lane_name}` references unknown persona `{persona_name}`"
                    )
                    continue
                known_lane_personas.append(persona_name)
                meta = personas[persona_name]
                if effective_role and effective_role not in meta["compatible_roles"]:
                    issues.append(
                        f"{origin} lane `{lane_name}` attaches persona `{persona_name}` to incompatible role `{effective_role}`"
                    )
                if host_name and host_name not in meta["compatible_hosts"]:
                    issues.append(
                        f"{origin} lane `{lane_name}` attaches persona `{persona_name}` to incompatible host `{host_name}`"
                    )
            issues.extend(
                persona_conflict_issues(
                    registry,
                    known_lane_personas,
                    origin=f"{origin} lane `{lane_name}`",
                )
            )

    credit_pool = lane.get("credit_pool")
    if credit_pool is not None and not isinstance(credit_pool, str):
        issues.append(f"{origin} lane `{lane_name}` has invalid `credit_pool`")

    return issues


def validate_registry(registry: dict) -> list[str]:
    issues: list[str] = []
    required_top_keys = {"defaults", "skills", "skillpacks", "hosts", "models", "personas", "presets"}
    missing = sorted(required_top_keys - set(registry.keys()))
    if missing:
        return [f"registry is missing top-level keys: {', '.join(missing)}"]

    defaults = registry["defaults"]
    for key in [
        "profile_dirname",
        "workspace_profile_filename",
        "project_profile_filename",
        "default_preset",
        "default_personas",
        "persona_mode",
    ]:
        if key not in defaults:
            issues.append(f"registry defaults missing `{key}`")
    if defaults.get("default_preset") not in registry["presets"]:
        issues.append("registry default preset does not exist")
    if not isinstance(defaults.get("default_personas"), list):
        issues.append("registry defaults `default_personas` must be a list")
    else:
        for persona_name in defaults["default_personas"]:
            if persona_name not in registry["personas"]:
                issues.append(f"registry defaults reference unknown persona `{persona_name}`")
        issues.extend(
            persona_conflict_issues(
                registry,
                defaults["default_personas"],
                origin="registry defaults",
            )
        )
    if defaults.get("persona_mode") not in PERSONA_ACTIVATIONS:
        issues.append(
            f"registry defaults `persona_mode` must be one of: {', '.join(sorted(PERSONA_ACTIVATIONS))}"
        )

    for skill_name, meta in registry["skills"].items():
        if not isinstance(meta.get("path"), str) or not meta["path"].strip():
            issues.append(f"skill `{skill_name}` must declare a non-empty `path`")
            continue
        if not Path(resolve_relative(meta["path"])).exists():
            issues.append(f"skill `{skill_name}` path is missing: {meta['path']}")
        if not meta.get("default_role"):
            issues.append(f"skill `{skill_name}` is missing `default_role`")
        if not isinstance(meta.get("default_capabilities"), list):
            issues.append(f"skill `{skill_name}` has invalid `default_capabilities`")

    for host_name, meta in registry["hosts"].items():
        if not isinstance(meta.get("path"), str) or not meta["path"].strip():
            issues.append(f"host `{host_name}` must declare a non-empty `path`")
            continue
        if not Path(resolve_relative(meta["path"])).exists():
            issues.append(f"host `{host_name}` path is missing: {meta['path']}")
        if not isinstance(meta.get("supports_reasoning_effort"), bool):
            issues.append(f"host `{host_name}` has invalid `supports_reasoning_effort`")
        if not isinstance(meta.get("default_models"), list):
            issues.append(f"host `{host_name}` has invalid `default_models`")

    for model_name, meta in registry["models"].items():
        if not isinstance(meta.get("path"), str) or not meta["path"].strip():
            issues.append(f"model `{model_name}` must declare a non-empty `path`")
            continue
        if not Path(resolve_relative(meta["path"])).exists():
            issues.append(f"model `{model_name}` path is missing: {meta['path']}")
        if not isinstance(meta.get("hosts"), list) or not meta["hosts"]:
            issues.append(f"model `{model_name}` must declare at least one host")
        else:
            for host_name in meta["hosts"]:
                if host_name not in registry["hosts"]:
                    issues.append(f"model `{model_name}` references unknown host `{host_name}`")

    for persona_name, meta in registry["personas"].items():
        for key in [
            "path",
            "name",
            "summary",
            "kind",
            "tier",
            "activation",
            "compatible_roles",
            "compatible_hosts",
            "token_cost",
            "conflicts_with",
            "load_order",
            "source",
        ]:
            if key not in meta:
                issues.append(f"persona `{persona_name}` missing `{key}`")
        if not isinstance(meta.get("path"), str) or not meta["path"].strip():
            issues.append(f"persona `{persona_name}` must declare a non-empty `path`")
        elif not Path(resolve_relative(meta["path"])).exists():
            issues.append(f"persona `{persona_name}` path is missing: {meta['path']}")
        if not isinstance(meta.get("compatible_roles"), list):
            issues.append(f"persona `{persona_name}` has invalid `compatible_roles`")
        if not isinstance(meta.get("compatible_hosts"), list):
            issues.append(f"persona `{persona_name}` has invalid `compatible_hosts`")
        if meta.get("tier") not in PERSONA_TIERS:
            issues.append(
                f"persona `{persona_name}` has invalid `tier`; expected one of {sorted(PERSONA_TIERS)}"
            )
        if meta.get("activation") not in PERSONA_ACTIVATIONS:
            issues.append(
                f"persona `{persona_name}` has invalid `activation`; expected one of {sorted(PERSONA_ACTIVATIONS)}"
            )
        if meta.get("token_cost") not in PERSONA_TOKEN_COSTS:
            issues.append(
                f"persona `{persona_name}` has invalid `token_cost`; expected one of {sorted(PERSONA_TOKEN_COSTS)}"
            )
        if not isinstance(meta.get("conflicts_with"), list):
            issues.append(f"persona `{persona_name}` has invalid `conflicts_with`")
        if not isinstance(meta.get("load_order"), int):
            issues.append(f"persona `{persona_name}` has invalid `load_order`")
        for conflict in meta.get("conflicts_with", []):
            if conflict not in registry["personas"]:
                issues.append(f"persona `{persona_name}` conflicts with unknown persona `{conflict}`")

    for preset_name, preset in registry["presets"].items():
        if not isinstance(preset.get("lanes"), dict):
            issues.append(f"preset `{preset_name}` has invalid `lanes`")
            continue
        for lane_name, lane in preset["lanes"].items():
            issues.extend(
                validate_lane_definition(
                    lane_name,
                    lane,
                    registry,
                    origin=f"preset `{preset_name}`",
                    require_complete=True,
                )
            )

    skillpacks = registry.get("skillpacks", {})
    if not isinstance(skillpacks, dict) or not skillpacks:
        issues.append("registry must declare at least one skillpack")
    else:
        for pack_name, pack in skillpacks.items():
            if not isinstance(pack, dict):
                issues.append(f"skillpack `{pack_name}` must be an object")
                continue
            if not isinstance(pack.get("description"), str) or not pack["description"].strip():
                issues.append(f"skillpack `{pack_name}` is missing `description`")
            entry_skill = pack.get("entry_skill")
            if not isinstance(entry_skill, str):
                issues.append(f"skillpack `{pack_name}` is missing `entry_skill`")
            skills_in_pack = pack.get("skills")
            if not isinstance(skills_in_pack, list) or not skills_in_pack:
                issues.append(f"skillpack `{pack_name}` must declare at least one skill")
                continue
            for skill_name in skills_in_pack:
                if not isinstance(skill_name, str):
                    issues.append(f"skillpack `{pack_name}` has a non-string skill entry")
                    continue
                if not (REPO_ROOT / "skills" / skill_name / "SKILL.md").exists():
                    issues.append(f"skillpack `{pack_name}` references missing skill `{skill_name}`")
            if isinstance(entry_skill, str) and entry_skill not in skills_in_pack:
                issues.append(f"skillpack `{pack_name}` entry skill `{entry_skill}` is not in its skill list")
            if not isinstance(pack.get("recommended_for"), list):
                issues.append(f"skillpack `{pack_name}` has invalid `recommended_for`")

    return issues


def validate_profile(
    profile: dict,
    registry: dict,
    *,
    expected_kind: str,
    base_preset: str,
    origin: str,
) -> list[str]:
    issues: list[str] = []
    if profile.get("version") != 1:
        issues.append(f"{origin} must use version 1")
    if profile.get("kind") != expected_kind:
        issues.append(f"{origin} kind must be `{expected_kind}`")

    if expected_kind == PROFILE_KIND_WORKSPACE:
        preset_name = profile.get("preset")
        if not isinstance(preset_name, str):
            issues.append(f"{origin} must declare a string `preset`")
        elif preset_name not in registry["presets"]:
            issues.append(f"{origin} references unknown preset `{preset_name}`")
        inventory = profile.get("inventory")
        if not isinstance(inventory, dict):
            issues.append(f"{origin} must declare `inventory`")
        else:
            available_hosts = inventory.get("available_hosts")
            if not isinstance(available_hosts, list) or not available_hosts:
                issues.append(f"{origin} inventory must declare at least one available host")
            else:
                for host_name in available_hosts:
                    if host_name not in registry["hosts"]:
                        issues.append(f"{origin} inventory references unknown host `{host_name}`")
            allowed_models = inventory.get("allowed_models_by_host")
            if not isinstance(allowed_models, dict):
                issues.append(f"{origin} inventory must declare `allowed_models_by_host`")
            else:
                for host_name, model_names in allowed_models.items():
                    if host_name not in registry["hosts"]:
                        issues.append(f"{origin} inventory references unknown host `{host_name}`")
                        continue
                    if not isinstance(model_names, list) or not model_names:
                        issues.append(f"{origin} inventory host `{host_name}` must declare at least one model")
                        continue
                    for model_name in model_names:
                        if model_name not in registry["models"]:
                            issues.append(f"{origin} inventory host `{host_name}` references unknown model `{model_name}`")
                        elif host_name not in registry["models"][model_name]["hosts"]:
                            issues.append(
                                f"{origin} inventory model `{model_name}` is not valid for host `{host_name}`"
                            )
            posture = inventory.get("default_posture")
            if posture not in taskflow.QUALITY_POSTURES:
                issues.append(
                    f"{origin} inventory default_posture must be one of {sorted(taskflow.QUALITY_POSTURES)}"
                )
    else:
        if not isinstance(profile.get("project_name"), str):
            issues.append(f"{origin} must declare `project_name`")
        if not isinstance(profile.get("inherits_workspace_defaults"), bool):
            issues.append(f"{origin} must declare boolean `inherits_workspace_defaults`")
        preset_name = profile.get("preset")
        if preset_name is not None and preset_name not in registry["presets"]:
            issues.append(f"{origin} references unknown preset `{preset_name}`")

    default_personas = profile.get("default_personas")
    if not isinstance(default_personas, list):
        issues.append(f"{origin} has invalid `default_personas`")
    else:
        for persona_name in default_personas:
            if persona_name not in registry["personas"]:
                issues.append(f"{origin} references unknown default persona `{persona_name}`")
        issues.extend(
            persona_conflict_issues(
                registry,
                default_personas,
                origin=f"{origin} default_personas",
            )
        )

    lane_overrides = profile.get("lane_overrides")
    if not isinstance(lane_overrides, dict):
        issues.append(f"{origin} has invalid `lane_overrides`")
        lane_overrides = {}
    else:
        for lane_name, override in lane_overrides.items():
            if not isinstance(override, dict):
                issues.append(f"{origin} lane override `{lane_name}` must be an object")
                continue
            unknown_keys = sorted(set(override.keys()) - ALLOWED_LANE_OVERRIDE_KEYS)
            if unknown_keys:
                issues.append(
                    f"{origin} lane override `{lane_name}` has unknown keys: {', '.join(unknown_keys)}"
                )

    effective_preset = profile.get("preset") or base_preset
    if effective_preset in registry["presets"]:
        lanes = deepcopy(registry["presets"][effective_preset]["lanes"])
        apply_lane_overrides(lanes, lane_overrides)
        for lane_name, lane in lanes.items():
            issues.extend(
                validate_lane_definition(
                    lane_name,
                    lane,
                    registry,
                    origin=origin,
                    require_complete=True,
                )
            )

    return issues


def resolve_effective_state(
    registry: dict,
    *,
    workspace_profile: dict | None,
    project_profile: dict | None,
    preset_override: str | None,
) -> dict:
    default_preset = registry_defaults(registry)["default_preset"]
    preset_id = preset_override
    if preset_id is None and project_profile is not None and project_profile.get("preset"):
        preset_id = project_profile["preset"]
    if (
        preset_id is None
        and project_uses_workspace_defaults(project_profile)
        and workspace_profile is not None
        and workspace_profile.get("preset")
    ):
        preset_id = workspace_profile["preset"]
    if preset_id is None:
        preset_id = default_preset
    if preset_id not in registry["presets"]:
        fail(f"unknown preset `{preset_id}`")

    lanes = deepcopy(registry["presets"][preset_id]["lanes"])
    if workspace_profile is not None and project_uses_workspace_defaults(project_profile):
        apply_lane_overrides(lanes, workspace_profile.get("lane_overrides", {}))
    if project_profile is not None:
        apply_lane_overrides(lanes, project_profile.get("lane_overrides", {}))

    workspace_personas = (
        workspace_profile.get("default_personas", [])
        if workspace_profile and project_uses_workspace_defaults(project_profile)
        else []
    )
    project_personas = project_profile.get("default_personas", []) if project_profile else []
    return {
        "preset": preset_id,
        "lanes": lanes,
        "default_personas": dedupe([*workspace_personas, *project_personas]),
        "cost_posture": registry["presets"][preset_id]["cost_posture"],
        "intent": registry["presets"][preset_id]["intent"],
    }


def filter_compatible_personas(
    registry: dict,
    persona_names: list[str],
    *,
    role: str,
    host: str,
) -> tuple[list[str], list[str]]:
    compatible: list[str] = []
    skipped: list[str] = []
    for name in sorted_personas(registry, persona_names):
        meta = registry["personas"][name]
        if role in meta["compatible_roles"] and host in meta["compatible_hosts"]:
            compatible.append(name)
        else:
            skipped.append(name)
    return compatible, skipped


def validate_personas(
    registry: dict,
    persona_names: list[str],
    *,
    role: str,
    host: str,
) -> list[str]:
    personas = registry["personas"]
    for name in persona_names:
        if name not in personas:
            fail(f"unknown persona `{name}`")
    for name in persona_names:
        meta = personas[name]
        if role not in meta["compatible_roles"]:
            fail(f"persona `{name}` is not compatible with role `{role}`")
        if host not in meta["compatible_hosts"]:
            fail(f"persona `{name}` is not compatible with host `{host}`")
    conflict_issues = persona_conflict_issues(
        registry,
        persona_names,
        origin=f"persona selection for role `{role}` on host `{host}`",
    )
    if conflict_issues:
        fail(conflict_issues[0], details=conflict_issues[1:] or None)
    return [resolve_relative(personas[name]["path"]) for name in sorted_personas(registry, persona_names)]


def build_stack(
    registry: dict,
    *,
    lane_name: str | None,
    skill_name: str | None,
    host_name: str | None,
    model_name: str | None,
    role: str | None,
    reasoning_effort: str | None,
    packet: str | None,
    repo_guide: str | None,
    preset: str | None,
    workspace_profile: dict | None,
    project_profile: dict | None,
    cli_personas: list[str],
    extra_persona_paths: list[str],
) -> dict:
    skills = registry["skills"]
    hosts = registry["hosts"]
    models = registry["models"]

    effective = resolve_effective_state(
        registry,
        workspace_profile=workspace_profile,
        project_profile=project_profile,
        preset_override=preset,
    )

    lane_data: dict = {}
    if lane_name:
        if lane_name not in effective["lanes"]:
            fail(f"effective preset `{effective['preset']}` has no lane `{lane_name}`")
        lane_data = deepcopy(effective["lanes"][lane_name])

    final_skill = skill_name or lane_data.get("skill")
    final_role = role or lane_data.get("role")
    final_host = host_name or lane_data.get("host")
    final_model = model_name or lane_data.get("model")
    final_reasoning = reasoning_effort or lane_data.get("reasoning_effort")
    final_capabilities = lane_data.get("capabilities") or skills.get(final_skill, {}).get(
        "default_capabilities", []
    )
    final_credit_pool = lane_data.get("credit_pool")
    lane_personas = lane_data.get("personas", [])

    if final_skill not in skills:
        fail("stack resolution requires a valid skill")
    if final_host not in hosts:
        fail("stack resolution requires a valid host")
    if final_model not in models:
        fail("stack resolution requires a valid model")
    if final_host not in models[final_model]["hosts"]:
        fail(f"model `{final_model}` is not registered for host `{final_host}`")
    if final_reasoning and not hosts[final_host]["supports_reasoning_effort"]:
        fail(f"host `{final_host}` does not expose reasoning effort")

    resolved_role = final_role or skills[final_skill]["default_role"]
    global_personas, skipped_personas = filter_compatible_personas(
        registry,
        effective["default_personas"],
        role=resolved_role,
        host=final_host,
    )
    explicit_personas = dedupe([*lane_personas, *cli_personas])
    selected_personas = dedupe([*global_personas, *explicit_personas])
    persona_paths = validate_personas(
        registry,
        selected_personas,
        role=resolved_role,
        host=final_host,
    )

    stack_components = [
        {
            "kind": "host-guide",
            "id": final_host,
            "path": resolve_relative(hosts[final_host]["path"]),
        },
        {
            "kind": "skill",
            "id": final_skill,
            "path": resolve_relative(skills[final_skill]["path"]),
        },
        {
            "kind": "model-note",
            "id": final_model,
            "path": resolve_relative(models[final_model]["path"]),
        },
    ]

    for persona_name in sorted_personas(registry, selected_personas):
        stack_components.append(
            {
                "kind": "persona",
                "id": persona_name,
                "path": resolve_relative(registry["personas"][persona_name]["path"]),
            }
        )
    for persona_path in extra_persona_paths:
        stack_components.append(
            {
                "kind": "persona-path",
                "id": Path(persona_path).stem,
                "path": str(Path(persona_path).resolve()),
            }
        )
    if packet:
        stack_components.append(
            {
                "kind": "packet",
                "id": Path(packet).name,
                "path": str(Path(packet).resolve()),
            }
        )
    if repo_guide:
        stack_components.append(
            {
                "kind": "repo-guide",
                "id": Path(repo_guide).name,
                "path": str(Path(repo_guide).resolve()),
            }
        )

    prompt_stack = [item["path"] for item in stack_components]
    selected_personas = [item["id"] for item in stack_components if item["kind"] == "persona"]

    return {
        "product": "RelayKit",
        "preset": effective["preset"],
        "intent": effective["intent"],
        "cost_posture": effective["cost_posture"],
        "lane": lane_name,
        "skill": final_skill,
        "role": resolved_role,
        "host": final_host,
        "model": final_model,
        "reasoning_effort": final_reasoning,
        "capabilities": final_capabilities,
        "credit_pool": final_credit_pool,
        "personas": selected_personas,
        "skipped_default_personas": skipped_personas,
        "primary_prompt_guide": prompt_stack[0],
        "prompt_stack": prompt_stack,
        "stack_components": stack_components,
    }


def render_stack_markdown(payload: dict) -> str:
    lines = [
        "# RelayKit Prompt Stack",
        "",
        f"- Preset: `{payload['preset']}`",
        f"- Lane: `{payload.get('lane') or 'custom'}`",
        f"- Skill: `{payload['skill']}`",
        f"- Role: `{payload['role']}`",
        f"- Host: `{payload['host']}`",
        f"- Model: `{payload['model']}`",
        f"- Cost posture: `{payload['cost_posture']}`",
        f"- Persona mode: `{payload.get('persona_mode', 'optional-addon')}`",
    ]
    if payload.get("reasoning_effort"):
        lines.append(f"- Reasoning effort: `{payload['reasoning_effort']}`")
    if payload.get("personas"):
        lines.append(f"- Personas: `{', '.join(payload['personas'])}`")
    if payload.get("skipped_default_personas"):
        lines.append(
            f"- Skipped default personas: `{', '.join(payload['skipped_default_personas'])}`"
        )
    if payload.get("capabilities"):
        lines.append(f"- Capabilities: `{', '.join(payload['capabilities'])}`")

    lines.extend(["", "## Load Order", ""])
    for index, item in enumerate(payload["stack_components"], start=1):
        lines.append(f"{index}. `{item['kind']}` `{item['id']}`")
        lines.append(f"   - {item['path']}")
    return "\n".join(lines)


def print_payload(payload: dict, output_format: str) -> None:
    if output_format == "markdown":
        print(render_stack_markdown(payload))
        return
    print(json.dumps(payload, indent=2))


def command_init_persona(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    payload = build_persona_init_payload(registry, args)
    if not args.dry_run:
        write_persona_init_payload(registry, payload)
    print(json.dumps(payload, indent=2))
    return 0


def resolve_workspace_profile_for_stack(
    args: argparse.Namespace,
    registry: dict,
) -> tuple[Path | None, dict | None]:
    if args.workspace_profile:
        explicit = Path(args.workspace_profile).resolve()
        return load_optional_profile(explicit, PROFILE_KIND_WORKSPACE)

    if args.workspace_root:
        workspace_root = Path(args.workspace_root).resolve()
        candidate = workspace_profile_path(workspace_root, registry)
        if candidate.exists():
            return load_optional_profile(candidate, PROFILE_KIND_WORKSPACE)
        if args.start_with_defaults:
            profile = default_workspace_profile(registry)
            write_json(candidate, profile)
            return candidate, profile
        fail(
            "workspace profile missing; run `relaykit.py init-workspace` or use `stack --start-with-defaults`"
        )

    found = find_workspace_profile(Path.cwd(), registry)
    if found is not None:
        return load_optional_profile(found, PROFILE_KIND_WORKSPACE)
    if args.start_with_defaults:
        candidate = workspace_profile_path(Path.cwd(), registry)
        profile = default_workspace_profile(registry)
        write_json(candidate, profile)
        return candidate, profile
    fail(
        "workspace profile missing; run `relaykit.py init-workspace` or use `stack --start-with-defaults`"
    )


def resolve_project_profile_for_stack(
    args: argparse.Namespace,
    registry: dict,
) -> tuple[Path | None, dict | None]:
    if args.project_profile:
        explicit = Path(args.project_profile).resolve()
        return load_optional_profile(explicit, PROFILE_KIND_PROJECT)
    if args.project_root:
        candidate = project_profile_path(Path(args.project_root).resolve(), registry)
        return load_optional_profile(candidate, PROFILE_KIND_PROJECT)
    candidate = project_profile_path(Path.cwd(), registry)
    return load_optional_profile(candidate, PROFILE_KIND_PROJECT)


def status_payload(path: Path | None, issues: list[str], *, optional: bool) -> dict:
    if path is None:
        return {
            "status": "missing",
            "optional": optional,
            "path": None,
            "issues": issues,
        }
    return {
        "status": "ok" if not issues else "invalid",
        "optional": optional,
        "path": str(path),
        "issues": issues,
    }


def build_doctor_payload(
    *,
    workspace_root: Path,
    project_root: Path | None = None,
    workspace_profile_override: Path | None = None,
    project_profile_override: Path | None = None,
    requested_hosts: list[str] | None = None,
    current_host: bool = False,
) -> dict[str, object]:
    registry = load_registry()
    registry_issues = validate_registry(registry)

    workspace_candidate = (
        workspace_profile_override.resolve()
        if workspace_profile_override
        else workspace_profile_path(workspace_root, registry)
    )
    workspace_path, workspace_profile = load_optional_profile(workspace_candidate, PROFILE_KIND_WORKSPACE)
    workspace_issues = (
        ["workspace profile is missing; run RelayKit workspace onboarding"]
        if workspace_profile is None
        else validate_profile(
            workspace_profile,
            registry,
            expected_kind=PROFILE_KIND_WORKSPACE,
            base_preset=registry_defaults(registry)["default_preset"],
            origin="workspace profile",
        )
    )

    project_payload = status_payload(None, [], optional=True)
    if project_root or project_profile_override:
        resolved_project_root = project_root.resolve() if project_root else Path.cwd().resolve()
        project_candidate = (
            project_profile_override.resolve()
            if project_profile_override
            else project_profile_path(resolved_project_root, registry)
        )
        project_path, project_profile = load_optional_profile(project_candidate, PROFILE_KIND_PROJECT)
        project_issues = (
            []
            if project_profile is None
            else validate_profile(
                project_profile,
                registry,
                expected_kind=PROFILE_KIND_PROJECT,
                base_preset=project_base_preset(
                    registry,
                    workspace_profile=workspace_profile,
                    project_profile=project_profile,
                ),
                origin="project profile",
            )
        )
        project_payload = status_payload(project_path, project_issues, optional=True)

    next_actions: list[str] = []
    guided_setup: dict[str, object] | None = None
    if workspace_profile is None:
        next_actions.append(f"relaykit init-workspace --workspace-root {workspace_root}")
        all_hosts = sorted(registry.get("hosts", {}).keys())
        all_presets = sorted(registry.get("presets", {}).keys())
        guided_setup = {
            "message": "No workspace profile found. Answer these 3 questions to create one.",
            "questions": [
                {
                    "id": "available_hosts",
                    "prompt": f"Which AI coding tools do you have available? Options: {', '.join(all_hosts)}",
                    "type": "multi_select",
                    "options": all_hosts,
                },
                {
                    "id": "preset",
                    "prompt": f"What's your default working style? Options: {', '.join(all_presets)}",
                    "type": "single_select",
                    "options": all_presets,
                    "default": registry_defaults(registry)["default_preset"],
                },
                {
                    "id": "git_integration",
                    "prompt": "Enable optional git branch preparation for task parts?",
                    "type": "boolean",
                    "default": False,
                },
            ],
            "apply_command": f"relaykit guided-setup --workspace-root {workspace_root}",
            "apply_arguments": {
                "workspace_root": str(workspace_root),
                "preset": registry_defaults(registry)["default_preset"],
                "git_integration": False,
            },
        }
    if project_root and project_payload["status"] == "missing":
        next_actions.append(
            "relaykit init-project "
            f"--project-root {project_root.resolve()} --use-workspace-defaults"
        )
    execution_context = discover_execution_context(
        workspace_root=workspace_root,
        project_root=project_root,
    )

    payload: dict[str, object] = {
        "product": PRODUCT_NAME,
        "registry": {
            "status": "ok" if not registry_issues else "invalid",
            "path": str(REGISTRY_PATH),
            "issues": registry_issues,
        },
        "workspace_profile": status_payload(workspace_path, workspace_issues, optional=False),
        "project_profile": project_payload,
        "schemas": {
            "workspace_profile": str((SCHEMA_ROOT / "workspace-profile.schema.json").resolve()),
            "project_profile": str((SCHEMA_ROOT / "project-profile.schema.json").resolve()),
        },
        "persona_layer": persona_layer_summary(registry),
        "next_actions": next_actions,
    }
    if execution_context is not None:
        payload["execution_context"] = execution_context
    if guided_setup:
        payload["guided_setup"] = guided_setup
    if requested_hosts or current_host:
        hosts = onboarding_hosts(requested_hosts, current_host=current_host)
        payload["host_onboarding"] = {
            "server": mcp_server_spec(),
            "hosts": [host_onboarding_status(host_name) for host_name in hosts],
        }
    return payload


def init_workspace_profile_payload(*, workspace_root: Path, force: bool = False) -> dict[str, object]:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    path = workspace_profile_path(workspace_root, registry)
    ensure_profile_write(path, force)
    profile = default_workspace_profile(registry)
    profile_issues = validate_profile(
        profile,
        registry,
        expected_kind=PROFILE_KIND_WORKSPACE,
        base_preset=registry_defaults(registry)["default_preset"],
        origin="workspace profile",
    )
    if profile_issues:
        fail("workspace profile is invalid", details=profile_issues)
    write_json(path, profile)
    return {"workspace_profile": str(path), "profile": profile}


def guided_workspace_profile_payload(
    *,
    workspace_root: Path,
    available_hosts: list[str],
    preset: str,
    git_integration: bool,
    force: bool = False,
) -> dict[str, object]:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    path = workspace_profile_path(workspace_root, registry)
    ensure_profile_write(path, force)
    profile = guided_workspace_profile(
        registry,
        available_hosts=available_hosts,
        preset=preset,
        git_integration=git_integration,
    )
    profile_issues = validate_profile(
        profile,
        registry,
        expected_kind=PROFILE_KIND_WORKSPACE,
        base_preset=registry_defaults(registry)["default_preset"],
        origin="workspace profile",
    )
    if profile_issues:
        fail("workspace profile is invalid", details=profile_issues)
    write_json(path, profile)
    return {"workspace_profile": str(path), "profile": profile}


def smoke_workspace_root(host_name: str) -> Path:
    slug = host_name.replace("-cli", "").replace("-", "-")
    return Path("/private/tmp") / f"relaykit-{slug}-smoke"


def run_smoke_flow(workspace_root: Path, *, host_name: str, force_workspace_init: bool = False) -> dict[str, object]:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)

    results: list[dict[str, object]] = []
    doctor_payload = build_doctor_payload(workspace_root=workspace_root)
    doctor_status = doctor_payload["workspace_profile"]["status"]  # type: ignore[index]
    results.append({"step": "doctor", "status": "succeeded", "workspace_profile_status": doctor_status})

    initialized_workspace = False
    if force_workspace_init or doctor_status == "missing":
        init_payload = init_workspace_profile_payload(workspace_root=workspace_root, force=force_workspace_init)
        results.append({"step": "init_workspace", "status": "succeeded", "workspace_profile": init_payload["workspace_profile"]})
        initialized_workspace = True

    workspace_profile_path_resolved = workspace_profile_path(workspace_root, registry)
    workspace_profile = read_json(workspace_profile_path_resolved)
    workspace_profile["inventory"]["available_hosts"] = [host_name]
    allowed_models = workspace_profile["inventory"].get("allowed_models_by_host", {})
    workspace_profile["inventory"]["allowed_models_by_host"] = {
        host_name: list(allowed_models.get(host_name, []))
    }
    write_json(workspace_profile_path_resolved, workspace_profile)

    task_started = taskflow.start_task(
        registry,
        workspace_root=workspace_root,
        project_root=None,
        workspace_profile=workspace_profile,
        project_profile=None,
        task_text=SMOKE_TASK_TEXT,
        task_scope=None,
        allowed_hosts=[host_name],
        skip_clarification=False,
    )
    task_id = task_started["task_id"]
    results.append({"step": "start_task", "status": "succeeded", "task_id": task_id})

    task_answer = taskflow.answer_task(
        registry,
        root=taskflow.root_for_task(workspace_root, None, None),
        task_id=task_id,
        answer=SMOKE_FIRST_ANSWER,
        question_id=None,
        workspace_profile=workspace_profile,
        project_profile=None,
    )
    results.append({"step": "answer_task", "status": "succeeded", "stage": task_answer.get("stage")})

    state = taskflow.load_task_state(task_id, taskflow.root_for_task(workspace_root, None, None), registry)
    state["clarification"]["skipped"] = True
    recommendation = taskflow.maybe_recommend(state, registry, workspace_profile, None)
    state_file, summary_file = taskflow.save_task_state(state, registry)
    recommendation["state_path"] = str(state_file)
    recommendation["summary_path"] = str(summary_file)
    results.append({"step": "skip_clarification", "status": "succeeded", "stage": recommendation.get("stage")})

    confirmed = taskflow.confirm_task(
        registry,
        root=taskflow.root_for_task(workspace_root, None, None),
        task_id=task_id,
        accept=True,
        change_text=None,
        workspace_profile=workspace_profile,
        project_profile=None,
    )
    results.append({"step": "confirm_task", "status": "succeeded", "stage": confirmed.get("stage")})

    checkpoint = taskflow.checkpoint_task(
        registry,
        root=taskflow.root_for_task(workspace_root, None, None),
        task_id=task_id,
        outcome=None,
        notes=f"{host_name} smoke checkpoint after confirmation.",
    )
    results.append({"step": "checkpoint_task", "status": "succeeded", "recommended_action": checkpoint.get("recommended_action")})

    reflection = taskflow.reflect_task(
        registry,
        root=taskflow.root_for_task(workspace_root, None, None),
        task_id=task_id,
        split_worth_it="no",
        tool_fit="good",
        simpler_better="no",
        notes=None,
        apply=True,
    )
    results.append({"step": "reflect_task", "status": "succeeded"})

    execution_context_paths = persist_execution_context(
        registry,
        workspace_root=workspace_root,
        payload=smoke_execution_context_payload(
            host_name=host_name,
            workspace_root=workspace_root,
            initialized_workspace=initialized_workspace,
        ),
        project_root=None,
    )

    payload = {
        "workspace_root": str(workspace_root),
        "task_id": task_id,
        "results": results,
        "reflection": reflection,
    }
    if execution_context_paths:
        payload["execution_context_paths"] = execution_context_paths
    return payload


def command_init_workspace(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)

    workspace_root = Path(args.workspace_root).resolve()
    path = workspace_profile_path(workspace_root, registry)
    ensure_profile_write(path, args.force)
    non_interactive_defaults = not sys.stdin.isatty()
    profile = (
        default_workspace_profile(registry)
        if args.start_with_defaults or non_interactive_defaults
        else interactive_workspace_profile(registry)
    )
    profile_issues = validate_profile(
        profile,
        registry,
        expected_kind=PROFILE_KIND_WORKSPACE,
        base_preset=registry_defaults(registry)["default_preset"],
        origin="workspace profile",
    )
    if profile_issues:
        fail("workspace profile is invalid", details=profile_issues)
    write_json(path, profile)
    print(json.dumps({"workspace_profile": str(path), "profile": profile}, indent=2))
    return 0


def command_guided_setup(args: argparse.Namespace) -> int:
    workspace_root = Path(args.workspace_root).resolve()
    payload = guided_workspace_profile_payload(
        workspace_root=workspace_root,
        available_hosts=args.host or [],
        preset=args.preset,
        git_integration=bool(args.git_integration),
        force=bool(args.force),
    )
    print(json.dumps(payload, indent=2))
    return 0


def command_init_project(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)

    project_root = Path(args.project_root).resolve()
    path = project_profile_path(project_root, registry)
    ensure_profile_write(path, args.force)
    project_name = project_root.name
    profile = (
        default_project_profile(project_name)
        if args.use_workspace_defaults
        else interactive_project_profile(registry, project_name)
    )
    profile_issues = validate_profile(
        profile,
        registry,
        expected_kind=PROFILE_KIND_PROJECT,
        base_preset=registry_defaults(registry)["default_preset"],
        origin="project profile",
    )
    if profile_issues:
        fail("project profile is invalid", details=profile_issues)
    write_json(path, profile)
    print(json.dumps({"project_profile": str(path), "profile": profile}, indent=2))
    return 0


def command_list(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    section = args.section
    if section == "skills":
        payload = sorted(registry["skills"].keys())
    elif section == "hosts":
        payload = sorted(registry["hosts"].keys())
    elif section == "models":
        payload = sorted(registry["models"].keys())
    elif section == "presets":
        payload = sorted(registry["presets"].keys())
    elif section == "skillpacks":
        payload = sorted(registry["skillpacks"].keys())
    elif section == "personas":
        payload = build_persona_catalog(registry) if args.detailed else sorted(registry["personas"].keys())
    elif section == "lanes":
        preset_name = args.preset or registry_defaults(registry)["default_preset"]
        if preset_name not in registry["presets"]:
            fail(f"unknown preset `{preset_name}`")
        payload = sorted(registry["presets"][preset_name]["lanes"].keys())
    else:
        fail(f"unknown section `{section}`")
    if section == "personas" and args.detailed:
        print(json.dumps(payload, indent=2))
    else:
        print(json.dumps({section: payload}, indent=2))
    return 0


def command_preset(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    presets = registry["presets"]
    if args.preset not in presets:
        fail(f"unknown preset `{args.preset}`")
    preset = presets[args.preset]
    if args.lane:
        lane = preset["lanes"].get(args.lane)
        if lane is None:
            fail(f"preset `{args.preset}` has no lane `{args.lane}`")
        payload = {"product": "RelayKit", "preset": args.preset, "lane": args.lane, "config": lane}
    else:
        payload = {"product": "RelayKit", "preset": args.preset, **preset}
    print(json.dumps(payload, indent=2))
    return 0


def command_stack(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)

    workspace_path, workspace_profile = resolve_workspace_profile_for_stack(args, registry)
    project_path, project_profile = resolve_project_profile_for_stack(args, registry)

    if workspace_profile is not None:
        workspace_issues = validate_profile(
            workspace_profile,
            registry,
            expected_kind=PROFILE_KIND_WORKSPACE,
            base_preset=registry_defaults(registry)["default_preset"],
            origin=f"workspace profile `{workspace_path}`",
        )
        if workspace_issues:
            fail("workspace profile is invalid", details=workspace_issues)

    if project_profile is not None:
        project_issues = validate_profile(
            project_profile,
            registry,
            expected_kind=PROFILE_KIND_PROJECT,
            base_preset=project_base_preset(
                registry,
                workspace_profile=workspace_profile,
                project_profile=project_profile,
            ),
            origin=f"project profile `{project_path}`",
        )
        if project_issues:
            fail("project profile is invalid", details=project_issues)

    payload = build_stack(
        registry,
        lane_name=args.lane,
        skill_name=args.skill,
        host_name=args.host,
        model_name=args.model,
        role=args.role,
        reasoning_effort=args.reasoning_effort,
        packet=args.packet,
        repo_guide=args.repo_guide,
        preset=args.preset,
        workspace_profile=workspace_profile,
        project_profile=project_profile,
        cli_personas=args.persona or [],
        extra_persona_paths=args.persona_path or [],
    )
    payload["workspace_profile"] = str(workspace_path) if workspace_path else None
    payload["project_profile"] = str(project_path) if project_path else None
    payload["persona_mode"] = registry_defaults(registry)["persona_mode"]
    print_payload(payload, args.format)
    return 0


def command_host_status(args: argparse.Namespace) -> int:
    hosts = resolved_onboarding_hosts(args.host, current_host=args.current_host, all_hosts=bool(getattr(args, "all_hosts", False)))
    hosts_payload = [host_onboarding_status(host_name) for host_name in hosts]
    payload = {
        "product": PRODUCT_NAME,
        "server": mcp_server_spec(),
        "hosts": hosts_payload,
        "actions": build_onboarding_actions(hosts_payload),
    }
    print(json.dumps(payload, indent=2))
    needs_onboarding = payload["actions"]["needs_onboarding"]
    return 2 if needs_onboarding else 0


def command_bootstrap_host(args: argparse.Namespace) -> int:
    hosts = resolved_onboarding_hosts(args.host, current_host=args.current_host, all_hosts=bool(getattr(args, "all_hosts", False)))
    payload = {
        "product": PRODUCT_NAME,
        "server": mcp_server_spec(),
        "results": [
            bootstrap_host(
                host_name,
                install_skills=not args.skip_skills,
                configure_mcp=not args.skip_mcp,
                force=args.force,
                dry_run=bool(args.dry_run),
            )
            for host_name in hosts
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0


def build_setup_payload(
    *,
    hosts: list[str],
    workspace_root: Path | None,
    skip_skills: bool,
    skip_mcp: bool,
    skip_smoke: bool,
    force: bool,
    dry_run: bool,
) -> dict[str, object]:
    before_hosts = [host_onboarding_status(host_name) for host_name in hosts]
    payload: dict[str, object] = {
        "product": PRODUCT_NAME,
        "server": mcp_server_spec(),
        "host_status_before": {
            "hosts": before_hosts,
            "actions": build_onboarding_actions(before_hosts),
        },
        "bootstrap": {
            "dry_run": dry_run,
            "results": [
                bootstrap_host(
                    host_name,
                    install_skills=not skip_skills,
                    configure_mcp=not skip_mcp,
                    force=force,
                    dry_run=dry_run,
                )
                for host_name in hosts
            ],
        },
        "restart_hints": {host_name: host_restart_hint(host_name) for host_name in hosts},
        "next_prompts": {
            host_name: first_use_prompt(
                host_name,
                workspace_root if workspace_root else smoke_workspace_root(host_name),
            )
            for host_name in hosts
        },
    }
    if not dry_run and workspace_root is not None:
        execution_context_paths = persist_execution_context(
            load_registry(),
            workspace_root=workspace_root,
            payload=setup_execution_context_payload(hosts=hosts, workspace_root=workspace_root),
            project_root=None,
        )
        if execution_context_paths:
            payload["execution_context_paths"] = execution_context_paths
    if not dry_run and not skip_smoke:
        payload["smoke"] = {
            host_name: run_smoke_flow(
                workspace_root if workspace_root else smoke_workspace_root(host_name),
                host_name=host_name,
                force_workspace_init=force,
            )
            for host_name in hosts
        }
    return payload


def command_setup(args: argparse.Namespace) -> int:
    hosts = resolved_setup_hosts(args.host, current_host=args.current_host, all_hosts=bool(getattr(args, "all_hosts", False)))
    payload = build_setup_payload(
        hosts=hosts,
        workspace_root=Path(args.workspace_root).resolve() if args.workspace_root else None,
        skip_skills=bool(args.skip_skills),
        skip_mcp=bool(args.skip_mcp),
        skip_smoke=bool(args.skip_smoke),
        force=bool(args.force),
        dry_run=bool(args.dry_run),
    )
    print_support_payload(payload, format_name=getattr(args, "format", "auto"), command_name="setup")
    return 0


def command_prepare_git(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    _workspace_root, workspace_profile, _project_root, project_profile, storage_root = resolve_task_context(args, registry)
    payload = taskflow.prepare_git(
        registry,
        root=storage_root,
        task_id=args.task_id,
        workspace_profile=workspace_profile,
        project_profile=project_profile,
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(payload, indent=2))
    return 0


def command_uninstall_host(args: argparse.Namespace) -> int:
    hosts = resolved_onboarding_hosts(args.host, current_host=args.current_host, all_hosts=bool(getattr(args, "all_hosts", False)))
    payload = {
        "product": PRODUCT_NAME,
        "server": mcp_server_spec(),
        "results": [
            uninstall_host(
                host_name,
                remove_skills=not args.skip_skills,
                remove_mcp=not args.skip_mcp,
                dry_run=bool(args.dry_run),
            )
            for host_name in hosts
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0


def command_acknowledge_host(args: argparse.Namespace) -> int:
    hosts = resolved_onboarding_hosts(args.host, current_host=args.current_host, all_hosts=bool(getattr(args, "all_hosts", False)))
    state = load_onboarding_state()
    for host_name in hosts:
        entry = host_state(state, host_name)
        entry["dismissed"] = True
    save_onboarding_state(state)
    print(json.dumps({"product": PRODUCT_NAME, "acknowledged_hosts": hosts}, indent=2))
    return 0


def command_install_self(args: argparse.Namespace) -> int:
    payload = build_install_self_payload(
        venv_dir=Path(args.venv).expanduser().resolve(),
        requested_hosts=args.host,
        current_host=bool(args.current_host),
        skip_skills=bool(args.skip_skills),
        skip_mcp=bool(args.skip_mcp),
        force=bool(args.force),
    )
    print(json.dumps(payload, indent=2))
    return 0


def build_install_self_payload(
    *,
    venv_dir: Path,
    requested_hosts: list[str] | None,
    current_host: bool,
    skip_skills: bool,
    skip_mcp: bool,
    force: bool,
) -> dict[str, object]:
    created = False
    if not venv_dir.exists():
        import venv

        venv.create(str(venv_dir), with_pip=True)
        created = True
    python = venv_dir / "bin" / "python"
    import subprocess

    install_steps: list[dict[str, object]] = []

    def run_install(command: list[str]) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        install_steps.append(
            {
                "command": command,
                "returncode": completed.returncode,
                "stdout_tail": completed.stdout[-500:],
                "stderr_tail": completed.stderr[-500:],
            }
        )
        return completed

    install_result = run_install([str(python), "-m", "pip", "install", "-e", str(SOURCE_ROOT)])
    if install_result.returncode != 0:
        run_install([str(python), "-m", "pip", "install", "--upgrade", "pip"])
        install_result = run_install([str(python), "-m", "pip", "install", "-e", str(SOURCE_ROOT)])
        if install_result.returncode != 0:
            fail("install-self failed", details=[json.dumps(install_steps[-1], indent=2)])
    payload = {
        "product": PRODUCT_NAME,
        "venv": str(venv_dir),
        "created": created,
        "install_steps": install_steps,
        "next_steps": [
            f"source {venv_dir}/bin/activate",
            f"{venv_dir}/bin/relaykit --version",
        ],
    }
    if requested_hosts or current_host:
        hosts = onboarding_hosts(requested_hosts, current_host=current_host)
        payload["host_install"] = [
            bootstrap_host(
                host_name,
                install_skills=not skip_skills,
                configure_mcp=not skip_mcp,
                force=force,
                dry_run=False,
            )
            for host_name in hosts
        ]
    return payload


def build_smoke_payload(
    *,
    hosts: list[str],
    workspace_root: Path | None,
    force: bool,
) -> dict[str, object]:
    return {
        "product": PRODUCT_NAME,
        "smoke": {
            host_name: run_smoke_flow(
                workspace_root if workspace_root else smoke_workspace_root(host_name),
                host_name=host_name,
                force_workspace_init=force,
            )
            for host_name in hosts
        },
        "next_prompts": {
            host_name: first_use_prompt(
                host_name,
                workspace_root if workspace_root else smoke_workspace_root(host_name),
            )
            for host_name in hosts
        },
    }


def command_smoke(args: argparse.Namespace) -> int:
    hosts = resolved_setup_hosts(args.host, current_host=args.current_host, all_hosts=bool(getattr(args, "all_hosts", False)))
    payload = build_smoke_payload(
        hosts=hosts,
        workspace_root=Path(args.workspace_root).resolve() if args.workspace_root else None,
        force=bool(args.force),
    )
    print_support_payload(payload, format_name=getattr(args, "format", "auto"), command_name="smoke")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    registry = load_registry()
    workspace_root = Path(args.workspace_root).resolve() if args.workspace_root else Path.cwd().resolve()
    project_root = Path(args.project_root).resolve() if args.project_root else None
    payload = build_doctor_payload(
        workspace_root=workspace_root,
        project_root=project_root,
        workspace_profile_override=Path(args.workspace_profile) if args.workspace_profile else None,
        project_profile_override=Path(args.project_profile) if args.project_profile else None,
        requested_hosts=args.host,
        current_host=args.current_host,
    )
    execution_context_paths = persist_execution_context(
        registry,
        workspace_root=workspace_root,
        project_root=project_root,
        payload=doctor_execution_context_payload(
            workspace_root=workspace_root,
            project_root=project_root,
        ),
    )
    if execution_context_paths:
        payload["execution_context_paths"] = execution_context_paths
    print(json.dumps(payload, indent=2))
    has_blockers = bool(
        payload["registry"]["issues"]
        or payload["workspace_profile"]["status"] == "invalid"
        or payload["project_profile"]["status"] == "invalid"
    )
    return 1 if has_blockers else 0


def resolve_task_context(
    args: argparse.Namespace,
    registry: dict,
) -> tuple[Path | None, dict | None, Path | None, dict | None, Path]:
    workspace_root = Path(args.workspace_root).resolve() if getattr(args, "workspace_root", None) else Path.cwd().resolve()
    project_root = Path(args.project_root).resolve() if getattr(args, "project_root", None) else None

    workspace_path = (
        Path(args.workspace_profile).resolve()
        if getattr(args, "workspace_profile", None)
        else workspace_profile_path(workspace_root, registry)
    )
    workspace_profile = load_optional_profile(workspace_path, PROFILE_KIND_WORKSPACE)[1] if workspace_path.exists() else None
    if workspace_profile is not None:
        issues = validate_profile(
            workspace_profile,
            registry,
            expected_kind=PROFILE_KIND_WORKSPACE,
            base_preset=registry_defaults(registry)["default_preset"],
            origin=f"workspace profile `{workspace_path}`",
        )
        if issues:
            fail("workspace profile is invalid", details=issues)

    project_profile = None
    if getattr(args, "project_profile", None):
        project_path = Path(args.project_profile).resolve()
        project_profile = load_optional_profile(project_path, PROFILE_KIND_PROJECT)[1]
    elif project_root is not None:
        project_path = project_profile_path(project_root, registry)
        if project_path.exists():
            project_profile = load_optional_profile(project_path, PROFILE_KIND_PROJECT)[1]
    else:
        project_path = None

    if project_profile is not None:
        issues = validate_profile(
            project_profile,
            registry,
            expected_kind=PROFILE_KIND_PROJECT,
            base_preset=project_base_preset(
                registry,
                workspace_profile=workspace_profile,
                project_profile=project_profile,
            ),
            origin="project profile",
        )
        if issues:
            fail("project profile is invalid", details=issues)

    storage_root = taskflow.root_for_task(workspace_root, project_root, getattr(args, "task_scope", None))
    return workspace_root, workspace_profile, project_root, project_profile, storage_root


def _resolve_output_format(format_name: str) -> str:
    if format_name == "auto":
        return "human" if sys.stdout.isatty() else "json"
    return format_name


def _append_line(lines: list[str], label: str, value: object) -> None:
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    lines.append(f"{label}: {value}")


def _human_task_part_lines(parts: list[dict]) -> list[str]:
    lines: list[str] = []
    for part in parts:
        assignment = part.get("assignment", {})
        header = f"- {part.get('name', part.get('part_id', 'part'))}: {assignment.get('host', '?')} / {assignment.get('model', '?')}"
        role = assignment.get("role")
        if role:
            header += f" / {role}"
        lines.append(header)
        objective = part.get("objective")
        if objective:
            lines.append(f"  objective: {objective}")
    return lines


def _human_render_recommendation(payload: dict) -> str:
    recommendation = payload["recommendation"]
    setup = recommendation.get("setup", {})
    confidence = recommendation.get("confidence", {})
    delivery_mode = recommendation.get("delivery_mode", {})
    verdict = delivery_mode.get("verdict")
    lines = [
        f"Task {payload.get('task_id')}",
    ]
    if verdict:
        _append_line(lines, "Verdict", verdict)
    _append_line(lines, "Recommendation", f"{setup.get('coordination')} + {setup.get('continuity')}")
    _append_line(lines, "Summary", recommendation.get("task_summary"))
    _append_line(lines, "Archetype", recommendation.get("archetype", {}).get("value"))
    _append_line(lines, "Confidence", confidence.get("level"))
    _append_line(lines, "Main uncertainty", confidence.get("main_uncertainty"))
    why_enough = setup.get("why_this_is_enough")
    why_not_simpler = setup.get("why_not_simpler")
    if why_enough:
        _append_line(lines, "Why this is enough", why_enough)
    if why_not_simpler:
        _append_line(lines, "Why not simpler", why_not_simpler)
    if delivery_mode.get("recommended") == "manual":
        _append_line(lines, "Delivery", "manual recommended")
        _append_line(lines, "Reason", delivery_mode.get("reason"))
    research = recommendation.get("research", {})
    if research.get("summary") and research.get("mode") != "none":
        _append_line(lines, "Research note", research.get("summary"))
    source_issues = recommendation.get("source_issues") or {}
    if source_issues.get("count"):
        _append_line(lines, "Source issues", f"{source_issues.get('open_count', 0)} open / {source_issues.get('count')} total")
    parts = recommendation.get("task_parts", [])
    if parts:
        lines.append("Task parts:")
        lines.extend(_human_task_part_lines(parts))
    required_action = payload.get("required_action") or {}
    if required_action:
        _append_line(lines, "Required action", required_action.get("message"))
        _append_line(lines, "Suggested command", required_action.get("suggested_command"))
    contract = payload.get("orchestration_contract") or []
    if contract:
        lines.append("Orchestration contract:")
        for item in contract:
            lines.append(f"- {item}")
    _append_line(lines, "Next step", recommendation.get("next_step"))
    _append_line(lines, "Confirm prompt", recommendation.get("confirm_prompt"))
    _append_line(lines, "State", payload.get("state_path"))
    return "\n".join(lines)


def _human_render_clarification(payload: dict) -> str:
    question = payload.get("question", {})
    lines = [f"Task {payload.get('task_id')}", "Clarification needed:"]
    _append_line(lines, "Question", question.get("prompt"))
    _append_line(lines, "Question id", question.get("id"))
    _append_line(lines, "Required", "yes" if question.get("required") else "no")
    _append_line(lines, "Asked", f"{payload.get('asked_count')}/{payload.get('question_cap')}")
    _append_line(lines, "State", payload.get("state_path"))
    return "\n".join(lines)


def _human_render_show_task(payload: dict) -> str:
    lines = [f"Task {payload.get('task_id')}"]
    _append_line(lines, "Status", payload.get("status"))
    _append_line(lines, "Scope", payload.get("scope"))
    _append_line(lines, "Task", payload.get("task"))
    recommendation = payload.get("recommendation") or {}
    setup = recommendation.get("setup") or {}
    if setup:
        _append_line(lines, "Setup", f"{setup.get('coordination')} + {setup.get('continuity')}")
    continuation = payload.get("continuation") or {}
    _append_line(lines, "Next best action", continuation.get("next_best_action"))
    _append_line(lines, "Safe stop point", continuation.get("safe_stop_point"))
    required_action = payload.get("required_action") or {}
    if required_action:
        _append_line(lines, "Required action", required_action.get("message"))
        _append_line(lines, "Suggested command", required_action.get("suggested_command"))
    parts = recommendation.get("task_parts") or payload.get("task_parts") or []
    if parts:
        lines.append("Task parts:")
        lines.extend(_human_task_part_lines(parts))
    drift = payload.get("drift_warnings") or []
    if drift:
        lines.append("Drift warnings:")
        for item in drift:
            lines.append(f"- {item}")
    guidance = payload.get("orchestration_guidance") or []
    if guidance:
        lines.append("Orchestration guidance:")
        for item in guidance:
            lines.append(f"- {item}")
    timeline = payload.get("timeline") or []
    if timeline:
        lines.append("Timeline:")
        for item in timeline[:5]:
            marker = " now" if item.get("is_now") else ""
            lines.append(f"- {item.get('label')}: {item.get('summary')}{marker}")
    return "\n".join(lines)


def _human_render_list_tasks(payload: dict) -> str:
    lines = [f"Tasks: {payload.get('count', 0)}"]
    for task in payload.get("tasks", []):
        lines.append(f"- {task.get('task_id')}: {task.get('status')} | {task.get('task')}")
    return "\n".join(lines)


def _human_render_confirm(payload: dict) -> str:
    lines = [f"Task {payload.get('task_id')}", "Task confirmed."]
    plan = payload.get("confirmed_plan") or payload.get("phase") or {}
    setup = plan.get("setup") or {}
    if setup:
        delivery_mode = plan.get("delivery_mode") or {}
        verdict = delivery_mode.get("verdict")
        if verdict:
            _append_line(lines, "Verdict", verdict)
        _append_line(lines, "Setup", f"{setup.get('coordination')} + {setup.get('continuity')}")
    parts = plan.get("task_parts") or []
    if parts:
        lines.append("Task parts:")
        lines.extend(_human_task_part_lines(parts))
    launch_bundle = payload.get("launch_bundle") or []
    if launch_bundle:
        lines.append(f"Launch bundle: {len(launch_bundle)} part(s) ready.")
    continuation = payload.get("continuation") or {}
    _append_line(lines, "Next best action", continuation.get("next_best_action"))
    _append_line(lines, "Safe stop point", continuation.get("safe_stop_point"))
    required_action = payload.get("required_action") or {}
    if required_action:
        _append_line(lines, "Required action", required_action.get("message"))
        _append_line(lines, "Suggested command", required_action.get("suggested_command"))
    contract = payload.get("orchestration_contract") or []
    if contract:
        lines.append("Orchestration contract:")
        for item in contract:
            lines.append(f"- {item}")
    return "\n".join(lines)


def _human_render_checkpoint(payload: dict) -> str:
    lines = [f"Task {payload.get('task_id')}", "Checkpoint recorded."]
    _append_line(lines, "Recommended outcome", payload.get("recommended_outcome"))
    _append_line(lines, "Recommended action", payload.get("recommended_action"))
    _append_line(lines, "Notes", payload.get("notes"))
    if payload.get("report_count") is not None:
        _append_line(lines, "Reports", payload.get("report_count"))
    reports = payload.get("reports") or []
    if reports:
        lines.append("Part outcomes:")
        for report in reports:
            lines.append(f"- {report.get('part_id')}: {report.get('recommended_outcome')}")
    required_action = payload.get("required_action") or {}
    if required_action:
        _append_line(lines, "Required action", required_action.get("message"))
        _append_line(lines, "Suggested command", required_action.get("suggested_command"))
    warnings = payload.get("phase_warnings") or []
    if warnings:
        lines.append("Phase warnings:")
        for item in warnings:
            lines.append(f"- {item}")
    return "\n".join(lines)


def _human_render_advance(payload: dict) -> str:
    lines = [f"Task {payload.get('task_id')}", "Task advanced."]
    phase = payload.get("phase") or {}
    setup = phase.get("setup") or {}
    if setup:
        _append_line(lines, "New setup", f"{setup.get('coordination')} + {setup.get('continuity')}")
    parts = phase.get("task_parts") or []
    if parts:
        lines.append("Current task parts:")
        lines.extend(_human_task_part_lines(parts))
    _append_line(lines, "Applied action", payload.get("applied_action"))
    _append_line(lines, "Reason", payload.get("change_reason"))
    required_action = payload.get("required_action") or {}
    if required_action:
        _append_line(lines, "Required action", required_action.get("message"))
        _append_line(lines, "Suggested command", required_action.get("suggested_command"))
    return "\n".join(lines)


def _human_render_resume(payload: dict) -> str:
    lines = [f"Task {payload.get('task_id')}", "Resume summary."]
    _append_line(lines, "Status", payload.get("status"))
    _append_line(lines, "Resume scope", payload.get("resume_scope"))
    remaining = payload.get("remaining_part_ids") or []
    if remaining:
        _append_line(lines, "Remaining parts", ", ".join(remaining))
    continuation = payload.get("continuation") or {}
    _append_line(lines, "Next best action", continuation.get("next_best_action"))
    required_action = payload.get("required_action") or {}
    if required_action:
        _append_line(lines, "Required action", required_action.get("message"))
        _append_line(lines, "Suggested command", required_action.get("suggested_command"))
    launch_bundle = payload.get("launch_bundle") or []
    if launch_bundle:
        lines.append(f"Launch bundle: {len(launch_bundle)} part(s) ready.")
    drift = payload.get("drift_warnings") or []
    if drift:
        lines.append("Drift warnings:")
        for item in drift:
            lines.append(f"- {item}")
    guidance = payload.get("orchestration_guidance") or []
    if guidance:
        lines.append("Orchestration guidance:")
        for item in guidance:
            lines.append(f"- {item}")
    return "\n".join(lines)


def _human_render_consolidation(payload: dict) -> str:
    lines = [f"Task {payload.get('task_id')}", "Consolidation packet ready."]
    _append_line(lines, "Phase", payload.get("phase_id"))
    _append_line(lines, "Reports", payload.get("report_count"))
    _append_line(lines, "Builder report included", "yes" if payload.get("contains_builder_report") else "no")
    _append_line(lines, "Reviewer report included", "yes" if payload.get("contains_reviewer_report") else "no")
    return "\n".join(lines)


def _human_render_reflection(payload: dict) -> str:
    lines = [f"Task {payload.get('task_id')}", "Reflection recorded."]
    reflection = payload.get("reflection") or {}
    _append_line(lines, "Split worth it", reflection.get("split_worth_it"))
    _append_line(lines, "Tool fit", reflection.get("tool_fit"))
    _append_line(lines, "Simpler better", reflection.get("simpler_better"))
    _append_line(lines, "Applied", "yes" if payload.get("applied") else "no")
    learning = payload.get("learning_summary") or {}
    _append_line(lines, "Lookback count", learning.get("lookback_count"))
    issue_updates = payload.get("source_artifact_updates") or {}
    if issue_updates.get("updated_count"):
        _append_line(lines, "Source issues updated", issue_updates.get("updated_count"))
        _append_line(lines, "Issue state", issue_updates.get("state_path"))
    return "\n".join(lines)


def _human_render_setup(payload: dict) -> str:
    lines = [f"{payload.get('product', PRODUCT_NAME)} setup complete."]
    results = ((payload.get("bootstrap") or {}).get("results")) or []
    for result in results:
        host_name = result.get("host")
        host_summary: list[str] = ["wiring applied"]
        skills = result.get("skills") or {}
        mcp = result.get("mcp") or {}
        host_summary.append(f"skills {'installed' if skills.get('configured') else 'not installed'}")
        host_summary.append(f"mcp {'configured' if mcp.get('configured') else 'not configured'}")
        smoke = (payload.get("smoke") or {}).get(host_name)
        if smoke is not None:
            smoke_results = smoke.get("results") or []
            succeeded = all(step.get("status") == "succeeded" for step in smoke_results)
            host_summary.append(f"smoke {'passed' if succeeded else 'needs review'}")
        lines.append(f"- {host_name}: {', '.join(host_summary)}")
    restart_hints = payload.get("restart_hints") or {}
    for host_name, hint in restart_hints.items():
        _append_line(lines, f"{host_name} restart", hint)
    lines.append("Next: use RelayKit MCP tools directly in your host.")
    if not payload.get("smoke"):
        lines.append("Optional: run `relaykit smoke --host <host>` when you want a full lifecycle check.")
    return "\n".join(lines)


def _human_render_smoke(payload: dict) -> str:
    lines = [f"{payload.get('product', PRODUCT_NAME)} smoke complete."]
    smoke = payload.get("smoke") or {}
    for host_name, smoke_payload in smoke.items():
        smoke_results = smoke_payload.get("results") or []
        succeeded = all(step.get("status") == "succeeded" for step in smoke_results)
        lines.append(f"- {host_name}: {'passed' if succeeded else 'needs review'}")
        _append_line(lines, "  task_id", smoke_payload.get("task_id"))
        reflection = smoke_payload.get("reflection") or {}
        summary = reflection.get("reflection") or {}
        selected_hosts = summary.get("selected_hosts") or []
        if selected_hosts:
            _append_line(lines, "  selected hosts", ", ".join(selected_hosts))
    next_prompts = payload.get("next_prompts") or {}
    for host_name, prompt in next_prompts.items():
        lines.append(f"{host_name} next prompt:")
        lines.append(prompt)
    return "\n".join(lines)


def render_taskflow_payload(payload: dict, *, command_name: str) -> str:
    if command_name == "setup":
        return _human_render_setup(payload)
    if command_name == "smoke":
        return _human_render_smoke(payload)
    if command_name in {"start-task", "answer-task"}:
        if payload.get("stage") == "clarification":
            return _human_render_clarification(payload)
        if payload.get("stage") == "recommendation":
            return _human_render_recommendation(payload)
    if command_name == "show-task":
        return _human_render_show_task(payload)
    if command_name == "list-tasks":
        return _human_render_list_tasks(payload)
    if command_name == "confirm-task":
        return _human_render_confirm(payload)
    if command_name in {"checkpoint-task", "checkpoint-phase"}:
        return _human_render_checkpoint(payload)
    if command_name == "advance-task":
        return _human_render_advance(payload)
    if command_name in {"resume-task", "resume-handoff"}:
        return _human_render_resume(payload)
    if command_name == "render-consolidation-packet":
        return _human_render_consolidation(payload)
    if command_name == "reflect-task":
        return _human_render_reflection(payload)
    return json.dumps(payload, indent=2)


def _run_input(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        fail("interactive input ended before RelayKit could finish the run flow")


def _run_print(payload: dict, *, command_name: str) -> None:
    print(render_taskflow_payload(payload, command_name=command_name))
    print("")


def command_run(args: argparse.Namespace) -> int:
    if not sys.stdin.isatty() and not args.task:
        fail("relaykit run needs --task when stdin is not interactive")
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    workspace_root, workspace_profile, project_root, project_profile, storage_root = resolve_task_context(args, registry)
    task_text = args.task or _run_input("Task: ").strip()
    if not task_text:
        fail("task text is required")
    execution_context = load_task_execution_context(
        registry,
        workspace_root=workspace_root,
        project_root=project_root,
    )
    try:
        payload = taskflow.start_task(
            registry,
            workspace_root=workspace_root,
            project_root=project_root,
            workspace_profile=workspace_profile,
            project_profile=project_profile,
            task_text=task_text,
            task_scope=args.task_scope,
            allowed_hosts=args.allowed_host or None,
            skip_clarification=bool(args.skip_clarification),
            execution_context=execution_context,
        )
    except ValueError as error:
        message, details = taskflow.parse_failure(error)
        fail(message, details=details)
    while True:
        stage = payload.get("stage")
        if stage == "clarification":
            _run_print(payload, command_name="start-task")
            question = payload.get("question") or {}
            answer = _run_input("Answer (or /skip): ").strip()
            try:
                if answer == "/skip":
                    if question.get("required"):
                        print("This clarification is required before RelayKit can recommend a setup.\n")
                        continue
                    state = taskflow.load_task_state(payload["task_id"], storage_root, registry)
                    state["clarification"]["skipped"] = True
                    payload = taskflow.maybe_recommend(state, registry, workspace_profile, project_profile)
                    state_file, summary_file = taskflow.save_task_state(state, registry)
                    payload["state_path"] = str(state_file)
                    payload["summary_path"] = str(summary_file)
                else:
                    if not answer:
                        print("A required clarification needs an answer or /skip.\n")
                        continue
                    payload = taskflow.answer_task(
                        registry,
                        root=storage_root,
                        task_id=payload["task_id"],
                        answer=answer,
                        question_id=question.get("id"),
                        workspace_profile=workspace_profile,
                        project_profile=project_profile,
                    )
            except ValueError as error:
                message, details = taskflow.parse_failure(error)
                fail(message, details=details)
            continue
        if stage == "recommendation":
            _run_print(payload, command_name="start-task")
            delivery_mode = (payload.get("recommendation") or {}).get("delivery_mode") or {}
            if args.accept:
                choice = "yes"
            else:
                choice = _run_input("Accept this setup? [Y/n/change/quit]: ").strip()
            lowered = choice.lower()
            if lowered in {"", "y", "yes"}:
                force_protocol = bool(args.force_protocol)
                if delivery_mode.get("recommended") == "manual" and not force_protocol:
                    override = _run_input("RelayKit recommends manual here. Force protocol anyway? [y/N]: ").strip().lower()
                    if override not in {"y", "yes"}:
                        print("Run ended without entering RelayKit protocol.")
                        return 0
                    force_protocol = True
                try:
                    payload = taskflow.confirm_task(
                        registry,
                        root=storage_root,
                        task_id=payload["task_id"],
                        accept=True,
                        change_text=None,
                        workspace_profile=workspace_profile,
                        project_profile=project_profile,
                        force_protocol=force_protocol,
                    )
                except ValueError as error:
                    message, details = taskflow.parse_failure(error)
                    fail(message, details=details)
                _run_print(payload, command_name="confirm-task")
                return 0
            if lowered in {"q", "quit", "no", "n"}:
                print("Run ended without confirming the setup.")
                return 0
            try:
                payload = taskflow.confirm_task(
                    registry,
                    root=storage_root,
                    task_id=payload["task_id"],
                    accept=False,
                    change_text=choice,
                    workspace_profile=workspace_profile,
                    project_profile=project_profile,
                    force_protocol=bool(args.force_protocol),
                )
            except ValueError as error:
                message, details = taskflow.parse_failure(error)
                fail(message, details=details)
            continue
        if stage == "confirmed":
            _run_print(payload, command_name="confirm-task")
            return 0
        print(json.dumps(payload, indent=2))
        return 0


def print_taskflow_payload(payload: dict, *, format_name: str, command_name: str) -> None:
    output_format = _resolve_output_format(format_name)
    if output_format == "human":
        print(render_taskflow_payload(payload, command_name=command_name))
        return
    print(json.dumps(payload, indent=2))


def print_support_payload(payload: dict, *, format_name: str, command_name: str) -> None:
    output_format = _resolve_output_format(format_name)
    if output_format == "human":
        print(render_taskflow_payload(payload, command_name=command_name))
        return
    print(json.dumps(payload, indent=2))


def command_start_task(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    workspace_root, workspace_profile, project_root, project_profile, _storage_root = resolve_task_context(args, registry)
    execution_context = load_task_execution_context(
        registry,
        workspace_root=workspace_root,
        project_root=project_root,
    )
    try:
        payload = taskflow.start_task(
            registry,
            workspace_root=workspace_root,
            project_root=project_root,
            workspace_profile=workspace_profile,
            project_profile=project_profile,
            task_text=args.task,
            task_scope=args.task_scope,
            allowed_hosts=args.allowed_host or None,
            skip_clarification=bool(args.skip_clarification),
            dry_run=bool(getattr(args, "dry_run", False)),
            execution_context=execution_context,
        )
    except ValueError as error:
        message, details = taskflow.parse_failure(error)
        fail(message, details=details)
    print_taskflow_payload(payload, format_name=args.format, command_name="start-task")
    return 0


def command_answer_task(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    workspace_root, workspace_profile, project_root, project_profile, storage_root = resolve_task_context(args, registry)
    try:
        if args.skip_clarification:
            state = taskflow.load_task_state(args.task_id, storage_root, registry)
            state["clarification"]["skipped"] = True
            payload = taskflow.maybe_recommend(state, registry, workspace_profile, project_profile)
            state_file, summary_file = taskflow.save_task_state(state, registry)
            payload["state_path"] = str(state_file)
            payload["summary_path"] = str(summary_file)
        else:
            if not args.answer:
                fail("answer-task requires --answer unless --skip-clarification is set")
            payload = taskflow.answer_task(
                registry,
                root=storage_root,
                task_id=args.task_id,
                answer=args.answer,
                question_id=args.question_id,
                workspace_profile=workspace_profile,
                project_profile=project_profile,
            )
    except ValueError as error:
        message, details = taskflow.parse_failure(error)
        fail(message, details=details)
    print_taskflow_payload(payload, format_name=args.format, command_name="answer-task")
    return 0


def command_show_task(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    _workspace_root, _workspace_profile, _project_root, _project_profile, storage_root = resolve_task_context(args, registry)
    try:
        payload = taskflow.inspect_task(registry, root=storage_root, task_id=args.task_id) if args.debug else taskflow.show_task(
            registry,
            root=storage_root,
            task_id=args.task_id,
        )
    except ValueError as error:
        message, details = taskflow.parse_failure(error)
        fail(message, details=details)
    print_taskflow_payload(payload, format_name=args.format, command_name="show-task")
    return 0


def command_list_tasks(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    _workspace_root, _workspace_profile, _project_root, _project_profile, storage_root = resolve_task_context(args, registry)
    try:
        payload = taskflow.list_tasks(
            registry,
            root=storage_root,
            status_filter=args.status,
        )
    except ValueError as error:
        message, details = taskflow.parse_failure(error)
        fail(message, details=details)
    print_taskflow_payload(payload, format_name=args.format, command_name="list-tasks")
    return 0


def command_confirm_task(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    workspace_root, workspace_profile, project_root, project_profile, storage_root = resolve_task_context(args, registry)
    try:
        payload = taskflow.confirm_task(
            registry,
            root=storage_root,
            task_id=args.task_id,
            accept=bool(args.accept),
            change_text=args.change,
            force_protocol=bool(args.force_protocol),
            workspace_profile=workspace_profile,
            project_profile=project_profile,
        )
    except ValueError as error:
        message, details = taskflow.parse_failure(error)
        fail(message, details=details)
    print_taskflow_payload(payload, format_name=args.format, command_name="confirm-task")
    return 0


def command_checkpoint_task(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    _workspace_root, _workspace_profile, _project_root, _project_profile, storage_root = resolve_task_context(args, registry)
    try:
        artifacts = None
        if args.artifacts:
            artifacts = json.loads(args.artifacts)
        payload = taskflow.checkpoint_task(
            registry,
            root=storage_root,
            task_id=args.task_id,
            outcome=args.outcome,
            notes=args.notes or "",
            artifacts=artifacts,
            part_id=args.part_id,
            report_markdown=args.report_markdown,
            verbosity=args.verbosity,
        )
    except ValueError as error:
        message, details = taskflow.parse_failure(error)
        fail(message, details=details)
    print_taskflow_payload(payload, format_name=args.format, command_name="checkpoint-task")
    return 0


def command_checkpoint_phase(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    _workspace_root, _workspace_profile, _project_root, _project_profile, storage_root = resolve_task_context(args, registry)
    try:
        reports = json.loads(args.reports)
        if not isinstance(reports, list):
            fail("checkpoint-phase requires --reports to decode to a JSON array")
        payload = taskflow.checkpoint_phase(
            registry,
            root=storage_root,
            task_id=args.task_id,
            phase_id=args.phase_id,
            reports=reports,
            verbosity=args.verbosity,
        )
    except ValueError as error:
        message, details = taskflow.parse_failure(error)
        fail(message, details=details)
    print_taskflow_payload(payload, format_name=args.format, command_name="checkpoint-phase")
    return 0


def command_advance_task(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    _workspace_root, workspace_profile, _project_root, project_profile, storage_root = resolve_task_context(args, registry)
    try:
        payload = taskflow.advance_task(
            registry,
            root=storage_root,
            task_id=args.task_id,
            action=args.action,
            change_reason=args.change_reason,
            notes=args.notes,
            change_text=args.change,
            workspace_profile=workspace_profile,
            project_profile=project_profile,
            verbosity=args.verbosity,
        )
    except ValueError as error:
        message, details = taskflow.parse_failure(error)
        fail(message, details=details)
    print_taskflow_payload(payload, format_name=args.format, command_name="advance-task")
    return 0


def command_resume_task(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    _workspace_root, _workspace_profile, _project_root, _project_profile, storage_root = resolve_task_context(args, registry)
    try:
        payload = taskflow.resume_task(
            registry,
            root=storage_root,
            task_id=args.task_id,
            verbosity=args.verbosity,
        )
    except ValueError as error:
        message, details = taskflow.parse_failure(error)
        fail(message, details=details)
    print_taskflow_payload(payload, format_name=args.format, command_name="resume-task")
    return 0


def command_resume_handoff(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    _workspace_root, _workspace_profile, _project_root, _project_profile, storage_root = resolve_task_context(args, registry)
    try:
        payload = taskflow.resume_handoff(
            registry,
            root=storage_root,
            task_id=args.task_id,
            part_id=args.part_id,
            verbosity=args.verbosity,
        )
    except ValueError as error:
        message, details = taskflow.parse_failure(error)
        fail(message, details=details)
    print_taskflow_payload(payload, format_name=args.format, command_name="resume-handoff")
    return 0


def command_render_task_part(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    _workspace_root, _workspace_profile, _project_root, _project_profile, storage_root = resolve_task_context(args, registry)
    try:
        payload = taskflow.render_task_part(
            registry,
            root=storage_root,
            task_id=args.task_id,
            part_id=args.part_id,
            verbosity=args.verbosity,
        )
    except ValueError as error:
        message, details = taskflow.parse_failure(error)
        fail(message, details=details)
    if args.format == "markdown":
        print(payload["markdown"], end="")
    else:
        print_taskflow_payload(payload, format_name=args.format, command_name="render-task-part")
    return 0


def command_render_consolidation_packet(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    _workspace_root, _workspace_profile, _project_root, _project_profile, storage_root = resolve_task_context(args, registry)
    try:
        payload = taskflow.render_consolidation_packet(
            registry,
            root=storage_root,
            task_id=args.task_id,
            phase_id=args.phase_id,
            verbosity=args.verbosity,
        )
    except ValueError as error:
        message, details = taskflow.parse_failure(error)
        fail(message, details=details)
    if args.format == "markdown":
        print(payload["markdown"], end="")
    else:
        print_taskflow_payload(payload, format_name=args.format, command_name="render-consolidation-packet")
    return 0


def command_reflect_task(args: argparse.Namespace) -> int:
    registry = load_registry()
    registry_issues = validate_registry(registry)
    if registry_issues:
        fail("registry validation failed", details=registry_issues)
    _workspace_root, _workspace_profile, _project_root, _project_profile, storage_root = resolve_task_context(args, registry)
    try:
        payload = taskflow.reflect_task(
            registry,
            root=storage_root,
            task_id=args.task_id,
            split_worth_it=args.split_worth_it,
            tool_fit=args.tool_fit,
            simpler_better=args.simpler_better,
            notes=args.notes,
            apply=bool(args.apply),
        )
    except ValueError as error:
        message, details = taskflow.parse_failure(error)
        fail(message, details=details)
    print_taskflow_payload(payload, format_name=args.format, command_name="reflect-task")
    return 0


def add_stack_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lane")
    parser.add_argument("--skill")
    parser.add_argument("--host")
    parser.add_argument("--model")
    parser.add_argument("--role")
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--preset")
    parser.add_argument("--persona", action="append")
    parser.add_argument("--persona-path", action="append")
    parser.add_argument("--packet")
    parser.add_argument("--repo-guide")
    parser.add_argument("--workspace-root")
    parser.add_argument("--project-root")
    parser.add_argument("--workspace-profile")
    parser.add_argument("--project-profile")
    parser.add_argument("--start-with-defaults", action="store_true")


def add_task_context_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace-root", default=".")
    parser.add_argument("--project-root")
    parser.add_argument("--workspace-profile")
    parser.add_argument("--project-profile")
    parser.add_argument("--task-scope", choices=["workspace", "project"])


def add_taskflow_format_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        choices=["auto", "json", "human"],
        default="auto",
        help="Render human-readable output in an interactive terminal, or JSON for scripts.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="RelayKit: coordinate multiple AI coding agents working in parallel, with human checkpoints between phases."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_start_task = subparsers.add_parser(
        "start-task",
        help="Start a RelayKit intake flow and return the next clarification question or recommendation.",
    )
    add_task_context_arguments(parser_start_task)
    add_taskflow_format_argument(parser_start_task)
    parser_start_task.add_argument("--task", required=True)
    parser_start_task.add_argument("--allowed-host", action="append")
    parser_start_task.add_argument("--skip-clarification", action="store_true")
    parser_start_task.add_argument("--dry-run", action="store_true", help="Preview the recommendation without persisting any state.")
    parser_start_task.set_defaults(func=command_start_task)

    parser_run = subparsers.add_parser(
        "run",
        help="Interactive RelayKit intake flow: clarify, recommend, and confirm in one guided shell session.",
    )
    add_task_context_arguments(parser_run)
    parser_run.add_argument("--task")
    parser_run.add_argument("--allowed-host", action="append")
    parser_run.add_argument("--skip-clarification", action="store_true")
    parser_run.add_argument("--accept", action="store_true", help="Auto-accept the first recommendation.")
    parser_run.add_argument("--force-protocol", action="store_true", help="Allow RelayKit protocol even when the recommendation says manual is better.")
    parser_run.set_defaults(func=command_run)

    parser_answer_task = subparsers.add_parser(
        "answer-task",
        help="Answer the current RelayKit clarification question.",
    )
    add_task_context_arguments(parser_answer_task)
    add_taskflow_format_argument(parser_answer_task)
    parser_answer_task.add_argument("--task-id", required=True)
    parser_answer_task.add_argument("--question-id")
    parser_answer_task.add_argument("--answer")
    parser_answer_task.add_argument("--skip-clarification", action="store_true")
    parser_answer_task.set_defaults(func=command_answer_task)

    parser_show_task = subparsers.add_parser(
        "show-task",
        help="Show the current state of a RelayKit task and lane-planning instance.",
    )
    add_task_context_arguments(parser_show_task)
    add_taskflow_format_argument(parser_show_task)
    parser_show_task.add_argument("--task-id", required=True)
    parser_show_task.add_argument("--debug", action="store_true")
    parser_show_task.set_defaults(func=command_show_task)

    parser_list_tasks = subparsers.add_parser(
        "list-tasks",
        help="List RelayKit tasks under the current workspace or project storage root.",
    )
    add_task_context_arguments(parser_list_tasks)
    add_taskflow_format_argument(parser_list_tasks)
    parser_list_tasks.add_argument("--status", action="append", help="Filter by one or more task statuses.")
    parser_list_tasks.set_defaults(func=command_list_tasks)

    parser_confirm_task = subparsers.add_parser(
        "confirm-task",
        help="Accept a RelayKit lane recommendation or request changes.",
    )
    add_task_context_arguments(parser_confirm_task)
    add_taskflow_format_argument(parser_confirm_task)
    parser_confirm_task.add_argument("--task-id", required=True)
    parser_confirm_task.add_argument("--accept", action="store_true")
    parser_confirm_task.add_argument("--change")
    parser_confirm_task.add_argument(
        "--force-protocol",
        action="store_true",
        help="Override a manual-recommended gate and continue with RelayKit anyway.",
    )
    parser_confirm_task.set_defaults(func=command_confirm_task)

    parser_checkpoint_task = subparsers.add_parser(
        "checkpoint-task",
        help="Record a checkpoint for a RelayKit task that is running across one or more lanes.",
    )
    add_task_context_arguments(parser_checkpoint_task)
    add_taskflow_format_argument(parser_checkpoint_task)
    parser_checkpoint_task.add_argument("--task-id", required=True)
    parser_checkpoint_task.add_argument("--part-id", help="The task part being checkpointed.")
    parser_checkpoint_task.add_argument("--outcome", choices=sorted(taskflow.CHECKPOINT_OUTCOMES))
    parser_checkpoint_task.add_argument("--notes")
    parser_checkpoint_task.add_argument("--artifacts", help="JSON object with findings, files_discovered, decisions, blockers.")
    parser_checkpoint_task.add_argument("--report-markdown", help="Optional markdown summary to preserve for later consolidation.")
    parser_checkpoint_task.add_argument("--verbosity", choices=sorted(taskflow.RESULT_VERBOSITIES), default="compact")
    parser_checkpoint_task.set_defaults(func=command_checkpoint_task)

    parser_checkpoint_phase = subparsers.add_parser(
        "checkpoint-phase",
        help="Record a batch checkpoint for multiple task parts in the current phase.",
    )
    add_task_context_arguments(parser_checkpoint_phase)
    add_taskflow_format_argument(parser_checkpoint_phase)
    parser_checkpoint_phase.add_argument("--task-id", required=True)
    parser_checkpoint_phase.add_argument("--phase-id")
    parser_checkpoint_phase.add_argument(
        "--reports",
        required=True,
        help="JSON array of report objects with part_id, optional outcome, notes, optional artifacts, and optional report_markdown.",
    )
    parser_checkpoint_phase.add_argument("--verbosity", choices=sorted(taskflow.RESULT_VERBOSITIES), default="compact")
    parser_checkpoint_phase.set_defaults(func=command_checkpoint_phase)

    parser_prepare_git = subparsers.add_parser(
        "prepare-git",
        help="Create git branches for the current task parts after explicit confirmation.",
    )
    add_task_context_arguments(parser_prepare_git)
    parser_prepare_git.add_argument("--task-id", required=True)
    parser_prepare_git.add_argument("--dry-run", action="store_true")
    parser_prepare_git.set_defaults(func=command_prepare_git)

    parser_advance_task = subparsers.add_parser(
        "advance-task",
        help="Apply the latest checkpoint action or an explicit setup/phase change.",
    )
    add_task_context_arguments(parser_advance_task)
    add_taskflow_format_argument(parser_advance_task)
    parser_advance_task.add_argument("--task-id", required=True)
    parser_advance_task.add_argument("--action", choices=sorted(taskflow.CHECKPOINT_ACTIONS))
    parser_advance_task.add_argument("--change-reason", choices=sorted(taskflow.CHANGE_REASONS))
    parser_advance_task.add_argument("--notes")
    parser_advance_task.add_argument("--change")
    parser_advance_task.add_argument("--verbosity", choices=sorted(taskflow.RESULT_VERBOSITIES), default="compact")
    parser_advance_task.set_defaults(func=command_advance_task)

    parser_resume_task = subparsers.add_parser(
        "resume-task",
        help="Resume a RelayKit task and get continuation guidance for the active lanes.",
    )
    add_task_context_arguments(parser_resume_task)
    add_taskflow_format_argument(parser_resume_task)
    parser_resume_task.add_argument("--task-id", required=True)
    parser_resume_task.add_argument("--verbosity", choices=sorted(taskflow.RESUME_VERBOSITIES), default="compact")
    parser_resume_task.set_defaults(func=command_resume_task)

    parser_resume_handoff = subparsers.add_parser(
        "resume-handoff",
        help="Return a ready-to-run handoff bundle for the remaining or requested task parts.",
    )
    add_task_context_arguments(parser_resume_handoff)
    add_taskflow_format_argument(parser_resume_handoff)
    parser_resume_handoff.add_argument("--task-id", required=True)
    parser_resume_handoff.add_argument("--part-id")
    parser_resume_handoff.add_argument("--verbosity", choices=sorted(taskflow.HANDOFF_VERBOSITIES), default="ultra-compact")
    parser_resume_handoff.set_defaults(func=command_resume_handoff)

    parser_render_task_part = subparsers.add_parser(
        "render-task-part",
        help="Render a launch bundle for one current task part.",
    )
    add_task_context_arguments(parser_render_task_part)
    parser_render_task_part.add_argument("--task-id", required=True)
    parser_render_task_part.add_argument("--part-id", required=True)
    parser_render_task_part.add_argument("--verbosity", choices=sorted(taskflow.HANDOFF_VERBOSITIES), default="compact")
    parser_render_task_part.add_argument("--format", choices=["json", "markdown"], default="json")
    parser_render_task_part.set_defaults(func=command_render_task_part)

    parser_render_consolidation = subparsers.add_parser(
        "render-consolidation-packet",
        help="Render a consolidation packet for the current or requested phase.",
    )
    add_task_context_arguments(parser_render_consolidation)
    parser_render_consolidation.add_argument("--task-id", required=True)
    parser_render_consolidation.add_argument("--phase-id")
    parser_render_consolidation.add_argument("--verbosity", choices=sorted(taskflow.HANDOFF_VERBOSITIES), default="compact")
    parser_render_consolidation.add_argument("--format", choices=["json", "markdown"], default="json")
    parser_render_consolidation.set_defaults(func=command_render_consolidation_packet)

    parser_reflect_task = subparsers.add_parser(
        "reflect-task",
        help="Propose or record a post-task RelayKit reflection about lane split, tool fit, and overhead.",
    )
    add_task_context_arguments(parser_reflect_task)
    add_taskflow_format_argument(parser_reflect_task)
    parser_reflect_task.add_argument("--task-id", required=True)
    parser_reflect_task.add_argument("--split-worth-it", choices=sorted(taskflow.REFLECTION_VALUES))
    parser_reflect_task.add_argument("--tool-fit", choices=sorted(taskflow.TOOL_FIT_VALUES))
    parser_reflect_task.add_argument("--simpler-better", choices=sorted(taskflow.REFLECTION_VALUES))
    parser_reflect_task.add_argument("--notes")
    parser_reflect_task.add_argument("--apply", action="store_true")
    parser_reflect_task.set_defaults(func=command_reflect_task)

    parser_list = subparsers.add_parser(
        "list", help="List registered skills, hosts, models, presets, personas, or advanced preset lanes."
    )
    parser_list.add_argument(
        "section",
        choices=["skills", "skillpacks", "hosts", "models", "presets", "personas", "lanes"],
    )
    parser_list.add_argument("--preset")
    parser_list.add_argument("--detailed", action="store_true")
    parser_list.set_defaults(func=command_list)

    parser_advanced = subparsers.add_parser(
        "advanced",
        help="Power-user lane, preset, and prompt-stack tools.",
    )
    advanced_subparsers = parser_advanced.add_subparsers(dest="advanced_command", required=True)

    parser_advanced_preset = advanced_subparsers.add_parser(
        "preset",
        help="Show one advanced preset or one lane inside a preset.",
    )
    parser_advanced_preset.add_argument("preset")
    parser_advanced_preset.add_argument("--lane")
    parser_advanced_preset.set_defaults(func=command_preset)

    parser_advanced_stack = advanced_subparsers.add_parser(
        "stack",
        help="Resolve the advanced RelayKit prompt stack for one lane or explicit skill/host/model tuple.",
    )
    add_stack_arguments(parser_advanced_stack)
    parser_advanced_stack.add_argument("--format", choices=["json", "markdown"], default="json")
    parser_advanced_stack.set_defaults(func=command_stack)

    parser_advanced_render = advanced_subparsers.add_parser(
        "render-prompt-stack",
        help="Render an advanced RelayKit prompt stack as Markdown.",
    )
    add_stack_arguments(parser_advanced_render)
    parser_advanced_render.set_defaults(func=lambda args: command_stack(argparse.Namespace(**{**vars(args), "format": "markdown"})))

    parser_preset = subparsers.add_parser("preset", help=argparse.SUPPRESS)
    parser_preset.add_argument("preset")
    parser_preset.add_argument("--lane")
    parser_preset.set_defaults(func=command_preset)

    parser_init_workspace = subparsers.add_parser(
        "init-workspace",
        help="Create a persistent workspace RelayKit profile with inventory and defaults.",
    )
    parser_init_workspace.add_argument("--workspace-root", default=".")
    parser_init_workspace.add_argument("--start-with-defaults", action="store_true")
    parser_init_workspace.add_argument("--force", action="store_true")
    parser_init_workspace.set_defaults(func=command_init_workspace)

    parser_guided_setup = subparsers.add_parser(
        "guided-setup",
        help="Create a workspace profile from guided first-run answers.",
    )
    parser_guided_setup.add_argument("--workspace-root", default=".")
    parser_guided_setup.add_argument("--host", action="append", required=True)
    parser_guided_setup.add_argument("--preset", required=True)
    parser_guided_setup.add_argument("--git-integration", action="store_true")
    parser_guided_setup.add_argument("--force", action="store_true")
    parser_guided_setup.set_defaults(func=command_guided_setup)

    parser_init_project = subparsers.add_parser(
        "init-project",
        help="Create an optional project RelayKit profile.",
    )
    parser_init_project.add_argument("--project-root", default=".")
    parser_init_project.add_argument("--use-workspace-defaults", action="store_true")
    parser_init_project.add_argument("--force", action="store_true")
    parser_init_project.set_defaults(func=command_init_project)

    parser_init_persona = subparsers.add_parser(
        "init-persona",
        help="Scaffold and optionally register a new repo-backed persona add-in.",
    )
    parser_init_persona.add_argument("--id")
    parser_init_persona.add_argument("--name", required=True)
    parser_init_persona.add_argument("--description", required=True)
    parser_init_persona.add_argument("--summary")
    parser_init_persona.add_argument("--kind", choices=sorted(PERSONA_KINDS), required=True)
    parser_init_persona.add_argument("--role", action="append", required=True)
    parser_init_persona.add_argument("--host", action="append")
    parser_init_persona.add_argument("--token-cost", choices=sorted(PERSONA_TOKEN_COSTS), default="low")
    parser_init_persona.add_argument("--tier", choices=sorted(PERSONA_TIERS), default="optional")
    parser_init_persona.add_argument("--source", default="local")
    parser_init_persona.add_argument("--conflicts-with", action="append")
    parser_init_persona.add_argument("--principle", action="append")
    parser_init_persona.add_argument("--load-order", type=int)
    parser_init_persona.add_argument("--dest")
    parser_init_persona.add_argument("--dry-run", action="store_true")
    parser_init_persona.add_argument("--force", action="store_true")
    parser_init_persona.set_defaults(func=command_init_persona)

    parser_stack = subparsers.add_parser("stack", help=argparse.SUPPRESS)
    add_stack_arguments(parser_stack)
    parser_stack.add_argument("--format", choices=["json", "markdown"], default="json")
    parser_stack.set_defaults(func=command_stack)

    parser_render = subparsers.add_parser("render-prompt-stack", help=argparse.SUPPRESS)
    add_stack_arguments(parser_render)
    parser_render.set_defaults(func=lambda args: command_stack(argparse.Namespace(**{**vars(args), "format": "markdown"})))

    parser_host_status = subparsers.add_parser(
        "host-status",
        help="Report whether a host is ready for RelayKit and return onboarding actions.",
    )
    parser_host_status.add_argument("--host", action="append")
    parser_host_status.add_argument(
        "--all-hosts",
        action="store_true",
        help=f"Target all supported hosts: {', '.join(SUPPORTED_ONBOARDING_HOSTS)}.",
    )
    parser_host_status.add_argument(
        "--current-host",
        action="store_true",
        help="Auto-detect the current host (Codex today, or use RELAYKIT_HOST to override).",
    )
    parser_host_status.set_defaults(func=command_host_status)

    parser_bootstrap_host = subparsers.add_parser(
        "bootstrap-host",
        help="Install RelayKit skills and configure wiring for one or more hosts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Install RelayKit-managed skills and host wiring. "
            f"Supported hosts: {', '.join(SUPPORTED_ONBOARDING_HOSTS)}. "
            f"Auto skill install is available for: {', '.join(SUPPORTED_SKILL_AUTO_HOSTS)}. "
            f"Auto MCP wiring is available for: {', '.join(SUPPORTED_MCP_AUTO_HOSTS)}."
        ),
        epilog=(
            "Examples:\n"
            "  relaykit bootstrap-host --current-host\n"
            "  relaykit bootstrap-host --host codex --dry-run\n"
            "  relaykit bootstrap-host --host codex --host antigravity --force"
        ),
    )
    parser_bootstrap_host.add_argument("--host", action="append")
    parser_bootstrap_host.add_argument(
        "--all-hosts",
        action="store_true",
        help=f"Target all supported hosts: {', '.join(SUPPORTED_ONBOARDING_HOSTS)}.",
    )
    parser_bootstrap_host.add_argument(
        "--current-host",
        action="store_true",
        help="Auto-detect the current host (Codex today, or use RELAYKIT_HOST to override).",
    )
    parser_bootstrap_host.add_argument("--skip-skills", action="store_true")
    parser_bootstrap_host.add_argument("--skip-mcp", action="store_true")
    parser_bootstrap_host.add_argument("--dry-run", action="store_true")
    parser_bootstrap_host.add_argument("--force", action="store_true")
    parser_bootstrap_host.set_defaults(func=command_bootstrap_host)

    parser_setup = subparsers.add_parser(
        "setup",
        help="One-command first-use setup: wire the host, run a safe CLI smoke test, and print concise next steps.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Bootstrap one host for first use, optionally run a local RelayKit smoke flow, "
            "and print concise next steps for entering the MCP path."
        ),
        epilog=(
            "Examples:\n"
            "  relaykit setup --host codex --force\n"
            "  relaykit setup --all-hosts\n"
            "  relaykit setup --current-host\n"
            "  relaykit setup --host claude-code --dry-run\n"
            "  relaykit setup --host gemini-cli --skip-smoke"
        ),
    )
    parser_setup.add_argument("--host", action="append")
    parser_setup.add_argument(
        "--all-hosts",
        action="store_true",
        help=f"Target all supported hosts: {', '.join(SUPPORTED_ONBOARDING_HOSTS)}.",
    )
    parser_setup.add_argument(
        "--current-host",
        action="store_true",
        help="Auto-detect the current host (Codex today, or use RELAYKIT_HOST to override).",
    )
    parser_setup.add_argument("--workspace-root")
    parser_setup.add_argument("--skip-skills", action="store_true")
    parser_setup.add_argument("--skip-mcp", action="store_true")
    parser_setup.add_argument("--skip-smoke", action="store_true")
    parser_setup.add_argument("--dry-run", action="store_true")
    parser_setup.add_argument("--force", action="store_true")
    parser_setup.add_argument("--format", choices=["auto", "human", "json"], default="auto")
    parser_setup.set_defaults(func=command_setup)

    parser_uninstall_host = subparsers.add_parser(
        "uninstall-host",
        help="Remove RelayKit skills and wiring for one or more hosts.",
    )
    parser_uninstall_host.add_argument("--host", action="append")
    parser_uninstall_host.add_argument(
        "--all-hosts",
        action="store_true",
        help=f"Target all supported hosts: {', '.join(SUPPORTED_ONBOARDING_HOSTS)}.",
    )
    parser_uninstall_host.add_argument(
        "--current-host",
        action="store_true",
        help="Auto-detect the current host (Codex today, or use RELAYKIT_HOST to override).",
    )
    parser_uninstall_host.add_argument("--skip-skills", action="store_true")
    parser_uninstall_host.add_argument("--skip-mcp", action="store_true")
    parser_uninstall_host.add_argument("--dry-run", action="store_true")
    parser_uninstall_host.set_defaults(func=command_uninstall_host)

    parser_ack_host = subparsers.add_parser(
        "acknowledge-host",
        help="Record that host onboarding was offered and explicitly deferred.",
    )
    parser_ack_host.add_argument("--host", action="append")
    parser_ack_host.add_argument(
        "--all-hosts",
        action="store_true",
        help=f"Target all supported hosts: {', '.join(SUPPORTED_ONBOARDING_HOSTS)}.",
    )
    parser_ack_host.add_argument(
        "--current-host",
        action="store_true",
        help="Auto-detect the current host (Codex today, or use RELAYKIT_HOST to override).",
    )
    parser_ack_host.set_defaults(func=command_acknowledge_host)

    parser_install_self = subparsers.add_parser(
        "install-self",
        help="Create a local venv, install RelayKit, and optionally wire supported hosts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Create or reuse a local virtual environment, install RelayKit into it, "
            "and optionally run host onboarding in the same step. "
            "This is the safest default on Homebrew Python systems that reject "
            "ambient pip installs with the externally-managed-environment error."
        ),
        epilog=(
            "Examples:\n"
            "  relaykit install-self\n"
            "  relaykit install-self --current-host --force\n"
            "  relaykit install-self --venv /tmp/relaykit-demo/.venv --host codex"
        ),
    )
    parser_install_self.add_argument("--venv", default=str(SOURCE_ROOT / ".venv"))
    parser_install_self.add_argument("--host", action="append")
    parser_install_self.add_argument(
        "--current-host",
        action="store_true",
        help="Auto-detect the current host (Codex today, or use RELAYKIT_HOST to override).",
    )
    parser_install_self.add_argument("--skip-skills", action="store_true")
    parser_install_self.add_argument("--skip-mcp", action="store_true")
    parser_install_self.add_argument("--force", action="store_true")
    parser_install_self.set_defaults(func=command_install_self)

    parser_smoke = subparsers.add_parser(
        "smoke",
        help="Run a reusable RelayKit lifecycle smoke test and print the next prompt.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Run the standard RelayKit lifecycle smoke test in a scratch workspace. "
            "This proves the local runtime before or after a host is wired."
        ),
        epilog=(
            "Examples:\n"
            "  relaykit smoke --host codex\n"
            "  relaykit smoke --all-hosts\n"
            "  relaykit smoke --host antigravity --workspace-root /private/tmp/relaykit-antigravity-smoke\n"
            "  relaykit smoke --current-host"
        ),
    )
    parser_smoke.add_argument("--host", action="append")
    parser_smoke.add_argument(
        "--all-hosts",
        action="store_true",
        help=f"Target all supported hosts: {', '.join(SUPPORTED_ONBOARDING_HOSTS)}.",
    )
    parser_smoke.add_argument(
        "--current-host",
        action="store_true",
        help="Auto-detect the current host (Codex today, or use RELAYKIT_HOST to override).",
    )
    parser_smoke.add_argument("--workspace-root")
    parser_smoke.add_argument("--force", action="store_true")
    parser_smoke.add_argument("--format", choices=["auto", "human", "json"], default="auto")
    parser_smoke.set_defaults(func=command_smoke)

    parser_doctor = subparsers.add_parser(
        "doctor",
        help="Validate the public runtime surface and the current workspace or project profiles.",
    )
    parser_doctor.add_argument("--workspace-root", default=".")
    parser_doctor.add_argument("--project-root")
    parser_doctor.add_argument("--workspace-profile")
    parser_doctor.add_argument("--project-profile")
    parser_doctor.add_argument("--host", action="append")
    parser_doctor.add_argument(
        "--current-host",
        action="store_true",
        help="Auto-detect the current host (Codex today, or use RELAYKIT_HOST to override).",
    )
    parser_doctor.set_defaults(func=command_doctor)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
