"""Optional GitHub mirror via the ``gh`` CLI.

Local JSON is the source of truth; this keeps a GitHub issue's ``factory:<state>``
label in sync and posts gate review packets as comments. Every call is a no-op
(returns a non-zero code) if ``gh`` is missing, so nothing here is load-bearing.
"""

from __future__ import annotations

import shutil
import subprocess

STATE_LABEL = {
    "triage": "factory:triage",
    "spec": "factory:spec",
    "spec_review": "factory:spec-review",
    "implement": "factory:implement",
    "code_review": "factory:code-review",
    "verify": "factory:verify",
    "ship_review": "factory:ship-review",
    "ci_cd": "factory:ci-cd",
    "ship": "factory:ci-cd",
    "monitor": "factory:monitor",
    "needs_human": "factory:needs-human",
    "blocked": "factory:blocked",
    "parked": "factory:parked",
    "done": "factory:done",
}


def available() -> bool:
    return shutil.which("gh") is not None


def _run(args: list[str]) -> tuple[int, str]:
    if not available():
        return 127, "gh not installed"
    p = subprocess.run(["gh", *args], capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def sync_label(
    issue: str, new_state: str, old_state: str | None = None, repo: str | None = None
) -> tuple[int, str]:
    add = STATE_LABEL.get(new_state)
    args = ["issue", "edit", issue]
    if add:
        args += ["--add-label", add]
    old = STATE_LABEL.get(old_state) if old_state else None
    if old and old != add:
        args += ["--remove-label", old]
    if repo:
        args += ["--repo", repo]
    return _run(args)


def comment(issue: str, body: str, repo: str | None = None) -> tuple[int, str]:
    args = ["issue", "comment", issue, "--body", body]
    if repo:
        args += ["--repo", repo]
    return _run(args)
