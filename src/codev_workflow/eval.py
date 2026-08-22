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
"""Local task creation and OpenCode skill evaluation."""

from __future__ import annotations

import base64
import contextlib
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from codev_workflow.installer import AGENTS_END, AGENTS_START


class EvaluationError(RuntimeError):
    """An invalid input or infrastructure failure."""


EXCLUDED_NAMES = frozenset({".env", ".git", ".venv", "node_modules"})
_SECRET_SUFFIXES = (".pem", ".key")
_SECRET_NAMES = frozenset(
    {".aws", "credentials", "credentials.json", "token", "token.json"}
)
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_JUDGE_FIELDS = {"schema_version", "verdict", "summary", "findings"}
# _valid_judge() requires exactly this shape. The prompt must spell it out:
# without it, the judge has no way to know what "the required JSON" means
# (nothing else staged into judge_dir documents the schema), and in practice
# spends its whole turn reading files instead of ever producing an answer --
# reproduced directly against a real model, not a guess.
_JUDGE_PROMPT = (
    "Review rubric.md and the other files in this directory as observable "
    "evidence. Reply with exactly one JSON object and nothing else -- no "
    "markdown fences, no commentary before or after it -- matching this "
    "schema: "
    '{"schema_version": 1, "verdict": "pass" or "fail", "summary": '
    '"one paragraph", "findings": [{"criterion": "short id", "verdict": '
    '"pass" or "fail", "evidence": "specific evidence from the files"}]}. '
    "Include one findings entry per rubric criterion."
)
_COMMIT_MARKER = ".codev-eval-commit.json"
_TRANSACTION_MARKER = ".codev-eval-transaction.json"
_PRIVATE_OWNER_MARKER = ".codev-eval-owner.json"
_PRIVATE_TRANSACTION_MARKER = ".codev-eval-transaction.json"
_PRIVATE_PREFIX = ".codev-eval-private-"
_PRIVATE_TRANSACTIONS: dict[str, tuple[Path, str]] = {}
_SECRET_OUTPUT = re.compile(
    r"(?i)(aws_secret_access_key|aws_access_key_id|password|passwd|token|secret|credential|api[_-]?key|authorization)(\s*[:=]\s*)([^\s,;&]+)"
)
_BEARER_OUTPUT = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_SECRET_CONTENT = re.compile(
    r"(?is)(-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----|"
    r"(?:api[_-]?key|apiToken|accessToken|authToken|privateKey|password|passwd|"
    r"secret|credential|token|key)\s*[=:]\s*[\"']?([^\s,;&\"']{4,})[\"']?)"
)
_SECRET_JSON = re.compile(
    r"(?i)([\"'](?P<key>[^\"']+)[\"']\s*:\s*)([\"'])([^\"'\r\n]*)(\3)"
)
_SECRET_ESCAPED_JSON = re.compile(
    r'(?i)(\\?"(?P<key>[^"\\]+)\\?"\s*:\s*\\?")([^"\\{]+)(\\?")'
)
_URL_OUTPUT = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


def _secret_key(key: str) -> bool:
    parts: list[str] = []
    for segment in re.split(r"[_-]+", key):
        parts.extend(
            re.findall(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|\d+", segment) or [segment]
        )
    parts = [part.lower() for part in parts]
    sensitive = {"password", "passwd", "token", "secret", "credential"}
    if any(part in sensitive for part in parts):
        return True
    return any(
        left in {"api", "access", "auth", "private", "client", "aws"}
        and right in {"key", "token", "secret", "access"}
        for left, right in zip(parts, parts[1:], strict=False)
    )


def _sanitize_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED_SECRET]"
            if isinstance(key, str) and _secret_key(key)
            else _sanitize_json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, str):
        value = _sanitize_json_string(value)
        try:
            nested = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return value
        if isinstance(nested, (dict, list)):
            return json.dumps(_sanitize_json_value(nested), ensure_ascii=False)
    return value


def _sanitize_json_string(value: str) -> str:
    """Remove credentials from URL user-info and sensitive query parameters."""
    value = _redact_text(value)
    return _sanitize_url(value)


def _sensitive_query_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    if normalized in {
        "token",
        "password",
        "passwd",
        "secret",
        "key",
        "credential",
        "apikey",
    }:
        return True
    return normalized.endswith(
        ("token", "password", "passwd", "secret", "key", "credential")
    ) and normalized not in {"monkey"}


def _sanitize_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if not parsed.scheme or not parsed.netloc:
        return value
    try:
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return value
    if hostname is None:
        return value
    netloc = hostname
    if ":" in hostname and not hostname.startswith("["):
        netloc = f"[{hostname}]"
    if port is not None:
        netloc += f":{port}"
    if parsed.username is not None:
        netloc = f"{parsed.username}:[REDACTED_SECRET]@{netloc}"
    query = [
        (key, "[REDACTED_SECRET]" if _sensitive_query_key(key) else item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit(
        (parsed.scheme, netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _redact_urls(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        trailing = ""
        while token and token[-1] in ".,;:!?)]":
            trailing = token[-1] + trailing
            token = token[:-1]
        return _sanitize_url(token) + trailing

    return _URL_OUTPUT.sub(replace, value)


def _safe_jsonl(value: str) -> str:
    """Return recursively sanitized JSONL, or empty output if it is malformed."""
    lines = [line for line in value.splitlines() if line.strip()]
    if not lines:
        return ""
    try:
        events = [json.loads(line) for line in lines]
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""
    return "".join(
        json.dumps(_sanitize_json_value(event), ensure_ascii=False) + "\n"
        for event in events
    )


def _safe_process_output(value: str) -> str:
    """Preserve diagnostics while omitting malformed structured payloads."""
    if not value:
        return ""
    structured = _safe_jsonl(value)
    if structured:
        return structured
    return _redact_text(value)


def _redact_json_match(match: re.Match[str]) -> str:
    if not _secret_key(match.group("key")):
        return match.group(0)
    return f"{match.group(1)}{match.group(3)}[REDACTED_SECRET]{match.group(5)}"


def _redact_escaped_json_match(match: re.Match[str]) -> str:
    if not _secret_key(match.group("key")):
        return match.group(0)
    return f"{match.group(1)}[REDACTED_SECRET]{match.group(4)}"


def _redact_fallback(value: str) -> str:
    urls: list[str] = []

    def protect_url(match: re.Match[str]) -> str:
        urls.append(_sanitize_url(match.group(0)))
        return f"__CODEV_SAFE_URL_{len(urls) - 1}__"

    value = _URL_OUTPUT.sub(protect_url, value)
    value = _SECRET_ESCAPED_JSON.sub(_redact_escaped_json_match, value)
    value = _SECRET_JSON.sub(_redact_json_match, value)
    value = _SECRET_CONTENT.sub("[REDACTED_SECRET]", value)
    value = _SECRET_OUTPUT.sub(r"\1\2[REDACTED]", value)
    value = _BEARER_OUTPUT.sub(r"\1[REDACTED]", value)
    for index, url in enumerate(urls):
        value = value.replace(f"__CODEV_SAFE_URL_{index}__", url)
    return value


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise EvaluationError(f"JSON object required: {path}")
    return value


def _strict(data: dict[str, Any], fields: set[str], path: Path) -> None:
    unknown = set(data) - fields
    if (
        unknown
        or type(data.get("schema_version")) is not int
        or data.get("schema_version") != 1
    ):
        raise EvaluationError(f"invalid schema: {path}")


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvaluationError(f"{label} must be a positive integer")
    return value


def _no_symlink(path: Path, boundary: Path) -> None:
    """Reject symlinks from boundary through path, including path itself."""
    boundary = boundary.absolute()
    path = path.absolute()
    try:
        relative = path.relative_to(boundary)
    except ValueError as exc:
        raise EvaluationError(f"path is outside boundary: {path}") from exc
    if ".." in relative.parts:
        raise EvaluationError(f"path is outside boundary: {path}")
    current = boundary
    if sys.platform == "win32":
        _windows_reparse_safe(current)
    try:
        if stat.S_ISLNK(os.lstat(current).st_mode):
            raise EvaluationError(f"symlinks are not allowed: {current}")
    except FileNotFoundError:
        pass
    for part in relative.parts:
        current /= part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise EvaluationError(f"symlinks are not allowed: {current}")
        if sys.platform == "win32":
            _windows_reparse_safe(current)


def _windows_reparse_safe(path: Path) -> None:
    kernel32 = ctypes.__dict__["WinDLL"]("kernel32", use_last_error=True)
    attributes = kernel32.GetFileAttributesW(str(path))
    if attributes != -1 and attributes & 0x00000400:
        raise EvaluationError(f"reparse points are not allowed: {path}")


def _is_secret_path(relative: Path) -> bool:
    for part in relative.parts:
        lower = part.lower()
        if (
            lower in {name.lower() for name in EXCLUDED_NAMES}
            or lower.startswith(".env")
            or lower in _SECRET_NAMES
            or lower.endswith(_SECRET_SUFFIXES)
            or "credential" in lower
            or "token" in lower
        ):
            return True
    return False


def _redact_text(value: str) -> str:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, UnicodeDecodeError):
        parsed = None
    if isinstance(parsed, (dict, list)):
        sanitized = _sanitize_json_value(parsed)
        if sanitized == parsed:
            return _redact_fallback(value)
        return _redact_fallback(json.dumps(sanitized, ensure_ascii=False))
    lines = value.splitlines(keepends=True)
    if len(lines) > 1:
        sanitized_lines: list[str] = []
        changed = False
        for line in lines:
            ending = "\n" if line.endswith("\n") else ""
            candidate = line[:-1] if ending else line
            try:
                parsed_line = json.loads(candidate)
            except json.JSONDecodeError:
                sanitized_lines.append(line)
                continue
            if isinstance(parsed_line, (dict, list)):
                sanitized_line = _sanitize_json_value(parsed_line)
                if sanitized_line == parsed_line:
                    sanitized_lines.append(line)
                else:
                    sanitized_lines.append(
                        json.dumps(sanitized_line, ensure_ascii=False) + ending
                    )
                    changed = True
            else:
                sanitized_lines.append(line)
        if changed:
            value = "".join(sanitized_lines)
    return _redact_fallback(value)


def _assert_safe_content(value: str, source: Path) -> None:
    if _redact_text(value) != value:
        raise EvaluationError(f"secret-like content is not allowed: {source}")


def _scan_bytes(data: bytes, source: Path) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    _assert_safe_content(text, source)


def _redact_bytes(data: bytes) -> bytes:
    """Redact secret-like text without changing arbitrary binary bytes."""
    try:
        return _redact_text(data.decode("utf-8")).encode("utf-8")
    except UnicodeDecodeError:
        return _redact_text(data.decode("latin-1")).encode("latin-1")


def _redact_diff(value: str) -> str:
    """Remove encoded binary payloads before applying textual redaction."""
    lines = value.splitlines(keepends=True)
    redacted: list[str] = []
    hiding_binary = False
    for line in lines:
        if line.startswith("diff --git "):
            hiding_binary = False
        if hiding_binary:
            continue
        redacted.append(line)
        if line.rstrip("\r\n") == "GIT binary patch":
            redacted.append("[REDACTED_BINARY_CONTENT]\n")
            hiding_binary = True
    return _redact_text("".join(redacted))


def _isolated_env() -> dict[str, str]:
    allowed = {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "TMPDIR",
        "TMP",
        "TEMP",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "OPENCODE_API_KEY",
        "OPENCODE_AUTH_TOKEN",
        "OPENCODE_SERVER_PASSWORD",
        # Carry no secrets, but Windows child processes (Node.js-based CLIs
        # like an npm-installed opencode.CMD in particular) need these just to
        # start; without SystemRoot in the child environment the process
        # fails immediately (observed as exit code 0xC0000409).
        "SystemRoot",
        "windir",
        "SystemDrive",
        "ComSpec",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "OS",
    }
    # Windows environment variable names are case-insensitive at the OS level,
    # but which case a given launcher (PowerShell, cmd.exe, an MSYS shell...)
    # actually hands to os.environ varies (e.g. SystemRoot vs SYSTEMROOT), so
    # match case-insensitively rather than listing every variant by hand.
    allowed_upper = {name.upper() for name in allowed}
    env = {
        key: value for key, value in os.environ.items() if key.upper() in allowed_upper
    }
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
        }
    )
    # Guarantee a working "python"/"python3" for task verifiers by
    # prepending the interpreter actually running CoDev, rather than
    # depending on whatever those bare names happen to resolve to elsewhere
    # on PATH. On Windows in particular, "python3" commonly resolves only to
    # a non-functional Microsoft Store execution-alias stub (prints "Python
    # was not found..." and exits 9009) unless a real interpreter's
    # directory is earlier on PATH -- observed directly, not theoretical.
    interpreter_dir = str(Path(sys.executable).resolve().parent)
    env["PATH"] = interpreter_dir + os.pathsep + env.get("PATH", "")
    return env


_BARE_PYTHON_NAMES = {"python", "python3"}


def _resolve_verifier_command(command: list[str]) -> list[str]:
    """Replace a bare "python"/"python3" verifier command with sys.executable.

    A task's verifier.json is static, portable data with no templating,
    so it can only reasonably assume "some Python is available" -- it can't
    know in advance which one. Prepending sys.executable's directory to PATH
    covers scripts a verifier shells out to internally, but the top-level
    command itself deserves a stronger guarantee: substitute the exact
    interpreter already running CoDev, which is known to work, rather than
    hoping whatever "python3" resolves to elsewhere on PATH does too. On
    Windows in particular, a bare "python3" commonly resolves only to a
    non-functional Microsoft Store execution-alias stub (exit code 9009)
    when no interpreter's own directory happens to be earlier on PATH --
    observed directly against a real install, not theoretical.
    """
    if command and command[0] in _BARE_PYTHON_NAMES:
        return [sys.executable, *command[1:]]
    return command


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        return {
            key: "[REDACTED_SECRET]"
            if isinstance(key, str) and _secret_key(key)
            else _redact_value(item)
            for key, item in value.items()
        }
    return value


def _secret_excludes() -> list[str]:
    return [
        ":(exclude)**/.env*",
        ":(exclude)**/.aws/**",
        ":(exclude)**/*credentials*",
        ":(exclude)**/*token*",
        ":(exclude)**/*.pem",
        ":(exclude)**/*.key",
    ]


def _task_path(target: Path, name: str) -> Path:
    if not _NAME.fullmatch(name):
        raise EvaluationError("invalid task name")
    target = target.resolve()
    tasks = target / ".codev" / "eval" / "tasks"
    _no_symlink(tasks, target)
    root = tasks / name
    _no_symlink(root, target)
    try:
        root.resolve().relative_to(tasks.resolve())
    except ValueError as exc:
        raise EvaluationError("task is outside the tasks directory") from exc
    return root


@dataclass(frozen=True)
class Task:
    root: Path
    name: str
    skill: str
    category: str
    actor_timeout: int
    judge_timeout: int
    # None unless the task opts into Docker isolation (ADR-0027); when set,
    # always {"backend": "docker", "image": "..."} -- CoDev never fills in or
    # defaults the image itself.
    environment: dict[str, str] | None
    # Exactly one of (command, verifier_timeout) or checks is populated --
    # a task declares either a custom verifier.json script or a declarative
    # checks.json, never both. See eval_checks.run_declarative_checks.
    command: list[str] | None
    verifier_timeout: int | None
    checks: list[dict[str, Any]] | None
    prompt: bytes
    rubric: bytes
    prompt_fingerprint: tuple[int, int, int, int]
    rubric_fingerprint: tuple[int, int, int, int]
    prompt_digest: str
    rubric_digest: str


def _file_fingerprint(path: Path) -> tuple[int, int, int, int]:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise EvaluationError(f"task fingerprint is not a regular file: {path}")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _assert_file_snapshot(path: Path, fingerprint: tuple[int, int, int, int]) -> None:
    try:
        current = _file_fingerprint(path)
    except OSError as exc:
        raise EvaluationError(f"task fingerprint changed: {path}") from exc
    if current != fingerprint:
        raise EvaluationError(f"task fingerprint changed: {path}")


def _assert_snapshot_digest(
    path: Path, fingerprint: tuple[int, int, int, int], digest: str
) -> None:
    _assert_file_snapshot(path, fingerprint)
    try:
        current_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise EvaluationError(f"task fingerprint changed: {path}") from exc
    if current_digest != digest:
        raise EvaluationError(f"task fingerprint changed: {path}")


def validate_task(root: Path) -> Task:
    if not root.is_dir() or root.is_symlink():
        raise EvaluationError(f"task does not exist: {root}")
    _no_symlink(root, root.parent.parent.parent)
    required = [
        root / name
        for name in (
            "task.json",
            "prompt.md",
            "rubric.md",
            "repository",
        )
    ]
    for path in required:
        if path.is_symlink() or (path.name != "repository" and not path.is_file()):
            raise EvaluationError(f"symlink is not allowed: {path}")
    verifier_path = root / "verifier.json"
    checks_path = root / "checks.json"
    has_verifier = verifier_path.is_file() and not verifier_path.is_symlink()
    has_checks = checks_path.is_file() and not checks_path.is_symlink()
    if verifier_path.is_symlink() or checks_path.is_symlink():
        raise EvaluationError("symlink is not allowed: verifier.json/checks.json")
    if has_verifier == has_checks:
        raise EvaluationError(
            "a task must declare exactly one of verifier.json or checks.json"
        )
    identity_path = root / "task.json"
    identity_text = identity_path.read_text(encoding="utf-8")
    _assert_safe_content(identity_text, identity_path)
    identity = _json(identity_path)
    _strict(
        identity,
        {
            "schema_version",
            "name",
            "description",
            "skill",
            "category",
            "actor_timeout_seconds",
            "judge_timeout_seconds",
            "environment",
        },
        identity_path,
    )
    name = identity.get("name")
    if not isinstance(name, str) or not name or name != root.name:
        raise EvaluationError("task name must match its directory")
    description = identity.get("description")
    if not isinstance(description, str) or not description.strip():
        raise EvaluationError("task description must be nonempty")
    skill = identity.get("skill")
    if not isinstance(skill, str) or not _NAME.fullmatch(skill):
        raise EvaluationError("task skill must be a nonempty skill-like name")
    category = identity.get("category")
    if not isinstance(category, str) or not _NAME.fullmatch(category):
        raise EvaluationError("task category must be a nonempty skill-like name")
    actor = _positive_int(identity.get("actor_timeout_seconds"), "actor timeout")
    judge = _positive_int(identity.get("judge_timeout_seconds"), "judge timeout")
    environment = identity.get("environment")
    if environment is not None and (
        not isinstance(environment, dict)
        or set(environment) != {"backend", "image"}
        or environment.get("backend") != "docker"
        or not isinstance(environment.get("image"), str)
        or not environment["image"]
    ):
        raise EvaluationError(
            'task environment must be {"backend": "docker", "image": "..."}'
        )
    snapshots: dict[str, tuple[bytes, tuple[int, int, int, int]]] = {}
    for filename in ("prompt.md", "rubric.md"):
        try:
            content_path = root / filename
            content_bytes = content_path.read_bytes()
            content = content_bytes.decode("utf-8")
            _assert_safe_content(content, content_path)
            snapshots[filename] = (content_bytes, _file_fingerprint(content_path))
        except (OSError, UnicodeError) as exc:
            raise EvaluationError(f"{filename} must be UTF-8 text") from exc
    command: list[str] | None = None
    timeout: int | None = None
    checks: list[dict[str, Any]] | None = None
    if has_verifier:
        _assert_safe_content(verifier_path.read_text(encoding="utf-8"), verifier_path)
        verifier = _json(verifier_path)
        _strict(
            verifier, {"schema_version", "command", "timeout_seconds"}, verifier_path
        )
        command = verifier.get("command")
        if (
            not isinstance(command, list)
            or not command
            or any(
                not isinstance(item, str) or not item or "\x00" in item
                for item in command
            )
        ):
            raise EvaluationError("verifier command must be a nonempty argv array")
        timeout = _positive_int(verifier.get("timeout_seconds"), "verifier timeout")
    else:
        _assert_safe_content(checks_path.read_text(encoding="utf-8"), checks_path)
        checks_doc = _json(checks_path)
        _strict(checks_doc, {"schema_version", "checks"}, checks_path)
        checks = checks_doc.get("checks")
        if not isinstance(checks, list) or not checks:
            raise EvaluationError("checks.json must contain a nonempty checks array")
        for entry in checks:
            if not isinstance(entry, dict) or not isinstance(entry.get("type"), str):
                raise EvaluationError("each checks.json entry must have a string type")
    repository = root / "repository"
    if not repository.is_dir() or repository.is_symlink():
        raise EvaluationError("task repository must be a directory")
    for item in repository.rglob("*"):
        if item.is_symlink() or _is_secret_path(item.relative_to(repository)):
            raise EvaluationError(f"unsafe repository seed path: {item}")
        if not item.is_file() and not item.is_dir():
            raise EvaluationError(f"repository seed contains a special file: {item}")
        if item.is_file():
            try:
                _scan_bytes(item.read_bytes(), item)
            except OSError as exc:
                raise EvaluationError(
                    f"repository seed content is not safe: {item}"
                ) from exc
    return Task(
        root,
        name,
        skill,
        category,
        actor,
        judge,
        environment,
        command,
        timeout,
        checks,
        snapshots["prompt.md"][0],
        snapshots["rubric.md"][0],
        snapshots["prompt.md"][1],
        snapshots["rubric.md"][1],
        hashlib.sha256(snapshots["prompt.md"][0]).hexdigest(),
        hashlib.sha256(snapshots["rubric.md"][0]).hexdigest(),
    )


def _relative_safe(target: Path, raw: str) -> tuple[Path, Path]:
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise EvaluationError(f"include path must be relative and inside target: {raw}")
    if _is_secret_path(relative):
        raise EvaluationError(f"excluded include path: {raw}")
    source = target / relative
    try:
        resolved = source.resolve(strict=True)
        resolved.relative_to(target.resolve())
    except (OSError, ValueError) as exc:
        raise EvaluationError(f"missing or unsafe include path: {raw}") from exc
    _no_symlink(source, target)
    return source, relative


def _path_identity(path: Path) -> tuple[int, int]:
    info = os.lstat(path)
    return info.st_dev, info.st_ino


def _source_identity(path: Path) -> tuple[int, int]:
    try:
        return _path_identity(path)
    except OSError as exc:
        raise EvaluationError(f"task source changed during copy: {path}") from exc


def _remove_owned_file(
    path: Path, identity: tuple[int, int], digest: str | None = None
) -> None:
    try:
        if _path_identity(path) == identity and (
            digest is None or hashlib.sha256(path.read_bytes()).hexdigest() == digest
        ):
            path.unlink()
    except FileNotFoundError:
        pass


def _remove_owned_directory(path: Path, identity: tuple[int, int]) -> None:
    try:
        if _path_identity(path) == identity and not path.is_symlink():
            shutil.rmtree(path)
    except FileNotFoundError:
        pass


def _private_owner_is_authenticated(private: Path, owner_path: Path) -> bool:
    try:
        private_info = os.lstat(private)
        owner_info = os.lstat(owner_path)
    except OSError:
        return False
    if (
        not stat.S_ISDIR(private_info.st_mode)
        or stat.S_ISLNK(private_info.st_mode)
        or not stat.S_ISREG(owner_info.st_mode)
        or stat.S_ISLNK(owner_info.st_mode)
    ):
        return False
    if sys.platform != "win32" and (
        private_info.st_mode & 0o077 or owner_info.st_mode & 0o077
    ):
        return False
    return not (sys.platform != "win32" and private_info.st_uid != os.getuid())


def _secure_directory_fd(path: Path, boundary: Path) -> int | Path:
    if sys.platform == "win32":
        current = boundary.absolute()
        for part in path.absolute().relative_to(current).parts:
            current /= part
            _no_symlink(current, boundary)
            current.mkdir(exist_ok=True)
            _no_symlink(current, boundary)
        return current
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise EvaluationError("task creation requires no-follow directory primitives")
    relative = path.absolute().relative_to(boundary.absolute())
    flags = os.O_RDONLY | os.__dict__["O_DIRECTORY"] | os.__dict__["O_NOFOLLOW"]
    current_fd = os.open(boundary, flags)
    try:
        for part in relative.parts:
            with contextlib.suppress(FileExistsError):
                os.mkdir(part, dir_fd=current_fd)
            next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _secure_child_directory(
    parent_fd: int | Path, name: str, *, require_new: bool = False
) -> int | Path:
    if isinstance(parent_fd, Path):
        child = parent_fd / name
        _no_symlink(child, parent_fd)
        try:
            child.mkdir(exist_ok=False)
        except FileExistsError as error:
            if require_new:
                raise EvaluationError(
                    f"task destination was created concurrently: {child}"
                ) from error
        if not child.is_dir() or child.is_symlink():
            raise EvaluationError(f"unsafe task destination: {child}")
        _no_symlink(child, parent_fd)
        return child
    # parent_fd is only ever a POSIX dir_fd (int) here; the Path branch above
    # handles Windows. mypy can't narrow that from the isinstance check alone.
    flags = os.O_RDONLY | os.__dict__["O_DIRECTORY"] | os.__dict__["O_NOFOLLOW"]
    try:
        os.mkdir(name, dir_fd=parent_fd)
    except FileExistsError as error:
        if require_new:
            raise EvaluationError(
                f"task destination was created concurrently: {name}"
            ) from error
    return os.open(name, flags, dir_fd=parent_fd)


def _read_windows_source(source: Path) -> tuple[bytes, tuple[int, int]]:
    kernel32 = ctypes.__dict__["WinDLL"]("kernel32", use_last_error=True)
    handle = kernel32.CreateFileW(
        str(source), 0x80000000, 0x00000007, None, 3, 0x00200000, None
    )
    if handle == -1 or kernel32.GetFileType(handle) != 1:
        if handle != -1:
            kernel32.CloseHandle(handle)
        raise EvaluationError(f"task source is not a regular file: {source}")
    file_descriptor = -1
    try:
        import msvcrt

        file_descriptor = msvcrt.__dict__["open_osfhandle"](handle, os.O_RDONLY)
        handle = -1
        source_info = os.fstat(file_descriptor)
        if not stat.S_ISREG(source_info.st_mode):
            raise EvaluationError(f"task source is not a regular file: {source}")
        source_bytes = b"".join(iter(lambda: os.read(file_descriptor, 1 << 20), b""))
        return source_bytes, (source_info.st_dev, source_info.st_ino)
    except (OSError, ValueError) as exc:
        raise EvaluationError(
            f"task source could not be opened safely: {source}"
        ) from exc
    finally:
        if file_descriptor != -1:
            os.close(file_descriptor)
        if handle != -1:
            kernel32.CloseHandle(handle)


def _read_task_source(
    source: Path, expected_identity: tuple[int, int], expected_digest: str
) -> bytes:
    opened_identity: tuple[int, int] | None = None
    if sys.platform == "win32":
        source_bytes, opened_identity = _read_windows_source(source)
        source_info = os.stat(source, follow_symlinks=False)
    else:
        if not hasattr(os, "O_NOFOLLOW"):
            raise EvaluationError(
                "task source copying requires no-follow file primitives"
            )
        try:
            source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as exc:
            raise EvaluationError(f"task source changed during copy: {source}") from exc
        try:
            source_info = os.fstat(source_fd)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            source_bytes = b"".join(chunks)
        finally:
            os.close(source_fd)
    if sys.platform == "win32":
        assert opened_identity is not None
        actual_identity = opened_identity
    else:
        actual_identity = (source_info.st_dev, source_info.st_ino)
    if not stat.S_ISREG(source_info.st_mode) or actual_identity != expected_identity:
        raise EvaluationError(f"task source changed during copy: {source}")
    if hashlib.sha256(source_bytes).hexdigest() != expected_digest:
        raise EvaluationError(f"task source content changed during copy: {source}")
    _scan_bytes(source_bytes, source)
    return source_bytes


def _write_task_file(
    source: Path,
    repository_fd: int | Path,
    relative: Path,
    expected_identity: tuple[int, int],
    expected_digest: str,
) -> None:
    source_bytes = _read_task_source(source, expected_identity, expected_digest)
    if isinstance(repository_fd, Path):
        current = repository_fd
        for part in relative.parts[:-1]:
            next_path = _secure_child_directory(current, part)
            if not isinstance(next_path, Path):
                raise EvaluationError("invalid task directory handle")
            current = next_path
        destination = current / relative.name
        _no_symlink(destination, current)
        destination_fd = os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        try:
            with os.fdopen(destination_fd, "wb") as handle:
                handle.write(source_bytes)
        finally:
            destination_fd = -1
        return
    current_fd = os.dup(repository_fd)
    try:
        for part in relative.parts[:-1]:
            next_fd = _secure_child_directory(current_fd, part)
            if not isinstance(next_fd, int):
                raise EvaluationError("invalid task directory handle")
            os.close(current_fd)
            current_fd = next_fd
        # POSIX-only path, same reasoning as _secure_child_directory above.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.__dict__["O_NOFOLLOW"]
        destination_fd = os.open(relative.name, flags, 0o600, dir_fd=current_fd)
        try:
            with os.fdopen(destination_fd, "wb") as handle:
                handle.write(source_bytes)
            destination_fd = -1
        finally:
            if destination_fd != -1:
                os.close(destination_fd)
    finally:
        os.close(current_fd)


def create_task(name: str, target: Path, includes: list[str]) -> Path:
    target = target.resolve()
    if not target.is_dir() or not (target / ".git").exists():
        raise EvaluationError("target must be an existing Git repository")
    if not includes:
        raise EvaluationError("at least one include path is required")
    destination = _task_path(target, name)
    tasks = destination.parent
    if tasks.is_dir() and any(
        entry.name.casefold() == name.casefold() for entry in tasks.iterdir()
    ):
        raise EvaluationError(f"task name collides case-insensitively: {name}")
    if destination.exists() or destination.is_symlink():
        raise EvaluationError(f"task already exists: {destination}")
    selected = [_relative_safe(target, item) for item in includes]
    destination_resolved = destination.resolve()
    planned_destinations: set[str] = set()
    source_identities: dict[Path, tuple[int, int]] = {}
    source_digests: dict[Path, str] = {}
    candidate_sets: dict[Path, tuple[Path, ...]] = {}
    candidate_identities: dict[Path, tuple[int, int]] = {}
    for source, _ in selected:
        if source.is_dir():
            try:
                destination_resolved.relative_to(source.resolve())
            except ValueError:
                pass
            else:
                raise EvaluationError("include directory contains the task destination")
        candidates = [source, *source.rglob("*")] if source.is_dir() else [source]
        candidate_sets[source] = tuple(candidates)
        for candidate in candidates:
            _no_symlink(candidate, target)
            relative = candidate.relative_to(target)
            if _is_secret_path(relative):
                raise EvaluationError(f"unsafe include path: {candidate}")
            if not candidate.is_file() and not candidate.is_dir():
                raise EvaluationError(f"include is not regular: {candidate}")
            candidate_identities[candidate] = _source_identity(candidate)
            if candidate.is_file():
                try:
                    preflight_bytes = candidate.read_bytes()
                    _scan_bytes(preflight_bytes, candidate)
                except OSError as exc:
                    raise EvaluationError(
                        f"include content is not safe: {candidate}"
                    ) from exc
                source_identities[candidate] = _source_identity(candidate)
                source_digests[candidate] = hashlib.sha256(preflight_bytes).hexdigest()
            if candidate.is_file():
                relative = candidate.relative_to(target)
                destination_key = relative.as_posix().casefold()
                duplicate = destination_key in planned_destinations
                if duplicate:
                    raise EvaluationError(f"duplicate task destination: {relative}")
                planned_destinations.add(destination_key)
    parent = destination.parent
    if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
        raise EvaluationError(f"unsafe task destination: {parent}")
    destination_identity: tuple[int, int] | None = None
    destination_fd: int | Path | None = None
    repository_fd: int | Path | None = None
    try:
        destination_parent_fd = _secure_directory_fd(destination.parent, target)
        try:
            destination_fd = _secure_child_directory(
                destination_parent_fd, destination.name, require_new=True
            )
        finally:
            if isinstance(destination_parent_fd, int):
                os.close(destination_parent_fd)
        destination_identity = _path_identity(destination)
        if destination_fd is None:
            raise EvaluationError("task destination creation failed")
        repository_fd = _secure_child_directory(destination_fd, "repository")
        if repository_fd is None:
            raise EvaluationError("task repository creation failed")
        for source, relative in selected:
            if source.is_dir():
                try:
                    current_candidates = tuple([source, *source.rglob("*")])
                except OSError as exc:
                    raise EvaluationError(
                        f"directory include changed during copy: {source}"
                    ) from exc
                if set(current_candidates) != set(candidate_sets[source]):
                    raise EvaluationError(
                        f"directory include changed during copy: {source}"
                    )
                for candidate in candidate_sets[source]:
                    if _source_identity(candidate) != candidate_identities[candidate]:
                        raise EvaluationError(
                            f"directory include entry changed during copy: {candidate}"
                        )
                for file in candidate_sets[source]:
                    try:
                        if set([source, *source.rglob("*")]) != set(
                            candidate_sets[source]
                        ):
                            raise EvaluationError(
                                f"directory include changed during copy: {source}"
                            )
                    except OSError as exc:
                        raise EvaluationError(
                            f"directory include changed during copy: {source}"
                        ) from exc
                    if file.is_file() and not _is_secret_path(file.relative_to(target)):
                        _no_symlink(file, target)
                        _write_task_file(
                            file,
                            repository_fd,
                            file.relative_to(target),
                            source_identities[file],
                            source_digests[file],
                        )
                try:
                    if set([source, *source.rglob("*")]) != set(candidate_sets[source]):
                        raise EvaluationError(
                            f"directory include changed during copy: {source}"
                        )
                except OSError as exc:
                    raise EvaluationError(
                        f"directory include changed during copy: {source}"
                    ) from exc
            else:
                if _source_identity(source) != candidate_identities[source]:
                    raise EvaluationError(f"task source changed during copy: {source}")
                _write_task_file(
                    source,
                    repository_fd,
                    relative,
                    source_identities[source],
                    source_digests[source],
                )
        contract_files = {
            "task.json": json.dumps(
                {
                    "schema_version": 1,
                    "name": name,
                    "description": "Describe the bounded scenario.",
                    "skill": "replace-with-skill-name",
                    "category": "replace-with-category",
                    "actor_timeout_seconds": 600,
                    "judge_timeout_seconds": 300,
                },
                indent=2,
            )
            + "\n",
            "prompt.md": "# Prompt\n\n",
            "rubric.md": "# Rubric\n\n",
            "verifier.json": json.dumps(
                {
                    "schema_version": 1,
                    "command": ["python", "-m", "unittest", "discover", "-s", "tests"],
                    "timeout_seconds": 120,
                },
                indent=2,
            )
            + "\n",
        }
        for filename, content in contract_files.items():
            if isinstance(destination_fd, Path):
                contract_path = destination_fd / filename
                _no_symlink(contract_path, destination_fd)
                with contract_path.open("xb") as handle:
                    handle.write(content.encode())
            else:
                # POSIX-only path, same reasoning as _secure_child_directory above.
                fd = os.open(
                    filename,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.__dict__["O_NOFOLLOW"],
                    0o600,
                    dir_fd=destination_fd,
                )
                with os.fdopen(fd, "wb") as handle:
                    handle.write(content.encode())
    except BaseException:
        if destination_identity is not None:
            _remove_owned_directory(destination, destination_identity)
        raise
    finally:
        if isinstance(repository_fd, int):
            os.close(repository_fd)
        if isinstance(destination_fd, int):
            os.close(destination_fd)
    return destination


@dataclass(frozen=True)
class Run:
    stdout: str
    stderr: str
    code: int | None
    timed_out: bool
    duration: float


def _run_declarative_verifier(checks: list[dict[str, Any]], worktree: Path) -> Run:
    """Run a task's checks.json in-process, as a Run-shaped result.

    Every check function resolves relative paths and git state against the
    current working directory, so this temporarily chdirs to the worktree --
    the same directory a custom verifier.json command already runs in via
    its own `cwd` argument to `_run`. Each check type already bounds its own
    subprocess calls (git, `command_succeeds`'s own timeout), so no separate
    outer timeout is enforced here.
    """
    from codev_workflow.eval_checks import run_declarative_checks

    start = time.monotonic()
    previous_cwd = Path.cwd()
    try:
        os.chdir(worktree)
        passed, message = run_declarative_checks(checks)
    finally:
        os.chdir(previous_cwd)
    duration = time.monotonic() - start
    return Run(
        stdout="" if passed else "",
        stderr=message,
        code=0 if passed else 1,
        timed_out=False,
        duration=duration,
    )


def _stop(process: subprocess.Popen[Any]) -> None:
    """Bound process termination and isolate platform-specific signaling."""
    try:
        if sys.platform != "win32":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                timeout=1.0,
            )
        process.wait(timeout=0.5)
        return
    except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
        pass
    try:
        if sys.platform != "win32":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (OSError, ProcessLookupError):
        pass
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=1.0)


# Metacharacters cmd.exe treats specially: pipe/redirect/chain operators,
# its own escape character, percent/bang variable expansion, and grouping
# parens. Deliberately excludes '"' -- subprocess's own Win32 argument
# quoting already escapes embedded quotes correctly, and layering a second,
# independent escape pass on top of that interacts badly with it (the two
# passes disagree about which backslash/quote belongs to which layer).
_WINDOWS_BATCH_METACHARACTERS = set("()%!^<>&|")


_NPM_SHIM_TARGET = re.compile(
    r'"%dp0%\\(?P<relative>[^"]+\.exe)"\s+%\*\s*$', re.MULTILINE
)


def _resolve_windows_shim(executable: str) -> str:
    """Resolve a standard npm-generated .cmd shim to the real .exe it wraps.

    npm auto-generates this exact wrapper shape (SETLOCAL/find_dp0/%dp0%) for
    every package with a Windows CLI entry point, including an npm-installed
    opencode.CMD. Resolving straight to the real executable means never
    invoking cmd.exe for it at all, which sidesteps its independent,
    metacharacter-sensitive re-parsing of arguments (see
    _windows_batch_safe_argv) at the root rather than escaping around it --
    cleaner than escaping since it leaves the argument text completely
    unmodified. Falls back to the original path (and _windows_batch_safe_argv
    escaping) for any .cmd/.bat that isn't this exact, extremely common shape.
    """
    if sys.platform != "win32" or not executable.lower().endswith(".cmd"):
        return executable
    path = Path(executable)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return executable
    match = _NPM_SHIM_TARGET.search(text)
    if match is None:
        return executable
    target = path.parent / match.group("relative")
    return str(target) if target.is_file() else executable


def _windows_batch_safe_argv(argv: list[str]) -> list[str]:
    """Escape cmd.exe metacharacters when the target is a .bat/.cmd file.

    Launching a .bat/.cmd executable on Windows (e.g. an npm-installed
    opencode.CMD wrapper) transparently delegates through `cmd.exe /c`,
    which re-parses the assembled command line for its own metacharacters
    on top of -- and independently of -- normal Win32 argument quoting.
    subprocess.Popen only guards against the latter, so e.g. a literal "|"
    inside a multi-line prompt is read as a pipe operator and silently
    truncates the argument before it ever reaches the real program. This is
    the same class of bug fixed for Node's child_process in CVE-2024-27980.
    Escaping every metacharacter with "^" is safe even where cmd.exe would
    have handled it correctly anyway.
    """
    if sys.platform != "win32" or not argv[0].lower().endswith((".cmd", ".bat")):
        return argv
    escaped = [argv[0]]
    for argument in argv[1:]:
        escaped.append(
            "".join(
                f"^{char}" if char in _WINDOWS_BATCH_METACHARACTERS else char
                for char in argument
            )
        )
    return escaped


def _run(
    argv: list[str],
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
    decode_errors: str = "replace",
) -> Run:
    if sys.platform == "win32" and argv[0].lower().endswith(".py"):
        argv = [sys.executable, *argv]
    argv = _windows_batch_safe_argv(argv)
    start = time.monotonic()
    flags = (
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if sys.platform == "win32"
        else 0
    )
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=sys.platform != "win32",
            creationflags=flags,
        )
    except (OSError, ValueError) as exc:
        raise EvaluationError(f"could not launch {argv[0]}") from exc
    try:
        raw_stdout, raw_stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _stop(process)
        raw_stdout, raw_stderr = process.communicate()
        stdout = _decode(raw_stdout or exc.stdout, decode_errors)
        stderr = _decode(raw_stderr or exc.stderr, decode_errors)
        return Run(stdout, stderr, process.returncode, True, time.monotonic() - start)
    except BaseException:
        _stop(process)
        raise
    _stop(process)
    result = Run(
        _decode(raw_stdout, decode_errors),
        _decode(raw_stderr, decode_errors),
        process.returncode,
        False,
        time.monotonic() - start,
    )
    return result


def _git(git: str, args: list[str], cwd: Path, timeout: int = 60) -> Run:
    config = ["-c", "core.hooksPath="]
    if args and args[0] == "diff":
        config.extend(["-c", "diff.external=", "-c", "diff.trustExitCode=false"])
    return _run(
        [git, *config, *args],
        cwd,
        timeout,
        env=_isolated_env(),
        decode_errors="surrogateescape",
    )


def _capture_diff(git: str, cwd: Path, seed_commit: str) -> str:
    changed = _git(git, ["diff", "--name-only", "-z", seed_commit], cwd)
    if changed.code != 0:
        raise EvaluationError(f"git changed-path phase failed: {changed.stderr}")
    safe_paths = [
        f":(literal){raw_path}"
        for raw_path in changed.stdout.split("\x00")
        if raw_path and not _is_secret_path(Path(raw_path))
    ]
    pathspec = ["--", *safe_paths]
    if safe_paths:
        diff = _git(
            git,
            [
                "diff",
                "--binary",
                "--no-ext-diff",
                "--no-textconv",
                seed_commit,
                *pathspec,
            ],
            cwd,
        )
        if diff.code != 0:
            raise EvaluationError(f"git diff phase failed: {diff.stderr}")
    else:
        diff = Run("", "", 0, False, 0.0)
    untracked = _git(git, ["ls-files", "--others", "--exclude-standard", "-z"], cwd)
    if untracked.code != 0:
        raise EvaluationError(f"git untracked-file phase failed: {untracked.stderr}")
    commits = _git(git, ["log", "--format=%H%x00", f"{seed_commit}..HEAD"], cwd)
    if commits.code != 0:
        raise EvaluationError(f"git history phase failed: {commits.stderr}")
    history: list[dict[str, str]] = []
    metadata = (
        ("commit", "%H"),
        ("parents", "%P"),
        ("author", "%an"),
        ("author_email", "%ae"),
        ("authored_at", "%aI"),
        ("committer", "%cn"),
        ("committer_email", "%ce"),
        ("committed_at", "%cI"),
        ("subject", "%s"),
    )
    for raw_commit in (item for item in commits.stdout.split("\x00") if item.strip()):
        commit = raw_commit.strip()
        entry: dict[str, str] = {}
        for key, format_spec in metadata:
            value = _git(git, ["show", "-s", f"--format={format_spec}", commit], cwd)
            if value.code != 0:
                raise EvaluationError(
                    f"git history metadata phase failed: {value.stderr}"
                )
            metadata_value = cast(str, _sanitize_json_value(value.stdout.rstrip("\n")))
            entry[key] = (
                "[REDACTED_SECRET]" if _secret_key(metadata_value) else metadata_value
            )
        history.append(entry)
    if safe_paths:
        status = _git(git, ["diff", "--name-status", "-z", seed_commit, *pathspec], cwd)
        if status.code != 0:
            raise EvaluationError(f"git status phase failed: {status.stderr}")
    else:
        status = Run("", "", 0, False, 0.0)
    status_entries = [item for item in status.stdout.split("\x00") if item]
    evidence = (
        "--- actor history ---\n"
        + json.dumps({"commits": history, "status": status_entries}, ensure_ascii=False)
        + "\n--- actor diff ---\n"
        + _redact_diff(diff.stdout)
    )
    untracked_paths = sorted(
        {raw_path for raw_path in untracked.stdout.split("\x00") if raw_path}
    )
    for raw_path in untracked_paths:
        relative = Path(raw_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or _is_secret_path(relative)
        ):
            continue
        path = cwd / relative
        try:
            path.resolve(strict=True).relative_to(cwd.resolve())
            _no_symlink(path, cwd)
        except (EvaluationError, OSError, ValueError):
            continue
        if not path.is_file() or path.is_symlink():
            continue
        encoded = base64.b64encode(_redact_bytes(path.read_bytes())).decode("ascii")
        evidence += f"\n--- untracked: {raw_path} (base64) ---\n{encoded}\n"
    return evidence


def _valid_judge(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != _JUDGE_FIELDS:
        return False
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        return False
    if not isinstance(value["verdict"], str) or value["verdict"] not in {
        "pass",
        "fail",
    }:
        return False
    if not isinstance(value["summary"], str) or not value["summary"].strip():
        return False
    findings = value["findings"]
    if not isinstance(findings, list) or not findings:
        return False
    return all(
        isinstance(item, dict)
        and set(item) == {"criterion", "verdict", "evidence"}
        and isinstance(item["verdict"], str)
        and item["verdict"] in {"pass", "fail"}
        and isinstance(item["criterion"], str)
        and bool(item["criterion"].strip())
        and isinstance(item["evidence"], str)
        and bool(item["evidence"].strip())
        for item in findings
    )


def _decode(value: str | bytes | None, errors: str = "replace") -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors=errors) if isinstance(value, bytes) else value


def _judge_json(raw: str) -> dict[str, Any]:
    """Resolve exactly one judge result from a complete JSON event stream."""
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        raise EvaluationError("judge returned empty output")
    try:
        events = [json.loads(line) for line in lines]
    except json.JSONDecodeError as exc:
        raise EvaluationError("judge returned malformed JSONL") from exc
    if len(events) == 1 and _valid_judge(events[0]):
        return cast(dict[str, Any], events[0])
    outputs: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            raise EvaluationError("judge event is not an object")
        event_type = event.get("type")
        if not isinstance(event_type, str):
            raise EvaluationError("judge event type is invalid")
        part = event.get("part")
        if (
            event_type in {"text", "assistant"}
            and isinstance(part, dict)
            and isinstance(part.get("text"), str)
        ):
            outputs.append(part["text"])
        elif event_type == "text" and isinstance(event.get("text"), str):
            outputs.append(event["text"])
        elif event_type not in {
            "step_start",
            "step_finish",
            "tool_use",
            "tool_result",
            "session",
        }:
            raise EvaluationError("unrelated judge event")
    if len(outputs) != 1:
        raise EvaluationError("judge final output is not unique")
    try:
        value = json.loads(outputs[0])
    except json.JSONDecodeError as exc:
        raise EvaluationError("judge final output is malformed") from exc
    if not _valid_judge(value):
        raise EvaluationError("judge final output violates schema")
    return cast(dict[str, Any], value)


def _actor_artifacts(raw: str) -> tuple[str, str]:
    """Separate raw JSONL events from the actor's final text output."""
    lines = [line for line in raw.splitlines() if line.strip()]
    try:
        events = [json.loads(line) for line in lines]
    except json.JSONDecodeError as exc:
        raise EvaluationError("actor returned malformed JSONL") from exc
    sanitized_events = [_sanitize_json_value(event) for event in events]
    output: list[str] = []
    for event in sanitized_events:
        if not isinstance(event, dict):
            raise EvaluationError("actor event is not an object")
        event_type = event.get("type")
        if event_type in {"text", "assistant"}:
            part = event.get("part")
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                output.append(part["text"])
            elif isinstance(event.get("text"), str):
                output.append(event["text"])
    event_stream = "".join(
        json.dumps(event, ensure_ascii=False) + "\n" for event in sanitized_events
    )
    return event_stream, "".join(output)


def _build_trajectory(event_stream: str, final_output: str | None = None) -> str:
    """Merge a redacted JSONL event stream (and, for the actor, its final text
    output) into one trajectory.json document: {"schema_version": 1, "steps":
    [...]}. A line that is not valid JSON (the fallback shape
    _safe_process_output falls back to for non-JSONL text) becomes a plain
    string step rather than being dropped, so this never loses evidence.
    """
    steps: list[dict[str, Any]] = []
    for index, line in enumerate(
        line for line in event_stream.splitlines() if line.strip()
    ):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            event = line
        steps.append({"index": index, "event": event})
    if final_output:
        steps.append({"index": len(steps), "final_output": final_output})
    return json.dumps({"schema_version": 1, "steps": steps}, ensure_ascii=False) + "\n"


def _manifest(files: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "path": name,
            "size": len(_content_bytes(content)),
            "sha256": hashlib.sha256(_content_bytes(content)).hexdigest(),
        }
        for name, content in sorted(files.items())
    ]


def _content_bytes(content: str) -> bytes:
    return content.encode("utf-8", errors="surrogateescape")


def _sync(path: Path) -> None:
    # "rb" opens read-only (GENERIC_READ only on Windows); os.fsync() maps to
    # FlushFileBuffers there, which requires write access on the handle, so a
    # read-only reopen fails with EBADF. "r+b" requires the file to already
    # exist (true for every caller here, which sync right after writing) and
    # does not truncate it.
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _sync_directory(path: Path) -> None:
    if sys.platform != "win32":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    elif sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateFileW(
            str(path), 0xC0000000, 0x00000007, None, 3, 0x02000000, None
        )
        if handle == -1:
            raise OSError(ctypes.get_last_error(), f"could not open directory: {path}")
        try:
            if not kernel32.FlushFileBuffers(handle):
                raise OSError(
                    ctypes.get_last_error(),
                    f"could not flush directory: {path}",
                )
        finally:
            kernel32.CloseHandle(handle)
    else:
        raise EvaluationError(
            f"unsupported platform for durable publication: {os.name}"
        )


def _safe_manifest_paths(output: Path, manifest: Any) -> set[str]:
    if not isinstance(manifest, list) or not manifest:
        raise EvaluationError("invalid evidence artifact manifest")
    paths: set[str] = set()
    for item in manifest:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise EvaluationError("invalid evidence artifact manifest entry")
        relative = Path(item["path"])
        if (
            relative.is_absolute()
            or not relative.parts
            or ".." in relative.parts
            or "." in relative.parts
        ):
            raise EvaluationError("unsafe evidence artifact path")
        if item["path"] in paths:
            raise EvaluationError("duplicate evidence artifact path")
        path = output / relative
        try:
            path.resolve().relative_to(output.resolve())
        except ValueError as exc:
            raise EvaluationError("evidence artifact is outside output") from exc
        _no_symlink(path, output)
        paths.add(item["path"])
    return paths


def _validate_bundle(output: Path) -> None:
    marker_path = output / _COMMIT_MARKER
    if marker_path.is_symlink():
        raise EvaluationError("evidence commit marker cannot be a symlink")
    marker = _json(marker_path)
    if set(marker) != {"schema_version", "bundle_id", "artifacts"}:
        raise EvaluationError("invalid evidence commit marker")
    if (
        type(marker.get("schema_version")) is not int
        or marker.get("schema_version") != 1
    ):
        raise EvaluationError("invalid evidence commit marker")
    if not isinstance(marker.get("bundle_id"), str) or not marker["bundle_id"]:
        raise EvaluationError("invalid evidence bundle identifier")
    manifest = marker.get("artifacts")
    paths = _safe_manifest_paths(output, manifest)
    manifest_entries = cast(list[dict[str, Any]], manifest)
    for item in manifest_entries:
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise EvaluationError("invalid evidence artifact manifest entry")
        if (
            not isinstance(item["path"], str)
            or type(item["size"]) is not int
            or item["size"] < 0
            or not isinstance(item["sha256"], str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", item["sha256"])
        ):
            raise EvaluationError("invalid evidence artifact manifest entry")
        path = output / item["path"]
        if not path.is_file():
            raise EvaluationError("evidence artifact is missing")
        data = path.read_bytes()
        if (
            len(data) != item["size"]
            or hashlib.sha256(data).hexdigest() != item["sha256"]
        ):
            raise EvaluationError("evidence artifact failed manifest validation")
    actual = {
        path.name
        for path in output.iterdir()
        if path.name not in {_COMMIT_MARKER, _TRANSACTION_MARKER}
        and not path.name.startswith(".codev-eval-stage-")
    }
    if actual != paths:
        raise EvaluationError("evidence bundle contains unexpected files")


def _validate_recovery_manifest(output: Path, manifest: Any) -> set[str]:
    paths = _safe_manifest_paths(output, manifest)
    for item in cast(list[dict[str, Any]], manifest):
        if not isinstance(item, dict) or set(item) != {"path", "size", "sha256"}:
            raise EvaluationError("invalid recovery artifact manifest entry")
        if (
            type(item["size"]) is not int
            or item["size"] < 0
            or not isinstance(item["sha256"], str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", item["sha256"])
        ):
            raise EvaluationError("invalid recovery artifact manifest entry")
        path = output / item["path"]
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file():
                raise EvaluationError("recovery artifact is not an owned regular file")
            data = path.read_bytes()
            if (
                len(data) != item["size"]
                or hashlib.sha256(data).hexdigest() != item["sha256"]
            ):
                raise EvaluationError("recovery artifact ownership validation failed")
    return paths


def _copy_seed_tree(source: Path, destination: Path) -> None:
    """Copy a validated task repository without following replacement links."""
    _no_symlink(source, source.parent)
    source_identity = _source_identity(source)
    entries = tuple([source, *source.rglob("*")])
    expected: dict[Path, tuple[tuple[int, int], str | None]] = {}
    for entry in entries:
        _no_symlink(entry, source)
        identity = _source_identity(entry)
        if entry.is_file():
            data = _read_task_source(
                entry, identity, hashlib.sha256(entry.read_bytes()).hexdigest()
            )
            expected[entry] = (identity, hashlib.sha256(data).hexdigest())
        elif entry.is_dir():
            expected[entry] = (identity, None)
        else:
            raise EvaluationError(f"task repository entry is not regular: {entry}")
    if _source_identity(source) != source_identity:
        raise EvaluationError("task repository changed during copy")
    destination.mkdir()
    for entry in entries:
        if entry == source:
            continue
        relative = entry.relative_to(source)
        target = destination / relative
        identity, digest = expected[entry]
        if _source_identity(entry) != identity:
            raise EvaluationError(f"task repository entry changed during copy: {entry}")
        if entry.is_dir():
            target.mkdir()
        else:
            _write_task_file(entry, destination, relative, identity, cast(str, digest))


def _stage_skill(seed: Path, target: Path, skill: str) -> None:
    """Copy an installed skill (plus its AGENTS.md routing block) into a seed.

    This is the entire "with skill" condition for a performance snapshot
    (see run_benchmark()): the prompt never names the skill, so the only
    thing that differs between the with- and without-skill conditions is
    whether the actor can discover and read the skill on its own -- exactly
    as it would in a real repository that has the skill installed, rather
    than being told to use it.
    """
    skill_source = target / ".agents" / "skills" / skill
    if not skill_source.is_dir() or skill_source.is_symlink():
        raise EvaluationError(f"skill is not installed under .agents/skills: {skill}")
    skill_destination = seed / ".agents" / "skills" / skill
    skill_destination.parent.mkdir(parents=True, exist_ok=True)
    _copy_seed_tree(skill_source, skill_destination)

    agents_source = target / "AGENTS.md"
    if not agents_source.is_file() or agents_source.is_symlink():
        return
    text = agents_source.read_text(encoding="utf-8")
    start = text.find(AGENTS_START)
    end = text.find(AGENTS_END)
    if start == -1 or end == -1 or end <= start:
        return
    block = text[start : end + len(AGENTS_END)]
    agents_destination = seed / "AGENTS.md"
    existing = (
        agents_destination.read_text(encoding="utf-8")
        if agents_destination.is_file()
        else ""
    )
    agents_destination.write_text(
        (existing + "\n" if existing else "") + block + "\n", encoding="utf-8"
    )


def _publish_artifact(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        destination_fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            destination_handle = os.fdopen(destination_fd, "wb")
            destination_fd = -1
            with source.open("rb") as source_handle, destination_handle:
                shutil.copyfileobj(source_handle, destination_handle)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
        finally:
            if destination_fd != -1:
                os.close(destination_fd)


def _write_output(output: Path, files: dict[str, str]) -> None:
    if not output.is_dir() or output.is_symlink() or any(output.iterdir()):
        raise EvaluationError("output must be an existing empty directory")
    output_identity = _path_identity(output)
    bundle_id = uuid.uuid4().hex
    manifest = _manifest(files)
    published: list[tuple[Path, tuple[int, int], str]] = []
    private = Path(tempfile.mkdtemp(prefix=_PRIVATE_PREFIX))
    stage = private / "stage"
    stage.mkdir()
    transaction_id = uuid.uuid4().hex
    transaction = {
        "schema_version": 1,
        "bundle_id": bundle_id,
        "transaction_id": transaction_id,
        "stage_id": stage.name,
        "output": str(output.resolve()),
        "artifacts": manifest,
        "owned_artifacts": manifest,
    }
    owner_path = private / _PRIVATE_OWNER_MARKER
    transaction_path = private / _PRIVATE_TRANSACTION_MARKER
    committed = False
    marker_identity: tuple[int, int] | None = None
    marker_content = ""
    output_key = str(output.resolve())
    _PRIVATE_TRANSACTIONS[output_key] = (private, transaction_id)
    try:
        for name, content in files.items():
            path = stage / name
            path.write_bytes(_content_bytes(content))
            _sync(path)
        owner_path.write_text(
            json.dumps(transaction, indent=2) + "\n", encoding="utf-8"
        )
        owner_path.chmod(0o600)
        _sync(owner_path)
        transaction_path.write_text(
            json.dumps(transaction, indent=2) + "\n", encoding="utf-8"
        )
        transaction_path.chmod(0o600)
        _sync(transaction_path)
        _sync_directory(stage)
        for item in manifest:
            if _path_identity(output) != output_identity:
                raise EvaluationError("output directory changed during publication")
            destination = output / item["path"]
            _publish_artifact(stage / item["path"], destination)
            stage_path = stage / item["path"]
            stage_path.unlink()
            published.append((destination, _path_identity(destination), item["sha256"]))
        for item in manifest:
            path = output / item["path"]
            data = path.read_bytes()
            if (
                len(data) != item["size"]
                or hashlib.sha256(data).hexdigest() != item["sha256"]
            ):
                raise EvaluationError("evidence manifest validation failed")
        marker_path = output / _COMMIT_MARKER
        marker = {"schema_version": 1, "bundle_id": bundle_id, "artifacts": manifest}
        if _path_identity(output) != output_identity:
            raise EvaluationError("output directory changed during publication")
        marker_content = json.dumps(marker, indent=2) + "\n"
        with marker_path.open("x", encoding="utf-8") as handle:
            handle.write(marker_content)
        _sync(marker_path)
        marker_identity = _path_identity(marker_path)
        _sync_directory(output)
        if _path_identity(marker_path) != marker_identity:
            raise EvaluationError("commit marker changed during publication")
        _validate_bundle(output)
        committed = True
        _PRIVATE_TRANSACTIONS.pop(output_key, None)
        shutil.rmtree(private)
    except BaseException:
        if _PRIVATE_TRANSACTIONS.get(output_key, (None, None))[0] == private:
            _PRIVATE_TRANSACTIONS.pop(output_key, None)
        if not committed:
            for path, identity, digest in published:
                _remove_owned_file(path, identity, digest)
            if marker_identity is not None:
                _remove_owned_file(
                    output / _COMMIT_MARKER,
                    marker_identity,
                    hashlib.sha256(marker_content.encode()).hexdigest(),
                )
            shutil.rmtree(private, ignore_errors=True)
        raise


def _recover_output(output: Path) -> None:
    output = output.resolve()
    if (output / _TRANSACTION_MARKER).exists():
        raise EvaluationError("caller output transaction marker is not recoverable")
    transaction_record = _PRIVATE_TRANSACTIONS.get(str(output))
    candidates: list[tuple[Path, str, dict[str, Any]]] = []
    if transaction_record is not None:
        candidates.append((transaction_record[0], transaction_record[1], {}))
    else:
        try:
            private_entries = Path(tempfile.gettempdir()).iterdir()
        except OSError:
            return
        for private in private_entries:
            if not private.name.startswith(_PRIVATE_PREFIX):
                continue
            owner_path = private / _PRIVATE_OWNER_MARKER
            if not _private_owner_is_authenticated(private, owner_path):
                continue
            try:
                owner_data = _json(owner_path)
            except EvaluationError:
                continue
            if owner_data.get("output") == str(output) and isinstance(
                owner_data.get("transaction_id"), str
            ):
                candidates.append((private, owner_data["transaction_id"], owner_data))
    if not candidates:
        return
    private, transaction_id, cached_data = candidates[0]
    if not _private_owner_is_authenticated(private, private / _PRIVATE_OWNER_MARKER):
        return
    owner_path = private / _PRIVATE_OWNER_MARKER
    if cached_data:
        data = cached_data
    else:
        try:
            data = _json(owner_path)
        except EvaluationError:
            return
    required = {
        "schema_version",
        "bundle_id",
        "transaction_id",
        "stage_id",
        "output",
        "artifacts",
        "owned_artifacts",
    }
    try:
        if (
            set(data) != required
            or type(data.get("schema_version")) is not int
            or data.get("schema_version") != 1
        ):
            return
        if data.get("transaction_id") != transaction_id or data.get("output") != str(
            output
        ):
            return
        if data.get("owned_artifacts") != data.get("artifacts"):
            return
        _validate_recovery_manifest(private, data["artifacts"])
        _validate_recovery_manifest(private, data["owned_artifacts"])
        stage_id = data.get("stage_id")
        if (
            not isinstance(stage_id, str)
            or Path(stage_id).name != stage_id
            or stage_id != "stage"
        ):
            return
    except (EvaluationError, KeyError, TypeError, ValueError):
        return
    transaction_path = private / _PRIVATE_TRANSACTION_MARKER
    if not transaction_path.is_file() or transaction_path.is_symlink():
        return
    try:
        if _json(transaction_path) != data:
            return
    except EvaluationError:
        return
    stage = private / stage_id
    if stage.is_symlink() or not stage.is_dir():
        return
    try:
        _validate_recovery_manifest(stage, data["artifacts"])
    except (EvaluationError, KeyError, TypeError, ValueError):
        return
    stage_paths = {item.name for item in stage.iterdir()}
    artifact_paths = {
        item["path"] for item in cast(list[dict[str, Any]], data["artifacts"])
    }
    if not stage_paths <= artifact_paths:
        return
    commit_path = output / _COMMIT_MARKER
    if commit_path.exists():
        try:
            _validate_bundle(output)
            commit = _json(commit_path)
        except EvaluationError:
            return
        if (
            commit.get("bundle_id") != data["bundle_id"]
            or commit.get("artifacts") != data["artifacts"]
        ):
            return
    if not commit_path.exists():
        for item in data["owned_artifacts"]:
            path = output / item["path"]
            if path.exists() or path.is_symlink():
                try:
                    _validate_recovery_manifest(output, [item])
                except EvaluationError:
                    return
                path.unlink()
    _PRIVATE_TRANSACTIONS.pop(str(output), None)
    shutil.rmtree(private)


def _clear_readonly_and_retry(
    func: Callable[[str], object], target: str, exc_info: object
) -> None:
    # git deliberately makes .git/objects/** read-only; Windows refuses to
    # delete a read-only file (WinError 5, Access is denied) even though the
    # containing directory and the current user both have full permissions.
    # POSIX ignores the read-only bit for deletion, so this only ever
    # triggers on Windows in practice.
    os.chmod(target, stat.S_IWRITE)
    func(target)


def _remove(path: Path) -> None:
    if path.exists() or path.is_symlink():
        shutil.rmtree(path, onerror=_clear_readonly_and_retry)


def evaluate(
    name: str,
    target: Path,
    output: Path,
    git: str = "git",
    opencode: str = "opencode",
    with_skill: bool = True,
    sandbox: str = "worktree",
    docker: str = "docker",
) -> bool:
    if sandbox not in ("worktree", "docker"):
        raise EvaluationError(f"unknown sandbox: {sandbox!r}")
    target = target.resolve()
    task = validate_task(_task_path(target, name))
    if sandbox == "docker" and task.environment is None:
        raise EvaluationError(
            "--sandbox docker requires the task to declare an environment "
            'block ({"backend": "docker", "image": "..."}) in its task.json'
        )
    try:
        output.resolve().relative_to(target)
    except ValueError:
        pass
    else:
        raise EvaluationError("output must be outside the target repository")
    if output.exists() and output.is_dir() and not output.is_symlink():
        _recover_output(output)
    if (
        not output.exists()
        or output.is_symlink()
        or not output.is_dir()
        or any(output.iterdir())
    ):
        raise EvaluationError("output must be an existing empty directory")
    # Resolve to the full path (with extension, e.g. opencode.CMD on Windows)
    # and use that everywhere below. subprocess.Popen with shell=False does
    # not perform the shell's PATHEXT extension search, so launching a bare
    # "opencode" fails on Windows when it resolves to a .cmd/.bat/.ps1 shim,
    # which is the common case for npm-installed CLIs.
    resolved_git = shutil.which(git)
    resolved_opencode = shutil.which(opencode)
    if resolved_opencode is None and Path(opencode).is_file():
        resolved_opencode = str(Path(opencode).resolve())
    if resolved_git is None or resolved_opencode is None:
        raise EvaluationError("git and opencode must be available")
    git = _resolve_windows_shim(resolved_git)
    opencode = _resolve_windows_shim(resolved_opencode)
    result: dict[str, Any] = {
        "schema_version": 1,
        "task": {
            "name": name,
            "path": str(Path(".codev") / "eval" / "tasks" / name),
        },
        "skill": task.skill,
        "category": task.category,
        "with_skill": with_skill,
        "actor": {"status": "skipped"},
        "verifier": {"status": "skipped"},
        "judge": {"status": "skipped"},
        "artifacts": {},
    }
    files: dict[str, str] = {}
    error: str | None = None
    with tempfile.TemporaryDirectory(prefix="codev-eval-") as temporary:
        base = Path(temporary)
        seed, worktree = base / "seed", base / "worktree"
        judge_dir: Path | None = None
        try:
            _copy_seed_tree(task.root / "repository", seed)
            if with_skill:
                _stage_skill(seed, target, task.skill)
            for args in (
                ["init"],
                ["config", "user.email", "codev@example.invalid"],
                ["config", "user.name", "CoDev"],
                ["add", "."],
                ["commit", "-m", "seed"],
            ):
                run = _git(git, list(args), seed)
                if run.code != 0:
                    raise EvaluationError(f"git seed phase failed: {run.stderr}")
            commit = _git(git, ["rev-parse", "HEAD"], seed)
            if commit.code != 0 or not commit.stdout.strip():
                raise EvaluationError(f"git seed commit phase failed: {commit.stderr}")
            seed_commit = commit.stdout.strip()
            run = _git(
                git, ["worktree", "add", "--detach", str(worktree), "HEAD"], seed
            )
            if run.code != 0:
                raise EvaluationError(f"git worktree phase failed: {run.stderr}")
            files["trajectory.json"] = ""
            try:
                _assert_snapshot_digest(
                    task.root / "prompt.md",
                    task.prompt_fingerprint,
                    task.prompt_digest,
                )
                actor_argv = [
                    opencode,
                    "run",
                    "--format",
                    "json",
                    "--dir",
                    str(worktree),
                    task.prompt.decode("utf-8"),
                ]
                if sandbox == "docker":
                    assert task.environment is not None
                    from codev_workflow.eval_environment import DockerEnvironment

                    resolved_docker = shutil.which(docker)
                    if resolved_docker is None and Path(docker).is_file():
                        resolved_docker = str(Path(docker).resolve())
                    if resolved_docker is None:
                        raise EvaluationError(
                            "this task's environment declares docker, but no "
                            f"`{docker}` executable is on PATH"
                        )
                    docker_environment = DockerEnvironment(
                        image=task.environment["image"], docker=resolved_docker
                    )
                    actor = docker_environment.run(
                        actor_argv,
                        worktree,
                        task.actor_timeout,
                        env=_isolated_env(),
                    )
                else:
                    actor = _run(
                        actor_argv,
                        worktree,
                        task.actor_timeout,
                        env=_isolated_env(),
                    )
            except EvaluationError as exc:
                result["actor"] = {
                    "status": "error",
                    "stdout": "",
                    "stderr": str(exc),
                    "exit_code": None,
                    "duration_seconds": 0.0,
                    "timeout": False,
                }
                raise
            result["actor"] = {
                "status": "timeout"
                if actor.timed_out
                else ("completed" if actor.code == 0 else "failed"),
                "stdout": "",
                "stderr": "",
                "exit_code": actor.code,
                "duration_seconds": actor.duration,
                "timeout": actor.timed_out,
            }
            continue_evaluation = actor.code == 0 and not actor.timed_out
            try:
                actor_events, actor_output = _actor_artifacts(actor.stdout)
            except EvaluationError:
                files["trajectory.json"] = ""
                if continue_evaluation:
                    result["actor"]["status"] = "malformed"
                    raise
            else:
                files["trajectory.json"] = _build_trajectory(
                    actor_events, final_output=actor_output
                )
            if not continue_evaluation:
                result["outcome"] = "failed"
            if continue_evaluation:
                files["verifier-stdout.txt"] = ""
                files["verifier-stderr.txt"] = ""
                try:
                    if task.checks is not None:
                        verifier = _run_declarative_verifier(task.checks, worktree)
                    else:
                        assert task.command is not None
                        assert task.verifier_timeout is not None
                        verifier = _run(
                            _resolve_verifier_command(task.command),
                            worktree,
                            task.verifier_timeout,
                            env=_isolated_env(),
                        )
                except EvaluationError as exc:
                    result["verifier"] = {
                        "status": "error",
                        "stdout": "",
                        "stderr": str(exc),
                        "exit_code": None,
                        "duration_seconds": 0.0,
                        "timeout": False,
                    }
                    raise
                files["verifier-stdout.txt"] = _safe_process_output(verifier.stdout)
                files["verifier-stderr.txt"] = _safe_process_output(verifier.stderr)
                result["verifier"] = {
                    "status": "passed"
                    if verifier.code == 0 and not verifier.timed_out
                    else ("timeout" if verifier.timed_out else "failed"),
                    "stdout": "",
                    "stderr": "",
                    "exit_code": verifier.code,
                    "duration_seconds": verifier.duration,
                    "timeout": verifier.timed_out,
                }
                files["diff.patch"] = _capture_diff(git, worktree, seed_commit)
                if verifier.code != 0 or verifier.timed_out:
                    result["outcome"] = "failed"
                else:
                    try:
                        _remove(worktree)
                        _remove(seed)
                    except OSError as exc:
                        raise EvaluationError(
                            f"cleanup before judge failed: {exc}"
                        ) from exc
                    judge_dir = base / "judge"
                    judge_dir.mkdir()
                    files["judge-trajectory.json"] = ""
                    files["judge-output.json"] = ""
                    _assert_snapshot_digest(
                        task.root / "rubric.md",
                        task.rubric_fingerprint,
                        task.rubric_digest,
                    )
                    rubric = _redact_text(task.rubric.decode("utf-8"))
                    (judge_dir / "rubric.md").write_text(rubric, encoding="utf-8")
                    for filename, content in files.items():
                        (judge_dir / filename).write_bytes(_content_bytes(content))
                    try:
                        judge = _run(
                            [
                                opencode,
                                "run",
                                "--format",
                                "json",
                                "--dir",
                                str(judge_dir),
                                _JUDGE_PROMPT,
                            ],
                            judge_dir,
                            task.judge_timeout,
                            env=_isolated_env(),
                        )
                    except EvaluationError:
                        result["judge"] = {
                            "status": "error",
                            "stdout": "",
                            "stderr": "judge launch failed",
                            "exit_code": None,
                            "duration_seconds": 0.0,
                            "timeout": False,
                        }
                        raise
                    files["judge-trajectory.json"] = _build_trajectory(
                        _safe_process_output(judge.stdout)
                    )
                    result["judge"] = {
                        "status": "timeout"
                        if judge.timed_out
                        else ("failed" if judge.code != 0 else "completed"),
                        "stdout": "",
                        "stderr": "",
                        "exit_code": judge.code,
                        "duration_seconds": judge.duration,
                        "timeout": judge.timed_out,
                    }
                    if judge.timed_out or judge.code != 0:
                        raise EvaluationError("judge phase failed")
                    try:
                        parsed = _judge_json(judge.stdout)
                    except EvaluationError:
                        result["judge"]["status"] = "malformed"
                        raise
                    files["judge-output.json"] = (
                        json.dumps(_sanitize_json_value(parsed), indent=2) + "\n"
                    )
                    result["judge"]["status"] = (
                        "passed" if parsed["verdict"] == "pass" else "failed"
                    )
                    result["judge"]["verdict"] = parsed["verdict"]
                    result["outcome"] = (
                        "passed" if parsed["verdict"] == "pass" else "failed"
                    )
        except (EvaluationError, OSError) as exc:
            error = str(exc)
            result["outcome"] = "error"
        finally:
            paths = [worktree, seed]
            if judge_dir is not None:
                paths.append(judge_dir)
            for path in paths:
                try:
                    _remove(path)
                except OSError as exc:
                    error = error or f"cleanup failed: {exc}"
                    result["outcome"] = "error"
            try:
                _remove(base)
            except OSError as exc:
                error = error or f"temporary directory cleanup failed: {exc}"
                result["outcome"] = "error"
    result.setdefault("outcome", "error")
    if error:
        result["error"] = error
    result["artifacts"] = {
        key.replace("-", "_")
        .replace(".jsonl", "")
        .replace(".txt", "")
        .replace(".patch", ""): key
        for key in files
    }
    safe_files = {name: content for name, content in files.items()}
    safe_result = cast(dict[str, Any], _sanitize_json_value(_redact_value(result)))
    _write_output(
        output, {**safe_files, "result.json": json.dumps(safe_result, indent=2) + "\n"}
    )
    if result["outcome"] == "error":
        raise EvaluationError("evaluation infrastructure failed; see result.json")
    return bool(result["outcome"] == "passed")


def _discover_skill_tasks(target: Path, skill: str) -> dict[str, list[Task]]:
    """Return every valid task tagged with `skill`, grouped by category."""
    tasks_root = target / ".codev" / "eval" / "tasks"
    by_category: dict[str, list[Task]] = {}
    if not tasks_root.is_dir():
        return by_category
    for entry in sorted(tasks_root.iterdir()):
        if not entry.is_dir() or entry.is_symlink():
            continue
        try:
            task = validate_task(entry)
        except EvaluationError:
            continue
        if task.skill == skill:
            by_category.setdefault(task.category, []).append(task)
    return by_category


def _condition_percentages(
    with_passed: int, baseline_passed: int, total_runs: int
) -> dict[str, float]:
    with_pct = 100.0 * with_passed / total_runs if total_runs else 0.0
    baseline_pct = 100.0 * baseline_passed / total_runs if total_runs else 0.0
    return {
        "with_skill_percentage": round(with_pct, 1),
        "baseline_percentage": round(baseline_pct, 1),
        "delta": round(with_pct - baseline_pct, 1),
    }


def run_benchmark(
    skill: str,
    target: Path,
    output: Path,
    repetitions: int = 3,
    only_categories: list[str] | None = None,
    git: str = "git",
    opencode: str = "opencode",
    package: bool = True,
    sandbox: str = "worktree",
    docker: str = "docker",
) -> dict[str, Any]:
    """Run every task tagged with `skill`, with it and without it, repeated.

    Answers a sharper question than a single evaluate() call: not "did the
    actor catch this defect once," but "does having this skill installed
    measurably outperform not having it at all." Each task runs
    `repetitions` times per condition (live model output has real sampling
    variance -- one run is a noisy point estimate, not a score). The prompt
    is identical in both conditions; only whether the skill is discoverable
    in the worktree changes (see _stage_skill()). Report is grouped by
    category with a percentage per condition and the delta between them.

    `only_categories`, if given, restricts the run to that subset (e.g. for a
    cheap trial before committing to the full, live-model-costly corpus) --
    every full evaluate() call is a real actor (and, if the verifier passes,
    judge) run against a live model, so cost scales linearly with how many
    tasks times conditions times repetitions actually run.

    An unrestricted run (``only_categories`` is None) also packages this
    report into the skill's own directory as its eval trace -- see
    package_benchmark_trace() and docs/adr/0028-skill-packages-carry-their-own-
    eval-trace.md. A category-restricted run never packages: it is defined
    above as a cheap partial trial, and packaging it would silently make a
    trace claim coverage the run didn't have. Pass ``package=False`` to skip
    packaging even for an unrestricted run.

    ``sandbox``/``docker`` are forwarded unchanged to every evaluate() call,
    the same opt-in Docker sandbox `codev eval task run --sandbox docker`
    uses for a single trial (see docs/adr/0027-opt-in-docker-sandbox-for-the-
    native-eval-harness.md) -- every task in this benchmark must declare its
    own environment block to use it, exactly as for a single task run.
    """
    if repetitions < 1:
        raise EvaluationError("repetitions must be at least 1")
    target = target.resolve()
    output = output.resolve()
    if not output.is_dir() or output.is_symlink() or any(output.iterdir()):
        raise EvaluationError("output must be an existing empty directory")
    by_category = _discover_skill_tasks(target, skill)
    if not by_category:
        raise EvaluationError(f"no tasks found for skill: {skill}")
    if only_categories is not None:
        unknown = sorted(set(only_categories) - set(by_category))
        if unknown:
            raise EvaluationError(
                f"unknown categories for skill {skill!r}: {', '.join(unknown)}; "
                f"available: {', '.join(sorted(by_category))}"
            )
        by_category = {name: by_category[name] for name in only_categories}

    categories: dict[str, Any] = {}
    overall_with_passed = 0
    overall_baseline_passed = 0
    overall_total_runs = 0
    for category in sorted(by_category):
        tasks_report: dict[str, Any] = {}
        for task in by_category[category]:
            condition_counts: dict[str, int] = {}
            for condition_key, with_skill in (
                ("with_skill", True),
                ("baseline", False),
            ):
                passed_count = 0
                for repetition in range(1, repetitions + 1):
                    run_output = (
                        output
                        / skill
                        / category
                        / task.name
                        / condition_key
                        / str(repetition)
                    )
                    run_output.mkdir(parents=True)
                    try:
                        if evaluate(
                            task.name,
                            target,
                            run_output,
                            git=git,
                            opencode=opencode,
                            with_skill=with_skill,
                            sandbox=sandbox,
                            docker=docker,
                        ):
                            passed_count += 1
                    except EvaluationError as exc:
                        (run_output / "benchmark-error.txt").write_text(
                            str(exc), encoding="utf-8"
                        )
                condition_counts[condition_key] = passed_count
            tasks_report[task.name] = {
                "with_skill": {
                    "passed": condition_counts["with_skill"],
                    "total": repetitions,
                },
                "baseline": {
                    "passed": condition_counts["baseline"],
                    "total": repetitions,
                },
            }
        total_runs = len(tasks_report) * repetitions
        with_passed = sum(f["with_skill"]["passed"] for f in tasks_report.values())
        baseline_passed = sum(f["baseline"]["passed"] for f in tasks_report.values())
        categories[category] = {
            "tasks": tasks_report,
            **_condition_percentages(with_passed, baseline_passed, total_runs),
        }
        overall_with_passed += with_passed
        overall_baseline_passed += baseline_passed
        overall_total_runs += total_runs

    report: dict[str, Any] = {
        "schema_version": 1,
        "skill": skill,
        "repetitions": repetitions,
        "categories": categories,
        "overall": _condition_percentages(
            overall_with_passed, overall_baseline_passed, overall_total_runs
        ),
    }
    (output / "benchmark.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    if package and only_categories is None:
        package_benchmark_trace(target, skill, report)
    return report


def package_benchmark_trace(
    target: Path, skill: str, report: dict[str, Any]
) -> Path | None:
    """Write `report` into the skill's own directory as its eval trace.

    Mirrors NVIDIA SkillEvaluator's Recommended Artifact Set (see
    docs/adr/0028-skill-packages-carry-their-own-eval-trace.md): a released
    skill package carries evidence of its own measured effect
    (``evals/benchmark.json``, ``evals/BENCHMARK.md``), not just
    instructions. `codev eval show` reads this back.

    Returns the ``evals/`` directory written, or None if `skill` isn't
    installed under ``.agents/skills/`` in `target` -- packaging is skipped,
    not fatal, since the caller's own `output` directory already durably
    holds the full report regardless of whether packaging succeeds.
    """
    skill_dir = target / ".agents" / "skills" / skill
    if not skill_dir.is_dir():
        return None
    evals_dir = skill_dir / "evals"
    evals_dir.mkdir(exist_ok=True)
    trace = {**report, "generated_at": datetime.now(UTC).isoformat()}
    (evals_dir / "benchmark.json").write_text(
        json.dumps(trace, indent=2) + "\n", encoding="utf-8"
    )
    (evals_dir / "BENCHMARK.md").write_text(
        _render_benchmark_markdown(trace), encoding="utf-8"
    )
    return evals_dir


def _render_benchmark_markdown(report: dict[str, Any]) -> str:
    """Render a packaged benchmark trace as a human-readable Markdown table."""
    rows = [(category, data) for category, data in sorted(report["categories"].items())]
    rows.append(("**Overall**", report["overall"]))
    lines = [
        f"# `{report['skill']}` -- Evaluation Trace",
        "",
        f"Generated: {report.get('generated_at', 'unknown')}",
        f"Repetitions per task: {report['repetitions']}",
        "",
        "| Category | With skill | Baseline | Delta |",
        "| --- | --- | --- | --- |",
    ]
    for name, data in rows:
        lines.append(
            f"| {name} | {data['with_skill_percentage']}% | "
            f"{data['baseline_percentage']}% | {data['delta']:+.1f}pp |"
        )
    lines += [
        "",
        "Full per-task trial evidence is in `evals/benchmark.json` (this "
        "table's underlying data) and in the `--output` directory passed to "
        "`codev eval benchmark run` when this trace was generated.",
        "",
    ]
    return "\n".join(lines)


# --- Public engine-integration surface -------------------------------------
#
# A second evaluation engine (codev_workflow.eval_nvidia, wrapping the
# external NVIDIA SkillEvaluator CLI) needs the same subprocess execution,
# environment isolation, durable publication, and redaction primitives this
# module already uses for the OpenCode actor/judge, without depending on its
# underscore-prefixed internals. These four wrappers are the deliberately
# small, stable surface for that reuse; each delegates unchanged to existing,
# tested behavior. See docs/adr/0026-external-evaluation-engines-are-thin-
# subprocess-wrappers.md.
#
# The three below (git_run, capture_diff, copy_seed_tree) are the equivalent
# surface for codev_workflow.eval_environment's Environment abstraction (see
# docs/adr/0027-opt-in-docker-sandbox-for-the-native-eval-harness.md):
# WorktreeEnvironment is this same worktree logic wearing the Environment
# protocol, not a reimplementation of it.


def run_process(
    argv: list[str],
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
) -> Run:
    """Run one subprocess with this module's timeout/cleanup/escaping rules."""
    return _run(argv, cwd, timeout, env=env)


def isolated_subprocess_env(
    *, extra_allowed: frozenset[str] = frozenset()
) -> dict[str, str]:
    """The base isolated environment, plus a caller-named extra allowlist.

    ``extra_allowed`` must be curated by the caller to exactly what its own
    subprocess needs -- this never becomes a passthrough of the calling
    process's full environment.
    """
    env = _isolated_env()
    if not extra_allowed:
        return env
    allowed_upper = {name.upper() for name in extra_allowed}
    for key, value in os.environ.items():
        if key.upper() in allowed_upper:
            env[key] = value
    return env


def publish_result_bundle(output: Path, files: dict[str, str]) -> None:
    """Atomically publish an evidence bundle using the shared commit-marker
    convention (staged writes, ``.codev-eval-commit.json`` written last)."""
    _write_output(output, files)


def redact_process_text(value: str) -> str:
    """Redact likely secrets from captured subprocess stdout/stderr text."""
    return _safe_process_output(value)


def git_run(git: str, args: list[str], cwd: Path, timeout: int = 60) -> Run:
    """Run one git subcommand with this module's hook/config-isolation rules."""
    return _git(git, args, cwd, timeout=timeout)


def capture_diff(git: str, cwd: Path, seed_commit: str) -> str:
    """Redacted diff of `cwd` against `seed_commit`, including untracked files."""
    return _capture_diff(git, cwd, seed_commit)


def copy_seed_tree(source: Path, destination: Path) -> None:
    """Copy a validated task's repository/ seed without following replacement
    links -- the same symlink-safe copy evaluate() uses for its own worktree
    seed."""
    _copy_seed_tree(source, destination)
