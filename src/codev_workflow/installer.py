# BSD 3-Clause License
#
# Copyright (c) 2026, Martin Urban, Hannah Kullik
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""Conflict-aware installation of the CoDev workflow bundle."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

from codev_workflow import __version__

LOCK_SCHEMA_VERSION = 2
LEGACY_LOCK_SCHEMA_VERSION = 1
LOCK_PATH = PurePosixPath(".codev/lock.json")
AGENTS_START = "<!-- codev:start -->"
AGENTS_END = "<!-- codev:end -->"
GITIGNORE_START = "# codev:start"
GITIGNORE_END = "# codev:end"
VALID_PLATFORMS = frozenset({"antigravity", "claude", "codex", "junie", "opencode"})
VALID_PROGRAMMING_LANGUAGES = frozenset({"none", "python", "typescript", "all"})
AUDIT_SKILL_PREFIXES = {
    "python": ".agents/skills/audit-google-python-style/",
    "typescript": ".agents/skills/audit-google-typescript-style/",
}
AUDIT_AGENT_TEMPLATES = {
    "antigravity": (
        ".agents/agents/code-audit.md.template",
        ".agents/agents/code-audit.md",
    ),
    "claude": (".claude/agents/code-audit.md.template", ".claude/agents/code-audit.md"),
    "codex": (
        ".codex/agents/code-audit.toml.template",
        ".codex/agents/code-audit.toml",
    ),
    "junie": (".junie/agents/code-audit.md.template", ".junie/agents/code-audit.md"),
    "opencode": (
        ".opencode/agents/code-audit.md.template",
        ".opencode/agents/code-audit.md",
    ),
}
# code-audit-gate is the autonomous, subagent-only counterpart dispatched by
# orchestrator's pre-PR cleanup step -- distinct from code-audit above, which
# stays human-direct only (ADR-0015). Same {{LANGUAGE_INSTRUCTIONS}}/
# {{SKILL_PERMISSIONS}}/{{DESCRIPTION_SCOPE}} templating, rendered the same
# way via _render_code_audit_agent.
PRE_PR_CLEANUP_AGENT_TEMPLATES = {
    "antigravity": (
        ".agents/agents/code-audit-gate.md.template",
        ".agents/agents/code-audit-gate.md",
    ),
    "claude": (
        ".claude/agents/code-audit-gate.md.template",
        ".claude/agents/code-audit-gate.md",
    ),
    "codex": (
        ".codex/agents/code-audit-gate.toml.template",
        ".codex/agents/code-audit-gate.toml",
    ),
    "junie": (
        ".junie/agents/code-audit-gate.md.template",
        ".junie/agents/code-audit-gate.md",
    ),
    "opencode": (
        ".opencode/agents/code-audit-gate.md.template",
        ".opencode/agents/code-audit-gate.md",
    ),
}
OPENCODE_AGENT_CONFIGS: dict[str, dict[str, str]] = {
    "orchestrator": {
        "model": "openai/gpt-5.6-luna",
        "description": "Human-controlled workflow and task orchestrator",
    },
    "planner": {
        "model": "openai/gpt-5.6-luna",
        "description": (
            "Human-controlled entry point for Specify, Understand, Design, "
            "and Plan work -- decoupled from execution"
        ),
        "mode": "primary",
    },
    "code-audit": {
        "model": "openai/gpt-5.6-luna",
        "description": "Standalone primary code audit agent",
        "mode": "primary",
    },
    "code-audit-gate": {
        "model": "openai/gpt-5.6-luna",
        "description": (
            "Autonomous pre-PR cleanup subagent -- fixes style and "
            "documentation issues only, dispatched by orchestrator"
        ),
    },
    "builder": {
        "model": "openai/gpt-5.6-luna",
        "description": "Bounded implementation subagent",
    },
    "reviewer": {
        "model": "openai/gpt-5.6-luna",
        "description": "Independent evidence-based code reviewer",
    },
    "lightweight-reviewer": {
        "model": "openai/gpt-5.6-luna",
        "description": (
            "Narrow, fast independent check that the inner loop's change "
            "matches the task and passes local QA"
        ),
    },
    "outer-loop-runner": {
        "model": "openai/gpt-5.6-luna",
        "description": (
            "Human-triggered outer-loop coordinator -- fetches a PR, gates on "
            "CI, dispatches five specialist reviewers, and drives "
            "human-triaged correction to a landed pull request"
        ),
        "mode": "primary",
    },
    "correctness-tests-specialist": {
        "model": "openai/gpt-5.6-luna",
        "description": (
            "Outer-loop specialist for correctness, error handling, and test "
            "quality -- one of five parallel specialist reviewers"
        ),
    },
    "security-data-specialist": {
        "model": "openai/gpt-5.6-luna",
        "description": (
            "Outer-loop specialist for security, privacy, data, and "
            "compatibility risk -- one of five parallel specialist reviewers"
        ),
    },
    "concurrency-specialist": {
        "model": "openai/gpt-5.6-luna",
        "description": (
            "Outer-loop specialist for concurrency and race-condition risk -- "
            "one of five parallel specialist reviewers"
        ),
    },
    "architecture-maintainability-specialist": {
        "model": "openai/gpt-5.6-luna",
        "description": (
            "Outer-loop specialist for architecture, scope, and "
            "maintainability -- one of five parallel specialist reviewers"
        ),
    },
    "rollout-specialist": {
        "model": "openai/gpt-5.6-luna",
        "description": (
            "Outer-loop specialist for rollout, monitoring, migration, and "
            "rollback -- one of five parallel specialist reviewers"
        ),
    },
}

AGENTS_BLOCK = """<!-- codev:start -->
## CoDev human-AI delivery

Read `.codev/for-ai/ai-agent-guidelines.md` before planning or implementing product
work. Route requests internally through the installed skills and describe the
current human-facing step as `Understand`, `Build`, `Review`, or `Ship`.

Use the lightest safe path. Inspect repository facts before prescribing code,
keep changes bounded and reviewable, run proportionate validation, and stop for
material decisions instead of inventing them. Humans retain authority for
acceptance, merge, deployment, migration, publication, and rollout expansion.
<!-- codev:end -->"""

GITIGNORE_BLOCK = """# codev:start
# CoDev local escalation log (ADR-0003) -- not shared or committed.
.codev/task/escalations.jsonl
# codev:end"""

CODEOWNERS_LOCATIONS = ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS")
_CODEOWNERS_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".codev",
        ".github",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".idea",
        ".vscode",
    }
)
CODEOWNERS_HEADER = """\
# CODEOWNERS -- routes GitHub review requests, and with a branch-protection
# rule, required approval, by path. The last matching pattern wins, the
# same as .gitignore. See
# https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners
#
# <pattern>  <@user-or-team> [<@user-or-team> ...]
"""


class CoDevError(RuntimeError):
    """Raised when an installation cannot be evaluated safely."""


@dataclass(frozen=True)
class Operation:
    """One observable action in an installation plan."""

    kind: str
    path: str
    detail: str = ""
    # The upstream bundle's replacement bytes for a "conflict" operation, when
    # one exists -- absent for conflicts where upstream has nothing to offer
    # (e.g. a managed file upstream no longer ships at all). Lets a conflict
    # resolver show a diff and write an "override" without recomputing the
    # bundle a second time.
    new_content: bytes | None = field(default=None, repr=False, compare=False)


class Resolution(StrEnum):
    """A user's per-file decision for one "conflict" operation.

    OVERRIDE and COPY require the operation's `new_content` to be set --
    they are not offered for a conflict where upstream has nothing to write
    (e.g. a managed file the bundle no longer ships). DELETE is only for
    that case: it adopts upstream's removal instead of retaining the file.
    """

    OVERRIDE = "override"
    KEEP = "keep"
    COPY = "copy"
    SKIP = "skip"
    DELETE = "delete"


def copy_sidecar_path(destination: Path) -> Path:
    """Where an upstream conflict's content is written for a `copy` choice."""

    return destination.with_name(destination.name + ".copy")


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


def normalize_programming_language(value: str | None) -> str:
    selected = value or "none"
    if selected not in VALID_PROGRAMMING_LANGUAGES:
        raise CoDevError(f"unknown programming language: {selected}")
    return selected


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


def _render_code_audit_agent(template: bytes, programming_language: str) -> bytes:
    scopes = {
        "none": "language-agnostic code style and quality issues",
        "python": "Google Python style violations",
        "typescript": "Google TypeScript style violations",
        "all": "Google TypeScript and Python style violations",
    }
    skill_names = {
        "python": "audit-google-python-style",
        "typescript": "audit-google-typescript-style",
    }
    selected_skills = (
        tuple(skill_names.values())
        if programming_language == "all"
        else (
            ()
            if programming_language == "none"
            else (skill_names[programming_language],)
        )
    )
    permissions = "".join(f"    {name}: allow\n" for name in selected_skills)
    junie_skills = "[" + ", ".join(f'"{name}"' for name in selected_skills) + "]"
    if programming_language == "none":
        instructions = (
            "Do not assume a programming language or invoke language-specific "
            "audit skills. Perform a language-agnostic audit using repository "
            "instructions, available deterministic tooling, and local conventions."
        )
    else:
        language_instructions = {
            "python": "Use `audit-google-python-style` for Python.",
            "typescript": "Use `audit-google-typescript-style` for TypeScript/TSX.",
            "all": (
                "Use `audit-google-typescript-style` for TypeScript/TSX and "
                "`audit-google-python-style` for Python. Use both when the "
                "approved scope spans both languages."
            ),
        }
        instructions = language_instructions[programming_language]
    rendered = template.decode("utf-8")
    rendered = rendered.replace("{{DESCRIPTION_SCOPE}}", scopes[programming_language])
    rendered = rendered.replace("{{SKILL_PERMISSIONS}}", permissions.rstrip("\n"))
    rendered = rendered.replace("{{LANGUAGE_INSTRUCTIONS}}", instructions)
    rendered = rendered.replace("{{JUNIE_SKILLS}}", junie_skills)
    return rendered.encode("utf-8")


def _bundle_files(
    platforms: tuple[str, ...], programming_language: str = "none"
) -> dict[str, bytes]:
    programming_language = normalize_programming_language(programming_language)
    files = _walk_bundle()
    templates: dict[str, bytes] = {}
    for platform, (source, _) in AUDIT_AGENT_TEMPLATES.items():
        template = files.pop(source, None)
        if template is None:
            raise CoDevError(f"bundle is missing {source}")
        templates[platform] = template
    cleanup_templates: dict[str, bytes] = {}
    for platform, (source, _) in PRE_PR_CLEANUP_AGENT_TEMPLATES.items():
        template = files.pop(source, None)
        if template is None:
            raise CoDevError(f"bundle is missing {source}")
        cleanup_templates[platform] = template
    # The validator needs a complete policy fixture at the bundle root, while
    # target repositories receive the conflict-safe managed block instead.
    files.pop("AGENTS.md", None)
    selected_audit_languages = (
        set(AUDIT_SKILL_PREFIXES)
        if programming_language == "all"
        else {programming_language} - {"none"}
    )
    files = {
        path: content
        for path, content in files.items()
        if not any(
            path.startswith(prefix)
            for language, prefix in AUDIT_SKILL_PREFIXES.items()
            if language not in selected_audit_languages
        )
    }
    if "claude" in platforms:
        # Claude Code has no configurable path for skill discovery -- it
        # hardcodes .claude/skills/*/SKILL.md, unlike Antigravity, which
        # shares CoDev's own .agents/skills/ directory directly. Mirror the
        # already-filtered shared skills there instead of duplicating them
        # by hand in the bundle source.
        for path, content in list(files.items()):
            if path.startswith(".agents/skills/"):
                files[".claude/skills/" + path[len(".agents/skills/") :]] = content
    for platform in platforms:
        if platform in AUDIT_AGENT_TEMPLATES:
            _, destination = AUDIT_AGENT_TEMPLATES[platform]
            files[destination] = _render_code_audit_agent(
                templates[platform], programming_language
            )
        if platform in PRE_PR_CLEANUP_AGENT_TEMPLATES:
            _, destination = PRE_PR_CLEANUP_AGENT_TEMPLATES[platform]
            files[destination] = _render_code_audit_agent(
                cleanup_templates[platform], programming_language
            )
    if "claude" not in platforms:
        files = {
            path: content
            for path, content in files.items()
            if not path.startswith(".claude/")
        }
    if "opencode" not in platforms:
        files = {
            path: content
            for path, content in files.items()
            if not path.startswith(".opencode/")
        }
    if "junie" not in platforms:
        files = {
            path: content
            for path, content in files.items()
            if not path.startswith(".junie/")
        }
    if "antigravity" not in platforms:
        files = {
            path: content
            for path, content in files.items()
            if not path.startswith(".agents/agents/")
        }
    if "codex" not in platforms:
        files = {
            path: content
            for path, content in files.items()
            if not path.startswith(".codex/")
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
    if raw.get("schema_version") not in {
        LEGACY_LOCK_SCHEMA_VERSION,
        LOCK_SCHEMA_VERSION,
    }:
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


def codeowners_init(target: Path) -> Path:
    """Scaffold a starter `.github/CODEOWNERS`. Refuses if one already exists.

    Unlike AGENTS.md and the .gitignore block, this is not a managed
    integration: no lock.json entry, no hash tracked, and codev
    update/remove have no awareness of it once written. It is intended to
    be run directly by a human during repository setup, the same as
    `codev init` itself, not invoked by an agent mid-workflow.
    """
    target = target.resolve()
    for relative in CODEOWNERS_LOCATIONS:
        if (target / Path(relative)).is_file():
            raise CoDevError(
                f"a CODEOWNERS file already exists at {relative}; refusing to "
                "overwrite it"
            )
    top_level_dirs = sorted(
        entry.name
        for entry in target.iterdir()
        if entry.is_dir() and entry.name not in _CODEOWNERS_EXCLUDED_DIRS
    )
    lines = [CODEOWNERS_HEADER.rstrip("\n")]
    if top_level_dirs:
        lines.extend(f"# {name}/  @your-team-here" for name in top_level_dirs)
    else:
        lines.append("# path/pattern  @your-team-here")
    destination = target / ".github" / "CODEOWNERS"
    _atomic_write(destination, ("\n".join(lines) + "\n").encode("utf-8"))
    return destination


def _remove_empty_parent_dirs(path: Path, target: Path) -> None:
    """Remove empty managed-file parents without touching the target repository."""

    current = path.parent
    while current != target:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _marked_block_from(
    text: str, label: str, start_marker: str, end_marker: str
) -> str | None:
    start = text.find(start_marker)
    end = text.find(end_marker)
    if start < 0 and end < 0:
        return None
    if start < 0 or end < start:
        raise CoDevError(f"{label} contains incomplete CoDev markers")
    end += len(end_marker)
    if text.find(start_marker, start + len(start_marker)) >= 0:
        raise CoDevError(f"{label} contains more than one CoDev block")
    return text[start:end]


def _with_marked_block(
    text: str, block: str, label: str, start_marker: str, end_marker: str
) -> str:
    current = _marked_block_from(text, label, start_marker, end_marker)
    newline = "\r\n" if "\r\n" in text else "\n"
    rendered = block.replace("\n", newline)
    if current is None:
        prefix = text.rstrip("\r\n")
        if prefix:
            return prefix + newline * 2 + rendered + newline
        return rendered + newline
    return text.replace(current, rendered, 1)


def _without_marked_block(
    text: str, label: str, start_marker: str, end_marker: str
) -> str:
    current = _marked_block_from(text, label, start_marker, end_marker)
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


def _agent_block_from(text: str) -> str | None:
    return _marked_block_from(text, "AGENTS.md", AGENTS_START, AGENTS_END)


def _with_agent_block(text: str, block: str) -> str:
    return _with_marked_block(text, block, "AGENTS.md", AGENTS_START, AGENTS_END)


def _without_agent_block(text: str) -> str:
    return _without_marked_block(text, "AGENTS.md", AGENTS_START, AGENTS_END)


def _gitignore_block_from(text: str) -> str | None:
    return _marked_block_from(text, ".gitignore", GITIGNORE_START, GITIGNORE_END)


def _with_gitignore_block(text: str, block: str) -> str:
    return _with_marked_block(text, block, ".gitignore", GITIGNORE_START, GITIGNORE_END)


def _without_gitignore_block(text: str) -> str:
    return _without_marked_block(text, ".gitignore", GITIGNORE_START, GITIGNORE_END)


def _sync_gitignore_block(target: Path, old_hash: str | None, plan: Plan) -> None:
    """Add, update, or leave alone the managed `.gitignore` block.

    `old_hash` is the hash recorded in the lock file, or None when this
    integration has never been recorded for this install (a fresh `init`,
    or an `update` of an install that predates this feature) -- in both
    cases an absent or matching block is integrated fresh rather than
    treated as a conflict.
    """
    path = target / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        current = _gitignore_block_from(existing)
    except CoDevError as error:
        plan.operations.append(Operation("conflict", ".gitignore", str(error)))
        return
    new_hash = _block_hash(GITIGNORE_BLOCK)
    if current is None:
        if old_hash is not None:
            plan.operations.append(
                Operation("conflict", ".gitignore", "managed ignore block is missing")
            )
            return
        plan.writes[path] = _with_gitignore_block(existing, GITIGNORE_BLOCK).encode(
            "utf-8"
        )
        plan.operations.append(
            Operation("integrate", ".gitignore", "append escalation-log ignore rule")
        )
        return
    current_hash = _block_hash(current)
    if current_hash == new_hash:
        plan.operations.append(Operation("keep", ".gitignore", "ignore rule current"))
    elif old_hash is not None and current_hash == old_hash:
        plan.operations.append(Operation("update", ".gitignore", "ignore block"))
        plan.writes[path] = _with_gitignore_block(existing, GITIGNORE_BLOCK).encode(
            "utf-8"
        )
    else:
        plan.operations.append(
            Operation("conflict", ".gitignore", "different CoDev block exists")
        )


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
    programming_language: str,
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
        "programming_language": programming_language,
        "files": {path: _sha256(files[path]) for path in sorted(files)},
        "integrations": {
            "agents_block_hash": _block_hash(AGENTS_BLOCK),
            "gitignore_block_hash": _block_hash(GITIGNORE_BLOCK),
            "opencode_default_agent_managed": default_agent_managed,
            "opencode_agent_hashes": dict(sorted(managed_opencode_agents.items())),
            "opencode_schema_managed": opencode_schema_managed,
            "opencode_agent_container_managed": opencode_agent_container_managed,
            "opencode_config_file_managed": opencode_config_file_managed,
        },
    }


def plan_init(
    target: Path,
    platforms: Iterable[str] = ("all",),
    programming_language: str = "none",
) -> Plan:
    target = target.resolve()
    if (target / Path(LOCK_PATH.as_posix())).exists():
        raise CoDevError("CoDev is already installed; use diff or update")
    selected = normalize_platforms(platforms)
    selected_language = normalize_programming_language(programming_language)
    files = _bundle_files(selected, selected_language)
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

    _sync_gitignore_block(target, None, plan)

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
        programming_language=selected_language,
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


def _audit_skill_language(path: str) -> str | None:
    for language, prefix in AUDIT_SKILL_PREFIXES.items():
        if path.startswith(prefix):
            return language
    return None


def plan_update(
    target: Path,
    platforms: Iterable[str] | None = None,
    *,
    programming_language: str | None = None,
) -> Plan:
    target = target.resolve()
    lock = _read_lock(target)
    selected = normalize_platforms(lock.get("platforms", []))
    if platforms is not None:
        selected = normalize_platforms((*selected, *platforms))
    selected_language = normalize_programming_language(
        programming_language or lock.get("programming_language")
    )
    new_files = _bundle_files(selected, selected_language)
    old_files = lock["files"]
    valid_entries = all(
        isinstance(path, str) and isinstance(value, str)
        for path, value in old_files.items()
    )
    if not valid_entries:
        raise CoDevError("lock file contains an invalid managed-file entry")

    # A file whose bundle path changed (e.g. a relocation like ai-agent-
    # guidelines.md's move to .codev/for-ai/) looks identical, from this old
    # path's point of view, to a file upstream genuinely removed: neither
    # exists in new_files under the old name. Distinguish them by content
    # hash so a clean rename deletes the stale copy instead of leaving an
    # orphaned duplicate that nothing manages or updates again.
    new_hashes: dict[str, str] = {
        new_relative: _sha256(new_content)
        for new_relative, new_content in new_files.items()
    }
    moved_to_by_old_hash: dict[str, list[str]] = {}
    for new_relative, new_hash in new_hashes.items():
        moved_to_by_old_hash.setdefault(new_hash, []).append(new_relative)

    plan = Plan()
    for relative in sorted(set(old_files) | set(new_files)):
        destination = target / Path(relative)
        old_hash = old_files.get(relative)
        content = new_files.get(relative)
        if content is None:
            candidates = moved_to_by_old_hash.get(old_hash, []) if old_hash else []
            if len(candidates) == 1 and destination.is_file():
                if _sha256(destination.read_bytes()) == old_hash:
                    plan.deletions.add(destination)
                    plan.operations.append(
                        Operation("remove", relative, f"relocated to {candidates[0]}")
                    )
                    continue
                plan.operations.append(
                    Operation(
                        "retire",
                        relative,
                        f"relocated to {candidates[0]} upstream, but this copy "
                        "has local changes; retained here for manual "
                        "reconciliation",
                    )
                )
                continue
            audit_language = _audit_skill_language(relative)
            if audit_language is not None and audit_language != selected_language:
                if not destination.is_file():
                    plan.operations.append(
                        Operation("conflict", relative, "managed skill is missing")
                    )
                elif _sha256(destination.read_bytes()) == old_hash:
                    plan.deletions.add(destination)
                    plan.operations.append(Operation("remove", relative))
                else:
                    plan.operations.append(
                        Operation(
                            "conflict", relative, "managed skill has local changes"
                        )
                    )
                continue
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
                    Operation(
                        "conflict",
                        relative,
                        "new bundle file collides locally",
                        new_content=content,
                    )
                )
            continue
        if not destination.is_file():
            plan.operations.append(
                Operation(
                    "conflict",
                    relative,
                    "managed file is missing or not a file",
                    new_content=content,
                )
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
                Operation(
                    "conflict",
                    relative,
                    "managed file has local changes",
                    new_content=content,
                )
            )
        else:
            plan.operations.append(
                Operation(
                    "conflict",
                    relative,
                    "local and upstream changes overlap",
                    new_content=content,
                )
            )

    integrations = lock.get("integrations")
    if not isinstance(integrations, dict):
        raise CoDevError("lock file contains invalid integrations")
    old_block_hash = integrations.get("agents_block_hash")
    if not isinstance(old_block_hash, str):
        raise CoDevError("lock file has no valid AGENTS.md block hash")
    _replace_agent_block_for_update(target, old_block_hash, plan)

    old_gitignore_hash = integrations.get("gitignore_block_hash")
    if old_gitignore_hash is not None and not isinstance(old_gitignore_hash, str):
        raise CoDevError("lock file has an invalid gitignore block hash")
    _sync_gitignore_block(target, old_gitignore_hash, plan)

    default_managed = bool(integrations.get("opencode_default_agent_managed"))
    schema_managed = bool(integrations.get("opencode_schema_managed"))
    agent_container_managed = bool(integrations.get("opencode_agent_container_managed"))
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
    conflicted_relatives = {
        item.path for item in plan.operations if item.kind == "conflict"
    }
    lockable_files = {
        relative: content
        for relative, content in new_files.items()
        if relative not in conflicted_relatives
    }
    plan.lock = _new_lock(
        selected,
        lockable_files,
        programming_language=selected_language,
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
        raise CoDevError(
            f"cannot remove managed values from {path}: {error}"
        ) from error
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
    if not all(
        isinstance(path, str) and isinstance(value, str)
        for path, value in files.items()
    ):
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
                        Operation(
                            "conflict", "AGENTS.md", "managed policy block was modified"
                        )
                    )
                else:
                    plan.writes[agents_path] = _without_agent_block(
                        agents_path.read_text(encoding="utf-8")
                    ).encode("utf-8")
                    plan.operations.append(
                        Operation(
                            "integrate", "AGENTS.md", "remove managed policy block"
                        )
                    )

    gitignore_path = target / ".gitignore"
    if gitignore_path.exists():
        try:
            gitignore_block = _gitignore_block_from(
                gitignore_path.read_text(encoding="utf-8")
            )
        except CoDevError as error:
            plan.operations.append(Operation("conflict", ".gitignore", str(error)))
        else:
            expected_gitignore_hash = integrations.get("gitignore_block_hash")
            if gitignore_block is not None and isinstance(expected_gitignore_hash, str):
                if _block_hash(gitignore_block) != expected_gitignore_hash:
                    plan.operations.append(
                        Operation(
                            "conflict",
                            ".gitignore",
                            "managed ignore block was modified",
                        )
                    )
                else:
                    plan.writes[gitignore_path] = _without_gitignore_block(
                        gitignore_path.read_text(encoding="utf-8")
                    ).encode("utf-8")
                    plan.operations.append(
                        Operation(
                            "integrate", ".gitignore", "remove managed ignore block"
                        )
                    )

    selected = normalize_platforms(lock.get("platforms", []))
    if "opencode" in selected:
        try:
            opencode_content, remove_opencode_config, detail = (
                _prepare_opencode_removal(target, integrations)
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


def plan_adapter_remove(target: Path, platform: str) -> Plan:
    """Preflight removal of a single adapter from an existing installation."""

    if platform not in VALID_PLATFORMS:
        raise CoDevError(f"unknown platform: {platform!r}")

    target = target.resolve()
    lock = _read_lock(target)
    installed = lock.get("platforms", [])
    if platform not in installed:
        raise CoDevError(
            f"adapter {platform!r} is not installed; "
            f"installed adapters: {', '.join(installed)}"
        )
    if len(installed) < 2:
        raise CoDevError(
            f"{platform!r} is the only installed adapter; "
            "use 'codev remove' to uninstall completely"
        )

    remaining = tuple(p for p in installed if p != platform)
    programming_language = lock.get("programming_language", "none")
    new_files = _bundle_files(remaining, programming_language)

    files = lock["files"]
    if not all(
        isinstance(path, str) and isinstance(value, str)
        for path, value in files.items()
    ):
        raise CoDevError("lock file contains an invalid managed-file entry")
    integrations = lock.get("integrations")
    if not isinstance(integrations, dict):
        raise CoDevError("lock file contains invalid integrations")

    plan = Plan()
    for relative, expected_hash in sorted(files.items()):
        if relative in new_files:
            continue
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

    if platform == "opencode":
        try:
            opencode_content, remove_opencode_config, detail = (
                _prepare_opencode_removal(target, integrations)
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

    managed_opencode_agents: dict[str, str] = {}
    schema_managed = False
    agent_container_managed = False
    config_file_managed = False
    default_agent_managed = False
    if "opencode" in remaining:
        managed_opencode_agents = integrations.get("opencode_agent_hashes", {})
        if not isinstance(managed_opencode_agents, dict) or not all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in managed_opencode_agents.items()
        ):
            raise CoDevError("lock file has invalid OpenCode agent hashes")
        schema_managed = bool(integrations.get("opencode_schema_managed"))
        agent_container_managed = bool(
            integrations.get("opencode_agent_container_managed")
        )
        config_file_managed = bool(integrations.get("opencode_config_file_managed"))
        default_agent_managed = bool(integrations.get("opencode_default_agent_managed"))
    plan.lock = _new_lock(
        remaining,
        new_files,
        programming_language=programming_language,
        default_agent_managed=default_agent_managed,
        managed_opencode_agents=managed_opencode_agents,
        opencode_schema_managed=schema_managed,
        opencode_agent_container_managed=agent_container_managed,
        opencode_config_file_managed=config_file_managed,
    )
    return plan


def apply_plan(
    target: Path, plan: Plan, resolutions: dict[str, Resolution] | None = None
) -> list[Operation]:
    """Write `plan` to `target`. Returns conflicts left unresolved.

    With no `resolutions` (the default), behaves exactly as before: any
    conflict refuses to write anything at all. Passing `resolutions` (from a
    conflict wizard or a non-interactive `--on-conflict` policy) instead
    resolves each conflicted path individually -- OVERRIDE adopts upstream,
    KEEP adopts the current local content as the new accepted baseline, COPY
    writes upstream's content beside the file without touching it, and
    DELETE removes a local file upstream no longer ships. A path with no
    resolution, or resolved SKIP, is left untouched and reported back so the
    caller can tell the user what's still outstanding; everything else in
    the plan -- clean operations and every other resolved conflict -- is
    still applied together.
    """
    if resolutions is None:
        if plan.conflicts:
            raise CoDevError("cannot apply a plan that contains conflicts")
        resolutions = {}
    if plan.lock is None and not plan.remove_lock:
        raise CoDevError("installation plan has no lock state")
    target = target.resolve()
    writes = dict(plan.writes)
    deletions = set(plan.deletions)
    lock = plan.lock
    unresolved: list[Operation] = []
    for op in plan.conflicts:
        choice = resolutions.get(op.path, Resolution.SKIP)
        destination = target / Path(op.path)
        if choice == Resolution.SKIP:
            unresolved.append(op)
        elif choice == Resolution.OVERRIDE:
            if op.new_content is None:
                raise CoDevError(f"{op.path}: no upstream content to override with")
            writes[destination] = op.new_content
            if lock is not None:
                lock["files"][op.path] = _sha256(op.new_content)
        elif choice == Resolution.KEEP:
            if destination.is_file() and lock is not None:
                lock["files"][op.path] = _sha256(destination.read_bytes())
        elif choice == Resolution.COPY:
            if op.new_content is None:
                raise CoDevError(f"{op.path}: no upstream content to copy")
            writes[copy_sidecar_path(destination)] = op.new_content
            unresolved.append(op)
        elif choice == Resolution.DELETE:
            if destination.is_file():
                deletions.add(destination)
        else:
            raise CoDevError(f"unknown conflict resolution: {choice!r}")

    for path, content in sorted(writes.items(), key=lambda item: str(item[0])):
        _atomic_write(path, content)
    for path in sorted(deletions, key=str):
        path.unlink()
    for path in sorted(deletions, key=str):
        _remove_empty_parent_dirs(path, target)
    if plan.remove_lock:
        lock_path = target / Path(LOCK_PATH.as_posix())
        lock_path.unlink(missing_ok=True)
        _remove_empty_parent_dirs(lock_path, target)
        return unresolved
    assert lock is not None
    lock_content = (json.dumps(lock, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    _atomic_write(target / Path(LOCK_PATH.as_posix()), lock_content)
    return unresolved


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

    gitignore_hash = integrations.get("gitignore_block_hash")
    if isinstance(gitignore_hash, str):
        gitignore_path = target / ".gitignore"
        if not gitignore_path.is_file():
            issues.append(".gitignore is missing its managed CoDev block")
        else:
            try:
                gitignore_block = _gitignore_block_from(
                    gitignore_path.read_text(encoding="utf-8")
                )
            except CoDevError as error:
                issues.append(str(error))
            else:
                if gitignore_block is None:
                    issues.append(".gitignore has no managed CoDev block")
                elif _block_hash(gitignore_block) != gitignore_hash:
                    issues.append("the managed .gitignore block has local changes")

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
                    if (
                        not isinstance(current, dict)
                        or _json_hash(current) != expected_hash
                    ):
                        issues.append(
                            f"managed OpenCode agent has local changes: {name}"
                        )

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
