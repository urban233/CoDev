"""Interactive and scripted conflict resolution for `codev update`.

`installer.plan_update` already classifies every managed-file mismatch as a
"conflict" operation rather than guessing; this module is the layer that
turns those conflicts into a decision per file -- either a human walking
through them one at a time (`run_wizard`), or one blanket policy applied to
all of them at once (`resolve_non_interactive`, for `--on-conflict` /
scripts / CI). Both return a `{relative_path: Resolution}` mapping that
`installer.apply_plan` consumes; neither writes to disk itself.

Three conflict paths -- `AGENTS.md`, `.gitignore`, `.opencode/opencode.json`
-- are managed as embedded blocks or a JSON merge rather than a whole file,
so there is no single "upstream replacement" to diff or copy. Both
resolvers deliberately leave those out of the returned mapping; they stay
conflicts and must still be resolved by hand.
"""

from __future__ import annotations

import difflib
import sys
from collections.abc import Callable
from pathlib import Path

from codev_workflow.installer import CoDevError, Plan, Resolution

SPECIAL_INTEGRATION_PATHS = frozenset(
    {"AGENTS.md", ".gitignore", ".opencode/opencode.json"}
)


def _decode_lines(content: bytes) -> list[str] | None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text.splitlines(keepends=True)


def render_diff(path: str, local: bytes, upstream: bytes) -> str:
    """A unified diff of `local` vs. `upstream`, or a note when not textual."""

    local_lines = _decode_lines(local)
    upstream_lines = _decode_lines(upstream)
    if local_lines is None or upstream_lines is None:
        return "(binary or non-UTF-8 content -- no diff available)"
    diff = "".join(
        difflib.unified_diff(
            local_lines,
            upstream_lines,
            fromfile=f"{path} (local)",
            tofile=f"{path} (upstream)",
        )
    )
    return diff or "(no textual difference)"


def run_wizard(
    target: Path,
    plan: Plan,
    *,
    input_fn: Callable[[str], str] = input,
    output: Callable[..., None] = print,
) -> dict[str, Resolution]:
    """Walk the user through each of `plan`'s conflicts, one at a time.

    Requires an interactive terminal. For each conflict: override adopts
    upstream's content, keep leaves the local file untouched and accepts it
    as the new baseline, copy writes upstream's content beside the file
    (`<name>.copy`) without touching the original, delete removes the local
    file, and skip leaves it exactly as unresolved as it was before this
    call. Override and copy are only offered when there is upstream content
    to act on. `q`uit stops early; everything decided up to that point is
    still returned.
    """
    if not sys.stdin.isatty():
        raise CoDevError(
            "codev update --resolve needs an interactive terminal; use "
            "--on-conflict for a non-interactive run"
        )
    target = target.resolve()
    resolutions: dict[str, Resolution] = {}
    conflicts = plan.conflicts
    for index, op in enumerate(conflicts, start=1):
        output(f"\n[{index}/{len(conflicts)}] {op.path}")
        output(f"  {op.detail}")
        if op.path in SPECIAL_INTEGRATION_PATHS:
            output(
                "  this conflict type isn't covered by the wizard yet -- "
                "resolve it by hand, then re-run `codev update`"
            )
            continue
        destination = target / Path(op.path)
        if op.new_content is not None:
            local = destination.read_bytes() if destination.is_file() else b""
            output(render_diff(op.path, local, op.new_content))
            choices = "[o]verride  [k]eep  [c]opy  [d]elete  [s]kip  [q]uit"
            valid = {
                "o": Resolution.OVERRIDE,
                "k": Resolution.KEEP,
                "c": Resolution.COPY,
                "d": Resolution.DELETE,
                "s": Resolution.SKIP,
            }
        else:
            output("  upstream no longer ships this file.")
            choices = "[k]eep  [d]elete  [s]kip  [q]uit"
            valid = {
                "k": Resolution.KEEP,
                "d": Resolution.DELETE,
                "s": Resolution.SKIP,
            }
        while True:
            answer = input_fn(f"  {choices} > ").strip().lower()
            if answer == "q":
                return resolutions
            if answer in valid:
                resolutions[op.path] = valid[answer]
                break
            output(f"  unrecognized choice: {answer!r}")
    return resolutions


def resolve_non_interactive(plan: Plan, policy: Resolution) -> dict[str, Resolution]:
    """Apply one `policy` to every conflict `--on-conflict` can reach.

    A conflict with no upstream content (`new_content is None`) can't take
    OVERRIDE or COPY -- there is nothing to write -- so those fall back to
    SKIP there rather than raising, leaving it reported as still
    unresolved rather than silently guessing DELETE on the caller's behalf.
    """
    resolutions: dict[str, Resolution] = {}
    for op in plan.conflicts:
        if op.path in SPECIAL_INTEGRATION_PATHS:
            continue
        if policy in (Resolution.OVERRIDE, Resolution.COPY) and op.new_content is None:
            resolutions[op.path] = Resolution.SKIP
        else:
            resolutions[op.path] = policy
    return resolutions
