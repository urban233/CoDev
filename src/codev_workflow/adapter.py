"""Conformance checks for installed platform adapters.

Verifies structural parity across the four platform adapters without
requiring them to be rendered from one source yet: every role file must
reference the `codev task` lifecycle wiring, must not resurrect the retired
P0-P3 finding scale, and must not grant unrestricted shell execution. This is
a second line of defense against cross-adapter drift, not a substitute for
eventually rendering adapters from one config source.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

_OUTER_LOOP_ROLES = (
    "outer-loop-runner",
    "correctness-tests-specialist",
    "security-data-specialist",
    "concurrency-specialist",
    "architecture-maintainability-specialist",
    "rollout-specialist",
)


def _role_paths(directory: str, extension: str) -> dict[str, str]:
    # code-audit (and its code-audit-gate counterpart, ADR-0015) are
    # deliberately absent here: both are templated ({{LANGUAGE_INSTRUCTIONS}}
    # etc.), so the raw bundle only ever has a .template source, never the
    # rendered filename this function's paths assume -- verify_adapter's
    # bundle-parity test runs directly against the raw bundle. Their rendered
    # output is instead checked where it's actually produced, by the
    # installer's own per-platform agent-rendering tests.
    paths = {
        "orchestrator": f"{directory}/orchestrator.{extension}",
        "planner": f"{directory}/planner.{extension}",
        "builder": f"{directory}/builder.{extension}",
        "reviewer": f"{directory}/reviewer.{extension}",
        "lightweight-reviewer": f"{directory}/lightweight-reviewer.{extension}",
    }
    for role in _OUTER_LOOP_ROLES:
        paths[role] = f"{directory}/{role}.{extension}"
    return paths


ADAPTER_ROLE_PATHS: dict[str, dict[str, str]] = {
    "opencode": _role_paths(".opencode/agents", "md"),
    "codex": _role_paths(".codex/agents", "toml"),
    "junie": _role_paths(".junie/agents", "md"),
    "antigravity": _role_paths(".agents/agents", "md"),
}

_REQUIRED_MARKERS: dict[str, tuple[str, ...]] = {
    "orchestrator": (
        "codev task start",
        "codev task check",
        "codev git open-pr",
        "--github-issue",
        "codev git issue-create",
        "--no-github-issue",
    ),
    "planner": ("codev git issue-create",),
    "builder": ("codev task record",),
    "reviewer": ("codev task record",),
    "lightweight-reviewer": ("codev task record",),
    "outer-loop-runner": (
        "codev task record",
        "codev task triage",
        "codev task waive",
        "codev task reopen",
        "--selection",
        "codev git mark-ready",
    ),
    "correctness-tests-specialist": ("expansion_reason",),
    "security-data-specialist": ("expansion_reason",),
    "concurrency-specialist": ("expansion_reason",),
    "architecture-maintainability-specialist": ("expansion_reason",),
    "rollout-specialist": ("expansion_reason",),
}

_FORBIDDEN_MARKERS: tuple[str, ...] = ("P0 through P3",)

_UNRESTRICTED_BASH_MARKERS: tuple[str, ...] = ('"*": allow', "'*': allow")

# ADR-0002: raw git/GitHub mutation must stay denied everywhere; `codev git`
# is the only guarded path to committing, pushing, or opening a pull request.
_RAW_MUTATION_MARKERS: tuple[str, ...] = (
    '"git push*": allow',
    "'git push*': allow",
    '"git commit*": allow',
    "'git commit*': allow",
)

# `codev git open-pr` renders recorded task evidence into the repository PR
# template when no `--body`/`--body-file` is given. An agent hardcoding a body
# placeholder would bypass that guarded rendering path.
_HANDWRITTEN_PR_BODY_MARKERS: tuple[str, ...] = ("--body <body>",)

# ADR-0021: OpenCode's per-subagent `task` permission block is the only
# mechanical backstop against outer-loop-runner silently skipping the human
# specialist-selection menu (ADR-0016/0018) -- these five must stay "ask",
# never regress to "allow", or the one available guardrail disappears again
# without anything noticing.
_SPECIALIST_ALLOW_MARKERS: tuple[str, ...] = (
    "correctness-tests-specialist: allow",
    "security-data-specialist: allow",
    "concurrency-specialist: allow",
    "architecture-maintainability-specialist: allow",
    "rollout-specialist: allow",
)


class AdapterVerificationError(Exception):
    """Raised when a platform cannot be verified at all."""


@dataclass(frozen=True)
class RoleFinding:
    role: str
    path: str
    ok: bool
    problems: tuple[str, ...]


@dataclass(frozen=True)
class VerificationResult:
    platform: str
    findings: tuple[RoleFinding, ...]

    @property
    def ok(self) -> bool:
        return all(finding.ok for finding in self.findings)


def verify_adapter(platform: str, *, target: Path) -> VerificationResult:
    role_paths = ADAPTER_ROLE_PATHS.get(platform)
    if role_paths is None:
        raise AdapterVerificationError(f"unknown platform: {platform!r}")

    findings: list[RoleFinding] = []
    for role, relative in sorted(role_paths.items()):
        path = target / relative
        problems: list[str] = []
        if not path.is_file():
            findings.append(RoleFinding(role, relative, False, ("missing file",)))
            continue

        text = path.read_text(encoding="utf-8")

        if relative.endswith(".toml"):
            try:
                tomllib.loads(text)
            except tomllib.TOMLDecodeError as error:
                problems.append(f"invalid TOML: {error}")

        for marker in _REQUIRED_MARKERS[role]:
            if marker not in text:
                problems.append(f"missing required reference: {marker!r}")
        for marker in _FORBIDDEN_MARKERS:
            if marker in text:
                problems.append(f"contains a retired pattern: {marker!r}")
        for marker in _UNRESTRICTED_BASH_MARKERS:
            if marker in text:
                problems.append(f"grants unrestricted shell execution: {marker!r}")
        for marker in _RAW_MUTATION_MARKERS:
            if marker in text:
                problems.append(
                    f"grants raw git mutation instead of the guarded `codev git` "
                    f"surface: {marker!r}"
                )
        for marker in _HANDWRITTEN_PR_BODY_MARKERS:
            if marker in text:
                problems.append(
                    f"hardcodes a PR body placeholder instead of relying on "
                    f"`codev git open-pr`'s template-aware rendering: {marker!r}"
                )
        for marker in _SPECIALIST_ALLOW_MARKERS:
            if marker in text:
                problems.append(
                    f"grants unconfirmed specialist dispatch instead of the "
                    f"ADR-0021 permission gate: {marker!r}"
                )

        findings.append(RoleFinding(role, relative, not problems, tuple(problems)))

    return VerificationResult(platform, tuple(findings))
