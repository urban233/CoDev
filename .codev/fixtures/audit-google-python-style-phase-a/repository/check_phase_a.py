"""Verify that the Phase A actor made no changes to the seeded sample."""

import hashlib
import subprocess
from pathlib import Path


EXPECTED = "e8ac067f3a095abb0b2d6e9df478073f7300c76a952ba4ba0e887c47fc445b0b"


def main() -> int:
    """Return zero only when the worktree and sample remain unchanged."""
    status = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=False
    )
    sample = Path("src/pyssa/controllers/delete_project_controller.py")
    digest = hashlib.sha256(sample.read_bytes()).hexdigest()
    if status.stdout or digest != EXPECTED:
        print("Phase A changed the fixture repository.")
        return 1
    print("Phase A repository remains unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
