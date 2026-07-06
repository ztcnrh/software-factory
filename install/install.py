#!/usr/bin/env python3
"""Adopt the software factory into a target repository.

Copies the factory's Claude Code config (station skills, subagents, commands,
hooks), the line/policy/label definitions, the spec templates, and — optionally —
the disabled GitHub Actions workflows into <target>, then creates the .factory/
runtime directories. Idempotent: existing files are skipped unless --force.

Usage:
    python3 install/install.py /path/to/your/repo
    python3 install/install.py /path/to/your/repo --with-cloud   # also drop workflows
    python3 install/install.py /path/to/your/repo --force        # overwrite existing
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

FACTORY = Path(__file__).resolve().parents[1]

# Claude Code config copied verbatim into <target>/.claude/.
CLAUDE_ITEMS = [
    "skills/factory-triage",
    "skills/factory-spec",
    "skills/factory-implement",
    "skills/factory-code-review",
    "skills/factory-verify",
    "skills/factory-monitor",
    "skills/factory-retro",
    "skills/council",
    "skills/cross-critique",
    "agents/factory-triage.md",
    "agents/factory-spec.md",
    "agents/factory-implement.md",
    "agents/factory-code-review.md",
    "agents/factory-verify.md",
    "agents/factory-monitor.md",
    "agents/factory-retro.md",
    "commands/factory.md",
    "commands/factory-status.md",
    "hooks/factory_board.py",
    "hooks/record_intervention.py",
]
ROOT_FILES = ["line.yml", "policies.yml", "labels.yml"]


def copy(src: Path, dst: Path, force: bool) -> str:
    if dst.exists() and not force:
        return f"skip (exists): {dst}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)
    return f"copied: {dst}"


def merge_settings(target: Path, force: bool) -> str:
    """Merge the factory's hooks + permission allowlist into the repo's existing
    settings.json rather than clobbering it."""
    src = FACTORY / ".claude" / "settings.json"
    dst = target / ".claude" / "settings.json"
    new = json.loads(src.read_text())
    if not dst.exists() or force:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(new, indent=2) + "\n")
        return f"copied: {dst}"
    existing = json.loads(dst.read_text())
    allow = existing.setdefault("permissions", {}).setdefault("allow", [])
    for a in new.get("permissions", {}).get("allow", []):
        if a not in allow:
            allow.append(a)
    existing.setdefault("hooks", {}).update(new.get("hooks", {}))
    dst.write_text(json.dumps(existing, indent=2) + "\n")
    return f"merged: {dst}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Adopt the software factory into a repo.")
    ap.add_argument("target")
    ap.add_argument(
        "--with-cloud",
        action="store_true",
        help="also copy the (disabled) GitHub Actions workflows",
    )
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    args = ap.parse_args(argv)

    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"✗ target is not a directory: {target}")
        return 1

    log = [copy(FACTORY / ".claude" / i, target / ".claude" / i, args.force) for i in CLAUDE_ITEMS]
    log.append(merge_settings(target, args.force))
    log += [copy(FACTORY / f, target / f, args.force) for f in ROOT_FILES]
    log.append(copy(FACTORY / "templates", target / "templates", args.force))
    for sub in ("work-items", "interventions", "metrics"):
        (target / ".factory" / sub).mkdir(parents=True, exist_ok=True)
    log.append(f"created: {target / '.factory'}")
    if args.with_cloud:
        wf = target / ".github" / "workflows"
        for w in sorted((FACTORY / "workflows").glob("*.disabled")):
            log.append(copy(w, wf / w.name, args.force))

    print("\n".join(log))
    cloud_step = ""
    if args.with_cloud:
        cloud_step = "\n  5. Cloud: see docs/CLOUD-AUTONOMY.md to enable the workflows."
    print(
        f"""
✓ Factory installed into {target}

Next steps:
  1. Put the `factory` CLI on PATH:   uv tool install {FACTORY}
  2. Initialize state:                cd {target} && factory init
  3. Create your first work item:     factory new "my first feature"
  4. Drive it in Claude Code:         /factory{cloud_step}
"""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
