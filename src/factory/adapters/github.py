"""Optional GitHub mirror via the ``gh`` CLI.

Local JSON is the source of truth; this keeps a GitHub issue's ``factory:<state>``
label in sync, posts gate review packets as comments, and lists labeled issues
for the intake sensor (``factory intake``). Every call is a no-op (returns a
non-zero code) if ``gh`` is missing, so nothing here is load-bearing.
"""

from __future__ import annotations

import json
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
    "deploy": "factory:deploy",
    "needs_human": "factory:needs-human",
    "blocked": "factory:blocked",
    "parked": "factory:parked",
    "done": "factory:done",
}


def available() -> bool:
    return shutil.which("gh") is not None


def _run2(args: list[str]) -> tuple[int, str, str]:
    """Run gh keeping stdout and stderr apart — stdout must stay clean for the
    ``--json`` callers."""
    if not available():
        return 127, "", "gh not installed"
    p = subprocess.run(["gh", *args], capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def _run(args: list[str]) -> tuple[int, str]:
    rc, out, err = _run2(args)
    return rc, (out + err).strip()


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


def list_issues(
    label: str, repo: str | None = None, limit: int = 50
) -> tuple[int, list[dict], str]:
    """Open issues carrying ``label`` — the intake sensor's read side. Returns
    ``(rc, issues, error)``; issues are dicts with number/title/body/url."""
    args = [
        "issue",
        "list",
        "--label",
        label,
        "--state",
        "open",
        "--limit",
        str(limit),
        "--json",
        "number,title,body,url",
    ]
    if repo:
        args += ["--repo", repo]
    rc, out, err = _run2(args)
    if rc != 0:
        return rc, [], (err.strip() or out.strip())
    try:
        return 0, json.loads(out or "[]"), ""
    except json.JSONDecodeError:
        return 1, [], f"unparseable gh output: {out[:200]!r}"
