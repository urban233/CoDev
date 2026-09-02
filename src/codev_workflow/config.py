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
"""Layered configuration resolution for CoDev (flags, env, project, global)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from codev_workflow.installer import _atomic_write

CONFIG_SCHEMA_VERSION = 1
PROJECT_CONFIG_RELATIVE = PurePosixPath(".codev/config.toml")
ENV_PREFIX = "CODEV_"

# Populated as features grow their own config keys (adapter defaults, round
# limits, and so on).
DEFAULTS: dict[str, str] = {
    # "trunk" (default) slices tasks at engineering-dependency boundaries,
    # contained behind a flag/config guard when incomplete; "feature-branch"
    # is the explicit override, with no containment expectation. See
    # ADR-0033.
    "git.workflow": "trunk",
    # A prompt to reconsider slicing, not a hard limit -- see
    # docs/features/small-prs/design.md.
    #
    # This began at 400, taken from Google's published median change-list
    # guidance, and that turned out to be too strict in practice: it fired on
    # changes that were genuinely one coherent purpose, mostly because a real
    # change carries its tests with it. Size is one input into whether a
    # change is reviewable, not the input -- a 500-line change doing one
    # thing is easier to review than a 300-line change spanning four
    # subsystems, and a line count cannot tell those apart. The threshold is
    # set where it catches the genuinely unreviewable rather than the merely
    # substantial.
    "review.max_lines": "600",
    "review.max_files": "8",
    # ADR-0037: one approving review from a human who is neither the task
    # owner nor a bot. Two only where the risk warrants it -- requiring two
    # everywhere will not survive contact with a team of eight, and Google
    # does not require it either.
    "review.required_approvals": "1",
    # Comma-separated globs whose changes raise the requirement to two.
    "review.sensitive_paths": "",
    # ADR-0038: comma-separated globs the loop must not build unattended.
    # Reaching one drops the slice to pair mode for the rest of the round.
    "review.pair_paths": "",
}


class ConfigError(Exception):
    """Raised for invalid or unreadable CoDev configuration."""


@dataclass(frozen=True)
class ResolvedValue:
    value: str
    source: str  # "flag" | "env" | "project" | "global" | "default"


def _project_config_path(target: Path) -> Path:
    return target / Path(PROJECT_CONFIG_RELATIVE.as_posix())


def _global_config_path() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "codev" / "config.toml"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "codev" / "config.toml"


def _read_config(path: Path) -> tuple[int, dict[str, str]]:
    if not path.exists():
        return CONFIG_SCHEMA_VERSION, {}
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in {path}: {error}") from error
    except OSError as error:
        raise ConfigError(f"cannot read {path}: {error}") from error

    schema_version = raw.get("schema_version", CONFIG_SCHEMA_VERSION)
    if schema_version != CONFIG_SCHEMA_VERSION:
        raise ConfigError(
            f"unsupported config schema {schema_version!r} in {path}; "
            "install a compatible CoDev version"
        )
    values = raw.get("values", {})
    if not isinstance(values, dict):
        raise ConfigError(f"{path} has an invalid [values] table")
    return schema_version, {str(key): str(val) for key, val in values.items()}


def _toml_scalar(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _write_config(path: Path, values: dict[str, str]) -> None:
    lines = [f"schema_version = {CONFIG_SCHEMA_VERSION}", "", "[values]"]
    for key in sorted(values):
        # Quote the key too, not only the value: an unquoted key containing a
        # dot (e.g. "git.pr_base") is a TOML *dotted key*, parsed as a nested
        # table rather than one literal key -- it would silently fail to
        # round-trip through _read_config below. Quoting keeps any key name
        # literal regardless of its characters.
        lines.append(f"{_toml_scalar(key)} = {_toml_scalar(values[key])}")
    content = ("\n".join(lines) + "\n").encode("utf-8")
    _atomic_write(path, content)


def resolve(
    key: str, *, target: Path, override: str | None = None
) -> ResolvedValue | None:
    """Resolve one config key: flag > env > project > global > default."""
    if override is not None:
        return ResolvedValue(override, "flag")

    env_key = ENV_PREFIX + key.upper().replace("-", "_")
    if env_key in os.environ:
        return ResolvedValue(os.environ[env_key], "env")

    _, project_values = _read_config(_project_config_path(target))
    if key in project_values:
        return ResolvedValue(project_values[key], "project")

    _, global_values = _read_config(_global_config_path())
    if key in global_values:
        return ResolvedValue(global_values[key], "global")

    if key in DEFAULTS:
        return ResolvedValue(DEFAULTS[key], "default")

    return None


def set_value(
    key: str, value: str, *, target: Path, global_scope: bool = False
) -> Path:
    """Write one key to the project or global config file; returns its path."""
    path = _global_config_path() if global_scope else _project_config_path(target)
    _, values = _read_config(path)
    values[key] = value
    _write_config(path, values)
    return path


def list_values(*, target: Path) -> dict[str, ResolvedValue]:
    """Resolve every key known to project config, global config, or defaults."""
    _, project_values = _read_config(_project_config_path(target))
    _, global_values = _read_config(_global_config_path())
    known_keys = set(project_values) | set(global_values) | set(DEFAULTS)
    resolved: dict[str, ResolvedValue] = {}
    for key in known_keys:
        value = resolve(key, target=target)
        if value is not None:
            resolved[key] = value
    return resolved
