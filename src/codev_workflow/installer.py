"""Conflict-aware installation of the CoDev workflow bundle."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

from codev_workflow import __version__

LOCK_SCHEMA_VERSION = 1
LOCK_PATH = PurePosixPath(".codev/lock.json")
AGENTS_START = "<!-- codev:start -->"
AGENTS_END = "<!-- codev:end -->"
VALID_PLATFORMS = frozenset({"codex", "opencode"})
OPENCODE_AGENT_CONFIGS: dict[str, dict[str, str]] = {
    "orchestrator": {
        "model": "openai/gpt-5.6-luna",
        "description": "Human-controlled workflow and work-item orchestrator",
    },
    "builder": {
        "model": "openai/gpt-5.6-luna",
        "description": "Bounded implementation subagent",
    },
    "reviewer": {
        "model": "openai/gpt-5.6-luna",
        "description": "Independent evidence-based code reviewer",
    },
}

AGENTS_BLOCK = """<!-- codev:start -->
## CoDev human-AI delivery

Read `docs/for-ai/WORKFLOW-AGENTS.md` before planning or implementing product
work. Route requests internally through the installed skills and describe the
current human-facing step as `Understand`, `Build`, `Review`, or `Ship`.

Use the lightest safe path. Inspect repository facts before prescribing code,
keep changes bounded and reviewable, run proportionate validation, and stop for
material decisions instead of inventing them. Humans retain authority for
acceptance, merge, deployment, migration, publication, and rollout expansion.
<!-- codev:end -->"""


class CoDevError(RuntimeError):
    """Raised when an installation cannot be evaluated safely."""


@dataclass(frozen=True)
class Operation:
    """One observable action in an installation plan."""

    kind: str
    path: str
    detail: str = ""


@dataclass
class Plan:
    """A completely preflighted repository mutation."""

    operations: list[Operation] = field(default_factory=list)
    writes: dict[Path, bytes] = field(default_factory=dict, repr=False)
    deletions: set[Path] = field(default_factory=set, repr=False)
    lock: dict[str, Any] | None = field(default=None, repr=False)
    remove_lock: bool = False

    @property
    def conflicts(self) -> list[Operation]:
        return [item for item in self.operations if item.kind == "conflict"]

    @property
    def changed(self) -> list[Operation]:
        return [
            item
            for item in self.operations
            if item.kind in {"add", "update", "integrate", "remove", "retire"}
        ]


@dataclass(frozen=True)
class CheckResult:
    """Health of one installed target."""

    version: str
    issues: tuple[str, ...]
    managed_files: int

    @property
    def ok(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class OpenCodePreparation:
    """The result of safely integrating the OpenCode configuration."""

    content: bytes | None
    default_agent_managed: bool
    managed_agents: dict[str, str]
    schema_managed: bool
    agent_container_managed: bool
    config_file_managed: bool
    detail: str


def normalize_platforms(platforms: Iterable[str]) -> tuple[str, ...]:
    selected = set(platforms)
    if "all" in selected:
        selected = set(VALID_PLATFORMS)
    unknown = selected - VALID_PLATFORMS
    if unknown:
        raise CoDevError("unknown platform: " + ", ".join(sorted(unknown)))
    if not selected:
        selected = set(VALID_PLATFORMS)
    return tuple(sorted(selected))


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalise_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _block_hash(value: str) -> str:
    return _sha256(_normalise_newlines(value).encode("utf-8"))


def _json_hash(value: Any) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256(rendered.encode("utf-8"))


def _walk_bundle() -> dict[str, bytes]:
    root = resources.files("codev_workflow").joinpath("bundle")
    found: dict[str, bytes] = {}

    def visit(node: Any, prefix: PurePosixPath) -> None:
        for child in sorted(node.iterdir(), key=lambda item: item.name):
            if child.name == "__pycache__" or child.name.endswith(".pyc"):
                continue
            relative = prefix / child.name
            if child.is_dir():
                visit(child, relative)
            elif child.is_file():
                found[relative.as_posix()] = child.read_bytes()

    visit(root, PurePosixPath())
    return found


def _bundle_files(platforms: tuple[str, ...]) -> dict[str, bytes]:
    files = _walk_bundle()
    # The validator needs a complete policy fixture at the bundle root, while
    # target repositories receive the conflict-safe managed block instead.
    files.pop("AGENTS.md", None)
    if "opencode" not in platforms:
        files = {
            path: content
            for path, content in files.items()
            if not path.startswith(".opencode/")
        }
    return files


def _read_lock(target: Path) -> dict[str, Any]:
    path = target / Path(LOCK_PATH.as_posix())
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CoDevError(f"CoDev is not installed in {target}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise CoDevError(f"cannot read {path}: {error}") from error
    if not isinstance(raw, dict):
        raise CoDevError(f"{path} must contain a JSON object")
    if raw.get("schema_version") != LOCK_SCHEMA_VERSION:
        raise CoDevError(
            f"unsupported lock schema {raw.get('schema_version')!r}; "
            "install a compatible CoDev version"
        )
    if not isinstance(raw.get("files"), dict):
        raise CoDevError(f"{path} has no valid files map")
    return raw


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.codev.tmp")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _remove_empty_parent_dirs(path: Path, target: Path) -> None:
    """Remove empty managed-file parents without touching the target repository."""

    current = path.parent
    while current != target:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _agent_block_from(text: str) -> str | None:
    start = text.find(AGENTS_START)
    end = text.find(AGENTS_END)
    if start < 0 and end < 0:
        return None
    if start < 0 or end < start:
        raise CoDevError("AGENTS.md contains incomplete CoDev markers")
    end += len(AGENTS_END)
    if text.find(AGENTS_START, start + len(AGENTS_START)) >= 0:
        raise CoDevError("AGENTS.md contains more than one CoDev block")
    return text[start:end]


def _with_agent_block(text: str, block: str) -> str:
    current = _agent_block_from(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    rendered = block.replace("\n", newline)
    if current is None:
        prefix = text.rstrip("\r\n")
        if prefix:
            return prefix + newline * 2 + rendered + newline
        return rendered + newline
    return text.replace(current, rendered, 1)


def _without_agent_block(text: str) -> str:
    current = _agent_block_from(text)
    if current is None:
        return text
    start = text.find(current)
    end = start + len(current)
    newline = "\r\n" if "\r\n" in text else "\n"
    prefix = text[:start]
    suffix = text[end:]
    if prefix.endswith(newline * 2):
        prefix = prefix[: -len(newline * 2)]
    if suffix.startswith(newline):
        suffix = suffix[len(newline) :]
    return prefix + suffix


def _prepare_opencode(
    target: Path,
    managed_agents: dict[str, str] | None = None,
    *,
    schema_managed: bool = False,
    agent_container_managed: bool = False,
    config_file_managed: bool = False,
) -> OpenCodePreparation:
    path = target / ".opencode" / "opencode.json"
    if path.exists():
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CoDevError(f"cannot merge {path}: {error}") from error
        if not isinstance(config, dict):
            raise CoDevError(f"{path} must contain a JSON object")
    else:
        config = {}
        config_file_managed = True

    managed_agents = dict(managed_agents or {})
    changed = False
    if "$schema" not in config:
        config["$schema"] = "https://opencode.ai/config.json"
        schema_managed = True
        changed = True

    default_managed = False
    detail = "existing default agent preserved"
    if "default_agent" not in config:
        config["default_agent"] = "orchestrator"
        default_managed = True
        changed = True
        detail = "set orchestrator as the default agent"
    elif config.get("default_agent") == "orchestrator":
        detail = "orchestrator already configured"

    agents = config.get("agent")
    if agents is None:
        agents = {}
        config["agent"] = agents
        agent_container_managed = True
        changed = True
    elif not isinstance(agents, dict):
        raise CoDevError(f"cannot merge {path}: agent must contain a JSON object")

    integrated_agents: list[str] = []
    for name, expected in OPENCODE_AGENT_CONFIGS.items():
        current = agents.get(name)
        expected_hash = _json_hash(expected)
        old_hash = managed_agents.get(name)
        if old_hash is not None:
            if not isinstance(current, dict) or _json_hash(current) != old_hash:
                raise CoDevError(
                    f"managed OpenCode agent {name!r} was modified or removed"
                )
            if current != expected:
                agents[name] = expected
                changed = True
            managed_agents[name] = expected_hash
            continue
        if name not in agents:
            agents[name] = expected
            managed_agents[name] = expected_hash
            integrated_agents.append(name)
            changed = True

    if integrated_agents:
        detail = "integrated OpenCode agents: " + ", ".join(integrated_agents)

    if not changed:
        return OpenCodePreparation(
            None,
            default_managed,
            managed_agents,
            schema_managed,
            agent_container_managed,
            config_file_managed,
            detail,
        )
    content = (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return OpenCodePreparation(
        content,
        default_managed,
        managed_agents,
        schema_managed,
        agent_container_managed,
        config_file_managed,
        detail,
    )


def _new_lock(
    platforms: tuple[str, ...],
    files: dict[str, bytes],
    *,
    default_agent_managed: bool,
    managed_opencode_agents: dict[str, str],
    opencode_schema_managed: bool,
    opencode_agent_container_managed: bool,
    opencode_config_file_managed: bool,
) -> dict[str, Any]:
    return {
        "schema_version": LOCK_SCHEMA_VERSION,
        "bundle_version": __version__,
        "platforms": list(platforms),
        "files": {path: _sha256(files[path]) for path in sorted(files)},
        "integrations": {
            "agents_block_hash": _block_hash(AGENTS_BLOCK),
            "opencode_default_agent_managed": default_agent_managed,
            "opencode_agent_hashes": dict(sorted(managed_opencode_agents.items())),
            "opencode_schema_managed": opencode_schema_managed,
            "opencode_agent_container_managed": opencode_agent_container_managed,
            "opencode_config_file_managed": opencode_config_file_managed,
        },
    }


def plan_init(target: Path, platforms: Iterable[str] = ("all",)) -> Plan:
    target = target.resolve()
    if (target / Path(LOCK_PATH.as_posix())).exists():
        raise CoDevError("CoDev is already installed; use diff or update")
    selected = normalize_platforms(platforms)
    files = _bundle_files(selected)
    plan = Plan()

    for relative, content in sorted(files.items()):
        destination = target / Path(relative)
        if not destination.exists():
            plan.operations.append(Operation("add", relative))
            plan.writes[destination] = content
        elif destination.is_file() and destination.read_bytes() == content:
            plan.operations.append(
                Operation("keep", relative, "identical file adopted")
            )
        else:
            plan.operations.append(
                Operation("conflict", relative, "different file already exists")
            )

    agents_path = target / "AGENTS.md"
    existing_agents = (
        agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    )
    try:
        existing_block = _agent_block_from(existing_agents)
    except CoDevError as error:
        plan.operations.append(Operation("conflict", "AGENTS.md", str(error)))
    else:
        if existing_block is None:
            merged = _with_agent_block(existing_agents, AGENTS_BLOCK)
            plan.writes[agents_path] = merged.encode("utf-8")
            plan.operations.append(
                Operation("integrate", "AGENTS.md", "append managed policy block")
            )
        elif _block_hash(existing_block) == _block_hash(AGENTS_BLOCK):
            plan.operations.append(
                Operation("keep", "AGENTS.md", "policy block exists")
            )
        else:
            plan.operations.append(
                Operation("conflict", "AGENTS.md", "different CoDev block exists")
            )

    default_agent_managed = False
    managed_opencode_agents: dict[str, str] = {}
    opencode_schema_managed = False
    opencode_agent_container_managed = False
    opencode_config_file_managed = False
    if "opencode" in selected:
        try:
            opencode = _prepare_opencode(target)
        except CoDevError as error:
            plan.operations.append(
                Operation("conflict", ".opencode/opencode.json", str(error))
            )
        else:
            default_agent_managed = opencode.default_agent_managed
            managed_opencode_agents = opencode.managed_agents
            opencode_schema_managed = opencode.schema_managed
            opencode_agent_container_managed = opencode.agent_container_managed
            opencode_config_file_managed = opencode.config_file_managed
            if opencode.content is not None:
                plan.writes[target / ".opencode" / "opencode.json"] = opencode.content
                plan.operations.append(
                    Operation("integrate", ".opencode/opencode.json", opencode.detail)
                )
            else:
                plan.operations.append(
                    Operation("keep", ".opencode/opencode.json", opencode.detail)
                )

    plan.lock = _new_lock(
        selected,
        files,
        default_agent_managed=default_agent_managed,
        managed_opencode_agents=managed_opencode_agents,
        opencode_schema_managed=opencode_schema_managed,
        opencode_agent_container_managed=opencode_agent_container_managed,
        opencode_config_file_managed=opencode_config_file_managed,
    )
    return plan


def _replace_agent_block_for_update(target: Path, old_hash: str, plan: Plan) -> None:
    agents_path = target / "AGENTS.md"
    if not agents_path.exists():
        plan.operations.append(
            Operation("conflict", "AGENTS.md", "managed policy block is missing")
        )
        return
    text = agents_path.read_text(encoding="utf-8")
    try:
        current = _agent_block_from(text)
    except CoDevError as error:
        plan.operations.append(Operation("conflict", "AGENTS.md", str(error)))
        return
    if current is None:
        plan.operations.append(
            Operation("conflict", "AGENTS.md", "managed policy block is missing")
        )
        return
    current_hash = _block_hash(current)
    new_hash = _block_hash(AGENTS_BLOCK)
    if current_hash == new_hash:
        plan.operations.append(Operation("keep", "AGENTS.md", "policy block current"))
    elif current_hash == old_hash:
        plan.operations.append(Operation("update", "AGENTS.md", "policy block"))
        plan.writes[agents_path] = _with_agent_block(text, AGENTS_BLOCK).encode("utf-8")
    else:
        plan.operations.append(
            Operation("conflict", "AGENTS.md", "managed policy block was modified")
        )


def plan_update(target: Path) -> Plan:
    target = target.resolve()
    lock = _read_lock(target)
    selected = normalize_platforms(lock.get("platforms", []))
    new_files = _bundle_files(selected)
    old_files = lock["files"]
    valid_entries = all(
        isinstance(path, str) and isinstance(value, str)
        for path, value in old_files.items()
    )
    if not valid_entries:
        raise CoDevError("lock file contains an invalid managed-file entry")

    plan = Plan()
    for relative in sorted(set(old_files) | set(new_files)):
        destination = target / Path(relative)
        old_hash = old_files.get(relative)
        content = new_files.get(relative)
        if content is None:
            plan.operations.append(
                Operation("retire", relative, "upstream removed; retained locally")
            )
            continue
        new_hash = _sha256(content)
        if old_hash is None:
            if not destination.exists():
                plan.operations.append(Operation("add", relative, "new bundle file"))
                plan.writes[destination] = content
            elif (
                destination.is_file() and _sha256(destination.read_bytes()) == new_hash
            ):
                plan.operations.append(Operation("keep", relative, "new file adopted"))
            else:
                plan.operations.append(
                    Operation("conflict", relative, "new bundle file collides locally")
                )
            continue
        if not destination.is_file():
            plan.operations.append(
                Operation("conflict", relative, "managed file is missing or not a file")
            )
            continue
        current_hash = _sha256(destination.read_bytes())
        if current_hash == new_hash:
            plan.operations.append(Operation("keep", relative))
        elif current_hash == old_hash:
            plan.operations.append(Operation("update", relative))
            plan.writes[destination] = content
        elif new_hash == old_hash:
            plan.operations.append(
                Operation("conflict", relative, "managed file has local changes")
            )
        else:
            plan.operations.append(
                Operation("conflict", relative, "local and upstream changes overlap")
            )

    integrations = lock.get("integrations")
    if not isinstance(integrations, dict):
        raise CoDevError("lock file contains invalid integrations")
    old_block_hash = integrations.get("agents_block_hash")
    if not isinstance(old_block_hash, str):
        raise CoDevError("lock file has no valid AGENTS.md block hash")
    _replace_agent_block_for_update(target, old_block_hash, plan)

    default_managed = bool(integrations.get("opencode_default_agent_managed"))
    schema_managed = bool(integrations.get("opencode_schema_managed"))
    agent_container_managed = bool(
        integrations.get("opencode_agent_container_managed")
    )
    config_file_managed = bool(integrations.get("opencode_config_file_managed"))
    managed_opencode_agents = integrations.get("opencode_agent_hashes", {})
    if not isinstance(managed_opencode_agents, dict) or not all(
        isinstance(name, str) and isinstance(value, str)
        for name, value in managed_opencode_agents.items()
    ):
        raise CoDevError("lock file has invalid OpenCode agent hashes")
    if "opencode" in selected:
        try:
            opencode = _prepare_opencode(
                target,
                managed_opencode_agents,
                schema_managed=schema_managed,
                agent_container_managed=agent_container_managed,
                config_file_managed=config_file_managed,
            )
        except CoDevError as error:
            plan.operations.append(
                Operation("conflict", ".opencode/opencode.json", str(error))
            )
        else:
            default_managed = default_managed or opencode.default_agent_managed
            managed_opencode_agents = opencode.managed_agents
            schema_managed = opencode.schema_managed
            agent_container_managed = opencode.agent_container_managed
            config_file_managed = opencode.config_file_managed
            if opencode.content is not None:
                plan.writes[target / ".opencode" / "opencode.json"] = opencode.content
                plan.operations.append(
                    Operation("integrate", ".opencode/opencode.json", opencode.detail)
                )
            else:
                plan.operations.append(
                    Operation("keep", ".opencode/opencode.json", opencode.detail)
                )
    plan.lock = _new_lock(
        selected,
        new_files,
        default_agent_managed=default_managed,
        managed_opencode_agents=managed_opencode_agents,
        opencode_schema_managed=schema_managed,
        opencode_agent_container_managed=agent_container_managed,
        opencode_config_file_managed=config_file_managed,
    )
    return plan


def _prepare_opencode_removal(
    target: Path, integrations: dict[str, Any]
) -> tuple[bytes | None, bool, str]:
    path = target / ".opencode" / "opencode.json"
    if not path.exists():
        return None, False, "OpenCode config already absent"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CoDevError(f"cannot remove managed values from {path}: {error}") from error
    if not isinstance(config, dict):
        raise CoDevError(f"{path} must contain a JSON object")

    managed_agents = integrations.get("opencode_agent_hashes", {})
    if not isinstance(managed_agents, dict) or not all(
        isinstance(name, str) and isinstance(value, str)
        for name, value in managed_agents.items()
    ):
        raise CoDevError("lock file has invalid OpenCode agent hashes")

    changed = False
    if integrations.get("opencode_default_agent_managed"):
        current_default = config.get("default_agent")
        if current_default == "orchestrator":
            del config["default_agent"]
            changed = True
        elif current_default is not None:
            raise CoDevError("managed OpenCode default_agent has local changes")

    agents = config.get("agent")
    if agents is not None and not isinstance(agents, dict):
        if managed_agents:
            raise CoDevError("managed OpenCode agent configuration has local changes")
    elif isinstance(agents, dict):
        for name, expected_hash in sorted(managed_agents.items()):
            if name not in agents:
                continue
            current = agents[name]
            if not isinstance(current, dict) or _json_hash(current) != expected_hash:
                raise CoDevError(f"managed OpenCode agent has local changes: {name}")
            del agents[name]
            changed = True
        if integrations.get("opencode_agent_container_managed") and not agents:
            del config["agent"]
            changed = True

    if integrations.get("opencode_schema_managed"):
        schema = config.get("$schema")
        if schema == "https://opencode.ai/config.json":
            del config["$schema"]
            changed = True
        elif schema is not None:
            raise CoDevError("managed OpenCode schema has local changes")

    if not changed:
        return None, False, "no managed OpenCode values to remove"
    if integrations.get("opencode_config_file_managed") and not config:
        return None, True, "remove managed OpenCode config"
    content = (json.dumps(config, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return content, False, "remove managed OpenCode values"


def plan_remove(target: Path) -> Plan:
    """Preflight removal of the installed CoDev bundle and integrations."""

    target = target.resolve()
    lock = _read_lock(target)
    files = lock["files"]
    if not all(isinstance(path, str) and isinstance(value, str) for path, value in files.items()):
        raise CoDevError("lock file contains an invalid managed-file entry")
    integrations = lock.get("integrations")
    if not isinstance(integrations, dict):
        raise CoDevError("lock file contains invalid integrations")

    plan = Plan(remove_lock=True)
    for relative, expected_hash in sorted(files.items()):
        destination = target / Path(relative)
        if not destination.exists():
            continue
        if not destination.is_file():
            plan.operations.append(
                Operation("conflict", relative, "managed path is not a file")
            )
        elif _sha256(destination.read_bytes()) != expected_hash:
            plan.operations.append(
                Operation("conflict", relative, "managed file has local changes")
            )
        else:
            plan.deletions.add(destination)
            plan.operations.append(Operation("remove", relative))

    agents_path = target / "AGENTS.md"
    if agents_path.exists():
        try:
            block = _agent_block_from(agents_path.read_text(encoding="utf-8"))
        except CoDevError as error:
            plan.operations.append(Operation("conflict", "AGENTS.md", str(error)))
        else:
            expected_hash = integrations.get("agents_block_hash")
            if not isinstance(expected_hash, str):
                raise CoDevError("lock file has no valid AGENTS.md block hash")
            if block is not None:
                if _block_hash(block) != expected_hash:
                    plan.operations.append(
                        Operation("conflict", "AGENTS.md", "managed policy block was modified")
                    )
                else:
                    plan.writes[agents_path] = _without_agent_block(
                        agents_path.read_text(encoding="utf-8")
                    ).encode("utf-8")
                    plan.operations.append(
                        Operation("integrate", "AGENTS.md", "remove managed policy block")
                    )

    selected = normalize_platforms(lock.get("platforms", []))
    if "opencode" in selected:
        try:
            opencode_content, remove_opencode_config, detail = _prepare_opencode_removal(
                target, integrations
            )
        except CoDevError as error:
            plan.operations.append(
                Operation("conflict", ".opencode/opencode.json", str(error))
            )
        else:
            if opencode_content is not None:
                plan.writes[target / ".opencode" / "opencode.json"] = opencode_content
                plan.operations.append(
                    Operation("integrate", ".opencode/opencode.json", detail)
                )
            elif remove_opencode_config:
                plan.deletions.add(target / ".opencode" / "opencode.json")
                plan.operations.append(Operation("remove", ".opencode/opencode.json"))
    return plan


def apply_plan(target: Path, plan: Plan) -> None:
    if plan.conflicts:
        raise CoDevError("cannot apply a plan that contains conflicts")
    if plan.lock is None and not plan.remove_lock:
        raise CoDevError("installation plan has no lock state")
    target = target.resolve()
    for path, content in sorted(plan.writes.items(), key=lambda item: str(item[0])):
        _atomic_write(path, content)
    for path in sorted(plan.deletions, key=str):
        path.unlink()
    for path in sorted(plan.deletions, key=str):
        _remove_empty_parent_dirs(path, target)
    if plan.remove_lock:
        lock_path = target / Path(LOCK_PATH.as_posix())
        lock_path.unlink(missing_ok=True)
        _remove_empty_parent_dirs(lock_path, target)
        return
    assert plan.lock is not None
    lock_content = (json.dumps(plan.lock, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    _atomic_write(target / Path(LOCK_PATH.as_posix()), lock_content)


def check_project(target: Path) -> CheckResult:
    target = target.resolve()
    lock = _read_lock(target)
    issues: list[str] = []
    files = lock["files"]
    for relative, expected in sorted(files.items()):
        destination = target / Path(relative)
        if not destination.is_file():
            issues.append(f"missing managed file: {relative}")
            continue
        if _sha256(destination.read_bytes()) != expected:
            issues.append(f"managed file has local changes: {relative}")

    integrations = lock.get("integrations", {})
    agents_path = target / "AGENTS.md"
    if not agents_path.is_file():
        issues.append("AGENTS.md is missing")
    else:
        try:
            block = _agent_block_from(agents_path.read_text(encoding="utf-8"))
        except CoDevError as error:
            issues.append(str(error))
        else:
            if block is None:
                issues.append("AGENTS.md has no managed CoDev block")
            elif _block_hash(block) != integrations.get("agents_block_hash"):
                issues.append("the managed AGENTS.md block has local changes")

    managed_opencode_agents = integrations.get("opencode_agent_hashes", {})
    if not isinstance(managed_opencode_agents, dict) or not all(
        isinstance(name, str) and isinstance(value, str)
        for name, value in managed_opencode_agents.items()
    ):
        issues.append("lock file has invalid OpenCode agent hashes")
        managed_opencode_agents = {}
    if integrations.get("opencode_default_agent_managed") or managed_opencode_agents:
        config_path = target / ".opencode" / "opencode.json"
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            issues.append(f"cannot read .opencode/opencode.json: {error}")
        else:
            if config.get("default_agent") != "orchestrator":
                issues.append("managed OpenCode default_agent is not orchestrator")
            agents = config.get("agent")
            if not isinstance(agents, dict):
                issues.append("managed OpenCode agent configuration is missing")
            else:
                for name, expected_hash in sorted(managed_opencode_agents.items()):
                    current = agents.get(name)
                    if not isinstance(current, dict) or _json_hash(current) != expected_hash:
                        issues.append(f"managed OpenCode agent has local changes: {name}")

    issues.extend(_validate_installed_skills(target, files))
    return CheckResult(
        version=str(lock.get("bundle_version", "unknown")),
        issues=tuple(issues),
        managed_files=len(files),
    )


def _validate_installed_skills(target: Path, files: dict[str, str]) -> list[str]:
    issues: list[str] = []
    skill_paths = [
        path
        for path in files
        if path.startswith(".agents/skills/") and path.endswith("/SKILL.md")
    ]
    for relative in sorted(skill_paths):
        path = target / Path(relative)
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        if len(lines) < 4 or lines[0].strip() != "---":
            issues.append(f"invalid skill frontmatter: {relative}")
            continue
        try:
            end = lines.index("---", 1)
        except ValueError:
            issues.append(f"unterminated skill frontmatter: {relative}")
            continue
        fields: dict[str, str] = {}
        for line in lines[1:end]:
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip()] = value.strip()
        expected_name = PurePosixPath(relative).parent.name
        if fields.get("name") != expected_name:
            issues.append(f"skill name does not match its folder: {relative}")
        if not fields.get("description"):
            issues.append(f"skill description is empty: {relative}")
    return issues


def format_plan(plan: Plan) -> str:
    if not plan.operations:
        return "No managed files found."
    visible = [item for item in plan.operations if item.kind != "keep"]
    if not visible:
        return "No changes."
    lines = []
    for item in visible:
        suffix = f" — {item.detail}" if item.detail else ""
        lines.append(f"{item.kind.upper():9} {item.path}{suffix}")
    return "\n".join(lines)
