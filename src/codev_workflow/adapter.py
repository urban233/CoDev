"""Conformance checks for installed platform adapters.

Verifies structural parity across the four platform adapters without
requiring them to be rendered from one source yet: every role file must
reference the `codev work` lifecycle wiring, must not resurrect the retired
P0-P3 finding scale, and must not grant unrestricted shell execution. This is
a second line of defense against cross-adapter drift, not a substitute for
eventually rendering adapters from one config source.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

ADAPTER_ROLE_PATHS: dict[str, dict[str, str]] = {
    "opencode": {
        "orchestrator": ".opencode/agents/orchestrator.md",
        "builder": ".opencode/agents/builder.md",
        "reviewer": ".opencode/agents/reviewer.md",
    },
    "codex": {
        "orchestrator": ".codex/agents/orchestrator.toml",
        "builder": ".codex/agents/builder.toml",
        "reviewer": ".codex/agents/reviewer.toml",
    },
    "junie": {
        "orchestrator": ".junie/agents/orchestrator.md",
        "builder": ".junie/agents/builder.md",
        "reviewer": ".junie/agents/reviewer.md",
    },
    "antigravity": {
        "orchestrator": ".agents/agents/orchestrator.md",
        "builder": ".agents/agents/builder.md",
        "reviewer": ".agents/agents/reviewer.md",
    },
}

_REQUIRED_MARKERS: dict[str, tuple[str, ...]] = {
    "orchestrator": ("codev work start", "codev work check"),
    "builder": ("codev work record",),
    "reviewer": ("codev work record",),
}

_FORBIDDEN_MARKERS: tuple[str, ...] = ("P0 through P3",)

_UNRESTRICTED_BASH_MARKERS: tuple[str, ...] = ('"*": allow', "'*': allow")


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

        findings.append(RoleFinding(role, relative, not problems, tuple(problems)))

    return VerificationResult(platform, tuple(findings))
