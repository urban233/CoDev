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
"""Conformance checks for installed platform adapters.

Verifies structural parity across the full-workflow platform adapters
(OpenCode, Claude Code) without requiring them to be rendered from one source
yet: every role file must reference the `codev task` lifecycle wiring, must
not resurrect the retired P0-P3 finding scale, and must not grant
unrestricted shell execution. This is a second line of defense against
cross-adapter drift, not a substitute for eventually rendering adapters from
one config source.

Junie and Antigravity are a narrower tier (ADR-0031): a single bounded-edit
`assistant` role with no task-lifecycle integration. They still go through
the same forbidden-pattern checks below (no unrestricted shell, no raw git
mutation), just with no required markers to enforce.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

_OUTER_LOOP_ROLES = (
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
    #
    # `lead` and `outer-loop-runner` are deliberately absent too, and for the
    # first time not because they render elsewhere but because neither is an
    # agent any more (ADR-0044): coordination is what
    # `.codev/for-ai/ai-agent-guidelines.md` already says to every ordinary
    # session, and the outer loop's protocol is the `outer-loop-review`
    # skill, loaded on demand rather than dispatched.
    paths = {
        "builder": f"{directory}/builder.{extension}",
        "reviewer": f"{directory}/reviewer.{extension}",
        "lightweight-reviewer": f"{directory}/lightweight-reviewer.{extension}",
    }
    for role in _OUTER_LOOP_ROLES:
        paths[role] = f"{directory}/{role}.{extension}"
    return paths


ADAPTER_ROLE_PATHS: dict[str, dict[str, str]] = {
    "opencode": _role_paths(".opencode/agents", "md"),
    "claude": _role_paths(".claude/agents", "md"),
    # Junie and Antigravity are the narrow tier: a single bounded-edit
    # `assistant` role, not the full workflow (see ADR-0031) -- no outer-loop
    # roles, no code-audit, no task-lifecycle markers to require.
    "junie": {"assistant": ".junie/agents/assistant.md"},
    "antigravity": {"assistant": ".agents/agents/assistant.md"},
}

_REQUIRED_MARKERS: dict[str, tuple[str, ...]] = {
    "builder": ("codev task record",),
    "reviewer": ("codev task record",),
    "lightweight-reviewer": ("codev task record",),
    "correctness-tests-specialist": ("expansion_reason",),
    "security-data-specialist": ("expansion_reason",),
    "concurrency-specialist": ("expansion_reason",),
    "architecture-maintainability-specialist": ("expansion_reason",),
    "rollout-specialist": ("expansion_reason",),
    # The narrow Junie/Antigravity `assistant` role is deliberately decoupled
    # from the task lifecycle -- it never calls `codev task`/`codev git`, so
    # there is no required marker to check for.
    "assistant": (),
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

# ADR-0021 / ADR-0044: nothing scanned here carries an OpenCode `task`
# permission block for the five specialists any more -- that guarantee now
# lives in the `outer-loop-review` skill's own explicit selection question,
# not in agent frontmatter (ADR-0044). This stays as a general safety net: a
# future role file that reintroduces one of these five as `allow` is still
# worth catching, even though nothing currently in scope should ever match.
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
