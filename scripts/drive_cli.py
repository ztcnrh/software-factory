#!/usr/bin/env python3
"""Drive the `factory` CLI end to end against a throwaway root.

Green unit tests are not enough for `cli.py` — the last several real bugs there
were invisible to the suite because they lived in argument wiring, exit codes, or
the `NEXT:` contract rather than in the dispatcher. This walks a work item from
intake to `done` through the actual command line.

It follows the `NEXT:` directive rather than hardcoding the route, so a change to
`line.yml`'s topology doesn't break it — only a change to the *contract* does,
which is the thing worth breaking on.

    python3 scripts/drive_cli.py          # uses `uv run factory`
    FACTORY_CMD="factory" python3 scripts/drive_cli.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CMD = os.environ.get("FACTORY_CMD", "uv run factory").split()

# One verdict per state, chosen to walk the happy path. A state the line grows
# later shows up as a clear KeyError here rather than an infinite loop.
HAPPY_PATH = {
    "triage": "needs_spec",
    "spec": "ready_for_review",
    "spec_review": "approved",
    "implement": "implemented",
    "code_review": "pass",
    "verify": "verified",
    "ship_review": "approved",
    "deploy": "succeeded",
}
MAX_STEPS = 40  # a routing loop should fail the run, not hang the runner

failures: list[str] = []


def check(name: str, cond: object, detail: str = "") -> None:
    ok = bool(cond)
    if not ok:
        failures.append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   [{detail}]" if detail and not ok else ""))


def factory(root: Path, *args: str, expect_rc: int = 0) -> str:
    r = subprocess.run(
        [*CMD, "--root", str(root), *args], capture_output=True, text=True, cwd=REPO, timeout=120
    )
    assert r.returncode == expect_rc, f"rc={r.returncode} args={args}\n{r.stdout}\n{r.stderr}"
    return r.stdout


def next_action(root: Path, item: str) -> dict:
    """The NEXT: line is the engine's only API contract with a driver — parse it
    the way a driver does, so a malformed or missing line fails the drive."""
    out = factory(root, "next", item)
    lines = [ln for ln in out.splitlines() if ln.startswith("NEXT: ")]
    assert len(lines) == 1, f"expected exactly one NEXT: line, got {len(lines)}\n{out}"
    return json.loads(lines[0][len("NEXT: ") :])


class Graded:
    """An item at code_review with a registered checklist, and a way to grade it."""

    def __init__(self, root: Path, item: str, rel: str):
        self.root, self.item, self.rel = root, item, rel

    def grade(self, implemented: str = "", holds: str = "") -> None:
        (self.root / self.rel).write_text(
            "# Invariant checklist\n\n"
            "| # | Invariant | Implemented | Holds |\n| - | - | - | - |\n\n"
            "<!-- machine-readable: the factory engine parses this block -->\n"
            "```yaml\nrows:\n"
            '  - n: 1\n    invariant: "Over the limit returns 429"\n'
            f'    implemented: "{implemented}"\n    holds: "{holds}"\n'
            "```\n"
        )


def walk_to_code_review(root: Path) -> Graded:
    """A second item taken to code_review carrying an ungraded checklist."""
    out = factory(root, "new", "checklist guard item")
    item = next(w for w in out.split() if w.startswith("WI-")).strip(":.,")
    rel = f"specs/{item}-x/CHECKLIST.md"
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    g = Graded(root, item, rel)
    g.grade()  # both columns blank — the state the spec station leaves behind
    factory(root, "advance", item, "--verdict", "needs_spec")
    factory(root, "advance", item, "--verdict", "ready_for_review", "--artifact", rel)
    factory(root, "gate", item, "--decision", "approved", "--by", "drive-script")
    factory(root, "advance", item, "--verdict", "implemented")
    return g


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="factory-drive-"))
    try:
        for f in ("line.yml", "policies.yml", "classifiers.yml"):
            shutil.copy2(REPO / f, tmp / f)

        print("\n=== init ===")
        check("init succeeds", "factory initialized" in factory(tmp, "init"))
        check("runtime dirs exist", (tmp / ".factory" / "work-items").is_dir())
        # A nested dir, not a second mkdtemp: it rides the same cleanup as `tmp`.
        bare = tmp / "bare-root"
        bare.mkdir()
        factory(bare, "init", expect_rc=1)
        check("init on a config-less root exits 1", True)

        print("\n=== intake ===")
        out = factory(tmp, "new", "smoke test item", "--body", "driven by scripts/drive_cli.py")
        item = next(w for w in out.split() if w.startswith("WI-")).strip(":.,")
        check("new mints an id", item.startswith("WI-"), out)
        check("item file on disk", (tmp / ".factory" / "work-items" / f"{item}.json").exists())
        factory(tmp, "status", "WI-9999", expect_rc=1)
        check("unknown id exits 1", True)
        out = factory(
            tmp, "new", "jira-sourced item", "--source", "jira", "--source-ref", "AMPS-104"
        )
        jitem = next(w for w in out.split() if w.startswith("WI-")).strip(":.,")
        jstatus = factory(tmp, "status", jitem)
        check("a jira-sourced item records its ticket", "jira AMPS-104" in jstatus)
        factory(tmp, "new", "mystery ref", "--source-ref", "AMPS-105", expect_rc=1)
        check("a non-numeric ref without --source is refused", True)
        out = factory(tmp, "feedback", item)
        check("feedback on a PR-less item is a calm no-op", "no pull requests recorded" in out)

        print("\n=== walk the line ===")
        seen: list[str] = []
        announced_checking: set[str] = set()
        briefed = False
        for _ in range(MAX_STEPS):
            action = next_action(tmp, item)
            state = action["state"]
            seen.append(state)
            if action.get("checking"):
                announced_checking.add(state)
            if action["type"] == "done":
                break
            if not briefed and action["type"] == "run_station":
                # A brief is only meaningful mid-run, so it has to be exercised here
                # rather than after the item terminates.
                factory(tmp, "brief", item)
                brief = tmp / ".factory" / "work-items" / item / "runs" / f"{state}-brief.md"
                check("brief renders to the path the driver is told to read", brief.exists())
                check("brief carries the request", "smoke test item" in brief.read_text())
                briefed = True
            verdict = HAPPY_PATH[state]
            if action["type"] == "human_gate":
                factory(tmp, "gate", item, "--decision", verdict, "--by", "drive-script")
            else:
                factory(tmp, "advance", item, "--verdict", verdict, "--summary", f"{state} ok")
        else:
            check("line terminates within the step cap", False, " → ".join(seen))

        print(f"  route: {' → '.join(seen)}")
        check("reached done", seen[-1] == "done")
        check("passed through both checking stations", {"code_review", "verify"} <= set(seen))
        # Isolation stops being the driver's job to remember only if the engine
        # actually says so in the machine-readable directive.
        check(
            "NEXT flags the checking stations",
            announced_checking == {"code_review", "verify"},
            str(sorted(announced_checking)),
        )

        print("\n=== the contract the driver reads ===")
        check("status renders", item in factory(tmp, "status", item))
        check("board renders", "Factory board" in factory(tmp, "status"))
        check("ledger renders", factory(tmp, "ledger", "list") is not None)
        m = factory(tmp, "metrics")
        check("metrics count the ship", "1/1" in m, m)
        check("metrics report a clean one-shot rate", "100%" in m, m)
        check("doctor is clean on a healthy root", "✓" in factory(tmp, "doctor"))

        print("\n=== the checklist guards, through the real CLI ===")
        # The unit tests drive the dispatcher directly; only here is the refusal
        # exercised as an exit code, which is all a driver sees.
        chk = walk_to_code_review(tmp)
        factory(tmp, "advance", chk.item, "--verdict", "pass", expect_rc=1)
        check("pass is refused while a row is ungraded", True)
        check("nothing routed", "state: code_review" in factory(tmp, "status", chk.item))
        chk.grade(implemented="no")
        factory(tmp, "advance", chk.item, "--verdict", "pass")
        check("an explicit `no` is an answer and lets pass through", True)
        out = factory(tmp, "status", chk.item)
        check("status carries the checklist headline", "checklist:" in out, out)
        check("the headline names the invariant the diff misses", "not implemented" in out, out)
        factory(tmp, "advance", chk.item, "--verdict", "verified", expect_rc=1)
        check("verified is refused while a row is undisposed", True)

        print("\n=== rejections are refusals, not crashes ===")
        factory(tmp, "advance", item, "--verdict", "not-a-real-verdict", expect_rc=1)
        check("unknown verdict exits 1", True)
        factory(tmp, "gate", item, "--decision", "approved", expect_rc=1)
        check("gate on a terminal item exits 1", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(failures)
    print(f"\n{'=' * 56}")
    if total:
        print(f"{total} check(s) FAILED:")
        for n in failures:
            print(f"  - {n}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
