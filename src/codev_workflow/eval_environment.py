"""Where a trial's actor actually executes: the worktree/Docker abstraction.

`WorktreeEnvironment` is `evaluate()`'s existing git-worktree isolation,
wearing this module's `Environment` protocol -- it delegates to the same
promoted helpers (`git_run`, `capture_diff`, `copy_seed_tree`) `evaluate()`
itself uses, so it is not a reimplementation and carries no behavior change.
`DockerEnvironment` is new and strictly opt-in: it only runs for a task that
declares its own `environment: {"backend": "docker", "image": "..."}` block
and only when the caller explicitly selects `--sandbox docker`. CoDev never
builds, pulls, or ships that image -- see
docs/adr/0027-opt-in-docker-sandbox-for-the-native-eval-harness.md.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Protocol

from codev_workflow.eval import (
    EvaluationError,
    Run,
    capture_diff,
    copy_seed_tree,
    git_run,
    run_process,
)

_MOUNT_POINT = "/workspace"


class Environment(Protocol):
    def create(self, seed_source: Path) -> Path:
        """Materialize `seed_source` (a task's repository/ seed) somewhere the
        actor can run against; return the actor's working directory."""
        ...

    def run(
        self,
        argv: list[str],
        cwd: Path,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> Run:
        """Run one command as the actor (or verifier) would see it."""
        ...

    def capture_diff(self, seed_commit: str) -> str:
        """Redacted diff of the working directory against `seed_commit`."""
        ...

    def cleanup(self) -> None:
        """Remove everything this environment created. Idempotent."""
        ...


class WorktreeEnvironment:
    """Existing isolation: a temporary Git worktree on the host."""

    def __init__(self, git: str = "git"):
        self._git = git
        self._base: Path | None = None
        self._seed: Path | None = None
        self._worktree: Path | None = None

    def create(self, seed_source: Path) -> Path:
        self._base = Path(tempfile.mkdtemp(prefix="codev-eval-"))
        self._seed = self._base / "seed"
        self._worktree = self._base / "worktree"
        copy_seed_tree(seed_source, self._seed)
        for args in (
            ["init"],
            ["config", "user.email", "codev@example.invalid"],
            ["config", "user.name", "CoDev"],
            ["add", "."],
            ["commit", "-m", "seed"],
        ):
            run = git_run(self._git, list(args), self._seed)
            if run.code != 0:
                raise EvaluationError(f"git seed phase failed: {run.stderr}")
        run = git_run(
            self._git,
            ["worktree", "add", "--detach", str(self._worktree), "HEAD"],
            self._seed,
        )
        if run.code != 0:
            raise EvaluationError(f"git worktree phase failed: {run.stderr}")
        return self._worktree

    def run(
        self,
        argv: list[str],
        cwd: Path,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> Run:
        return run_process(argv, cwd, timeout, env=env)

    def capture_diff(self, seed_commit: str) -> str:
        assert self._worktree is not None
        return capture_diff(self._git, self._worktree, seed_commit)

    def cleanup(self) -> None:
        if self._base is not None:
            shutil.rmtree(self._base, ignore_errors=True)
            self._base = None


class DockerEnvironment:
    """Opt-in isolation: the actor runs inside a container built from a
    task-declared image. The seed is still a real Git worktree on the host
    (so diff capture works exactly like WorktreeEnvironment's) -- only the
    actor's own subprocess is redirected to run inside the container, with
    that worktree bind-mounted at a fixed mount point.
    """

    def __init__(self, image: str, docker: str = "docker", git: str = "git"):
        self.image = image
        self._docker = docker
        self._worktree_env = WorktreeEnvironment(git=git)

    def create(self, seed_source: Path) -> Path:
        if shutil.which(self._docker) is None:
            raise EvaluationError(
                f"this task's environment declares docker, but no `{self._docker}` "
                "executable is on PATH"
            )
        return self._worktree_env.create(seed_source)

    def run(
        self,
        argv: list[str],
        cwd: Path,
        timeout: int,
        env: dict[str, str] | None = None,
    ) -> Run:
        """Run `argv` inside a container with `cwd` mounted at /workspace.

        Any argv element that is exactly `str(cwd)` is rewritten to the
        mount point -- the convention `evaluate()`'s own actor/verifier argv
        already follows (e.g. `--dir <cwd>`), so no argv-specific knowledge
        of OpenCode's flags is needed here.
        """
        remapped = [_MOUNT_POINT if part == str(cwd) else part for part in argv]
        docker_argv = [
            self._docker,
            "run",
            "--rm",
            "-v",
            f"{cwd}:{_MOUNT_POINT}",
            "-w",
            _MOUNT_POINT,
            self.image,
            *remapped,
        ]
        return run_process(docker_argv, cwd, timeout, env=env)

    def capture_diff(self, seed_commit: str) -> str:
        return self._worktree_env.capture_diff(seed_commit)

    def cleanup(self) -> None:
        self._worktree_env.cleanup()
