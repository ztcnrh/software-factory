#!/usr/bin/env python3
"""Adopt the software factory into a target repository.

Copies the factory's Claude Code config (station skills, subagents, commands,
hooks), the line/policy/label definitions, the spec templates, the human's
FACTORY-MANUAL.md, and — optionally — the disabled GitHub Actions workflows into
<target>, then creates the .factory/ runtime directories. Also plants a short
factory pointer block in the repo's CLAUDE.md (between sentinel markers; only
that block is ever touched, and a reinstall refreshes it) and stamps
.factory/install-manifest.json (toolkit version/commit + which paths this
installer created — what makes uninstall safe and reinstalls version-aware).
Idempotent: existing files are skipped unless --force, which overwrites only
factory-owned files, never the project's own.

Usage:
    python3 install/install.py /path/to/your/repo --dry-run      # review the plan
    python3 install/install.py /path/to/your/repo
    python3 install/install.py /path/to/your/repo --with-cloud   # also drop workflows
    python3 install/install.py /path/to/your/repo --force        # refresh factory files
    python3 install/install.py /path/to/your/repo --uninstall    # remove (keeps .factory/)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

FACTORY = Path(__file__).resolve().parents[1]


def _toolkit_version() -> str:
    """The toolkit's version, read from pyproject.toml (the single source)."""
    m = re.search(r'^version\s*=\s*"([^"]+)"', (FACTORY / "pyproject.toml").read_text(), re.M)
    return m.group(1) if m else "unknown"


def _toolkit_commit() -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(FACTORY), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"

# Claude Code config copied verbatim into <target>/.claude/.
CLAUDE_ITEMS = [
    "skills/factory-triage",
    "skills/factory-spec",
    "skills/factory-implement",
    "skills/factory-code-review",
    "skills/factory-verify",
    "skills/factory-retro",
    "skills/council",
    "agents/factory-triage.md",
    "agents/factory-spec.md",
    "agents/factory-implement.md",
    "agents/factory-code-review.md",
    "agents/factory-verify.md",
    "agents/factory-retro.md",
    "commands/factory.md",
    "commands/factory-status.md",
    "hooks/factory_board.py",
    "hooks/record_intervention.py",
]
ROOT_FILES = ["line.yml", "policies.yml", "labels.yml", "FACTORY-MANUAL.md"]

# The CLAUDE.md pointer block. CLAUDE.md is the one context channel with an
# unconditional load guarantee (every session, from turn one, even before the
# repo's hooks are trusted) — so it carries discovery pointers and the standing
# "prefer the factory" policy, never the rules themselves (those live in
# .claude/commands/factory.md and the station skills, their single homes).
_BLOCK_BEGIN = "<!-- factory:begin -->"
_BLOCK_END = "<!-- factory:end -->"
CLAUDE_MD_BLOCK = (
    f"{_BLOCK_BEGIN}\n"
    "## Software factory\n"
    "Delivery work in this repo runs on a software factory: a deterministic dispatcher "
    "(the `factory` CLI + `line.yml`) moves work items station by station and pauses at "
    "human gates. When asked to build a feature or fix a bug, prefer driving it through "
    "the factory rather than working ad hoc — `/factory <request>`, or read "
    "`.claude/commands/factory.md`, the driver protocol.\n"
    "For any factory command, `factory <cmd> -h` is the source-of-truth reference. "
    "The human's operating guide is `FACTORY-MANUAL.md`. "
    "(This block is managed by the factory's install.py; a reinstall refreshes it.)\n"
    f"{_BLOCK_END}\n"
)


def plant_claude_md(target: Path, dry: bool = False) -> str:
    """Plant (or refresh) the factory pointer block in the repo's CLAUDE.md.

    Only the sentinel-marked block is ever written: existing content outside the
    markers is preserved byte-for-byte, and a stale block between the markers is
    replaced — so upgrades propagate without --force and without clobbering the
    project's own instructions."""
    path = target / "CLAUDE.md"
    if not path.exists():
        if dry:
            return f"would create: {path}"
        path.write_text(CLAUDE_MD_BLOCK)
        return f"created: {path}"
    text = path.read_text()
    if _BLOCK_BEGIN in text and _BLOCK_END in text:
        if dry:
            return f"would refresh factory block: {path}"
        head, rest = text.split(_BLOCK_BEGIN, 1)
        tail = rest.split(_BLOCK_END, 1)[1]
        path.write_text(head + CLAUDE_MD_BLOCK.rstrip("\n") + tail)
        return f"refreshed factory block: {path}"
    if dry:
        return f"would append factory block: {path}"
    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    path.write_text(text + sep + CLAUDE_MD_BLOCK)
    return f"appended factory block: {path}"


def strip_claude_md(target: Path, dry: bool) -> str | None:
    """Reverse plant_claude_md: remove the marked block, preserving everything
    else; if the file held nothing but our block, remove the file."""
    path = target / "CLAUDE.md"
    if not path.exists():
        return None
    text = path.read_text()
    if _BLOCK_BEGIN not in text or _BLOCK_END not in text:
        return None
    if dry:
        return f"would strip factory block from: {path}"
    head = text.split(_BLOCK_BEGIN, 1)[0]
    tail = text.split(_BLOCK_END, 1)[1]
    remains = (head.rstrip("\n") + "\n\n" + tail.lstrip("\n")).strip("\n")
    if remains:
        path.write_text(remains + "\n")
        return f"stripped factory block from: {path}"
    path.unlink()
    return f"removed: {path} (contained only the factory block)"


# --- the install manifest -----------------------------------------------------
# Written to .factory/install-manifest.json: which toolkit version/commit was
# installed, when, and which paths the installer actually created (vs. skipped
# because they already existed). This is what makes uninstall safe (only remove
# what we created), reinstalls version-aware, and future upgrade/divergence
# tooling possible (see docs/OPTIMIZATION-AREAS.md §6).

_MANIFEST_REL = ".factory/install-manifest.json"

# Shared files are never blind-deleted by uninstall or the reinstall prune: even
# when the installer created them, the user may have added their own content
# since. Their strip/unmerge paths remove only the factory's part.
_SHARED_FILES = {"CLAUDE.md", ".claude/settings.json"}


def _shipped_paths() -> list[str]:
    """Every repo-relative path the CURRENT toolkit ships. The single source for
    the uninstall fallback (pre-manifest installs) and the reinstall prune of
    retired paths — both must agree on what 'ours' means."""
    paths = [f".claude/{i}" for i in CLAUDE_ITEMS] + ROOT_FILES + ["templates"]
    paths += [f".github/workflows/{w.name}" for w in (FACTORY / "workflows").glob("*.disabled")]
    return paths


def prune_retired(target: Path, prior: dict | None, dry: bool) -> list[str]:
    """On reinstall, remove previously-installed paths the current toolkit no
    longer ships (e.g. a skill that was folded into another). Without this, an
    upgrade leaves the retired skill live in the target repo until a full
    uninstall. Pruned entries also leave the manifest so they don't resurrect."""
    if not prior or not prior.get("created"):
        return []
    shipped = set(_shipped_paths())
    log, kept = [], []
    for rel in prior["created"]:
        if rel in shipped or rel in _SHARED_FILES:
            kept.append(rel)
            continue
        p = target / rel
        if p.exists():
            if dry:
                log.append(f"would remove (retired): {p}")
            else:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
                log.append(f"removed (retired): {p}")
    if not dry:
        prior["created"] = kept
    return log


def read_manifest(target: Path) -> dict | None:
    path = target / _MANIFEST_REL
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def write_manifest(target: Path, log: list[str], prior: dict | None) -> str:
    created_now = []
    for line in log:
        for prefix in ("copied: ", "created: "):
            if line.startswith(prefix):
                created_now.append(str(Path(line[len(prefix) :]).relative_to(target)))
    manifest = {
        "toolkit_version": _toolkit_version(),
        "toolkit_commit": _toolkit_commit(),
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "created": sorted(set((prior or {}).get("created", [])) | set(created_now)),
    }
    path = target / _MANIFEST_REL
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return f"stamped: {path} (v{manifest['toolkit_version']} @ {manifest['toolkit_commit']})"


def uninstall(target: Path, prior: dict | None, dry: bool) -> int:
    """Remove the factory from a repo: delete what the installer created, unmerge
    settings.json, strip the CLAUDE.md block. Deliberately leaves .factory/ —
    that's the repo's own history (work items, interventions, metrics)."""
    if prior and prior.get("created"):
        owned = prior["created"]
        print(f"uninstalling factory v{prior.get('toolkit_version', '?')} (per install manifest)")
    else:
        owned = _shipped_paths()
        print("⚠ no install manifest found (pre-manifest install) — removing the standard file set")
    log = []
    for rel in sorted(set(owned) - _SHARED_FILES):
        p = target / rel
        if not p.exists():
            continue
        if dry:
            log.append(f"would remove: {p}")
        else:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
            log.append(f"removed: {p}")
    log.append(strip_claude_md(target, dry))
    log.append(unmerge_settings(target, dry))
    if not dry:  # prune now-empty factory parent dirs (user content keeps them alive)
        for rel in (
            ".claude/skills",
            ".claude/agents",
            ".claude/commands",
            ".claude/hooks",
            ".claude",
            ".github/workflows",
            ".github",
        ):
            p = target / rel
            if p.is_dir() and not any(p.iterdir()):
                p.rmdir()
    # A workflow the user enabled (renamed away from .disabled, added secrets)
    # is a deliberate act of theirs — never delete it, but say it's still there.
    for w in sorted((FACTORY / "workflows").glob("*.disabled")):
        live = target / ".github" / "workflows" / w.name.removesuffix(".disabled")
        if live.exists():
            log.append(f"⚠ enabled workflow left in place (you activated it): {live}")
    print("\n".join(line for line in log if line))
    if dry:
        print(f"\nDry run — nothing was removed. Rerun to uninstall from {target}")
        return 0
    print(
        f"""
✓ Factory removed from {target}
  Left in place: .factory/ — your work items, interventions, and metrics (the
  factory's memory, including the install manifest). Delete it manually for a
  clean slate. Review the diff and commit when satisfied.
"""
    )
    return 0


def copy(src: Path, dst: Path, force: bool, dry: bool = False) -> str:
    if dst.exists() and not force:
        return f"skip (exists): {dst}"
    if dry:
        return f"would copy: {dst}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)
    return f"copied: {dst}"


def merge_settings(target: Path, dry: bool = False) -> str:
    """Merge the factory's hooks + permission allowlist into the repo's existing
    settings.json rather than clobbering it. settings.json is shared real estate
    (the project's own hooks/permissions live there too), so even --force never
    replaces it wholesale — the merge already refreshes the factory's entries."""
    src = FACTORY / ".claude" / "settings.json"
    dst = target / ".claude" / "settings.json"
    new = json.loads(src.read_text())
    if not dst.exists():
        if dry:
            return f"would copy: {dst}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(new, indent=2) + "\n")
        return f"copied: {dst}"
    if dry:
        return f"would merge hooks + permissions into: {dst}"
    existing = json.loads(dst.read_text())
    allow = existing.setdefault("permissions", {}).setdefault("allow", [])
    for a in new.get("permissions", {}).get("allow", []):
        if a not in allow:
            allow.append(a)
    existing.setdefault("hooks", {}).update(new.get("hooks", {}))
    dst.write_text(json.dumps(existing, indent=2) + "\n")
    return f"merged: {dst}"


def _hollow(value: object) -> bool:
    """True when a JSON value holds no real content (only empty containers)."""
    if isinstance(value, dict):
        return all(_hollow(v) for v in value.values())
    if isinstance(value, list):
        return all(_hollow(v) for v in value)
    return not value


def unmerge_settings(target: Path, dry: bool) -> str | None:
    """Reverse merge_settings: remove the factory's own hook groups, permission
    entries, and comment from the repo's settings.json, leaving everything else
    untouched. If nothing but empty husks remain (we created the file and the
    user never added to it), remove the file itself."""
    dst = target / ".claude" / "settings.json"
    if not dst.exists():
        return None
    fact = json.loads((FACTORY / ".claude" / "settings.json").read_text())
    cur = json.loads(dst.read_text())
    changed = False
    allow = cur.get("permissions", {}).get("allow", [])
    for a in fact.get("permissions", {}).get("allow", []):
        while a in allow:
            allow.remove(a)
            changed = True
    hooks = cur.get("hooks", {})
    for k, v in fact.get("hooks", {}).items():
        if hooks.get(k) == v:
            del hooks[k]
            changed = True
    if cur.get("$comment") == fact.get("$comment"):
        del cur["$comment"]
        changed = True
    if not changed:
        return None
    if _hollow(cur):
        if dry:
            return f"would remove: {dst} (holds only factory settings)"
        dst.unlink()
        return f"removed: {dst} (held only factory settings)"
    if dry:
        return f"would remove factory hooks + permissions from: {dst}"
    dst.write_text(json.dumps(cur, indent=2) + "\n")
    return f"removed factory hooks + permissions from: {dst}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Adopt the software factory into a repo.")
    ap.add_argument("target")
    ap.add_argument(
        "--with-cloud",
        action="store_true",
        help="also copy the (disabled) GitHub Actions workflows",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing factory-owned files (never the project's own; "
        "settings.json is always merged, CLAUDE.md only its marked block)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="list every operation without writing anything (review the plan, then rerun)",
    )
    ap.add_argument(
        "--uninstall",
        action="store_true",
        help="remove the factory from the target (keeps .factory/ state; see --dry-run)",
    )
    args = ap.parse_args(argv)

    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"✗ target is not a directory: {target}")
        return 1

    dry = args.dry_run
    prior = read_manifest(target)
    if args.uninstall:
        return uninstall(target, prior, dry)
    if prior:
        print(
            f"→ previously installed: v{prior.get('toolkit_version', '?')} "
            f"({prior.get('toolkit_commit', '?')}) at {prior.get('installed_at', '?')}; "
            f"installing v{_toolkit_version()} ({_toolkit_commit()})"
        )

    log = prune_retired(target, prior, dry)
    log += [
        copy(FACTORY / ".claude" / i, target / ".claude" / i, args.force, dry)
        for i in CLAUDE_ITEMS
    ]
    log.append(merge_settings(target, dry))
    log += [copy(FACTORY / f, target / f, args.force, dry) for f in ROOT_FILES]
    log.append(copy(FACTORY / "templates", target / "templates", args.force, dry))
    log.append(plant_claude_md(target, dry))
    runtime = target / ".factory"
    subs = ("work-items", "interventions", "metrics")
    missing = [s for s in subs if not (runtime / s).is_dir()]
    if not missing:
        log.append(f"skip (exists): {runtime}")
    elif dry:
        log.append(f"would create runtime state dirs: {runtime}")
    else:
        for sub in subs:
            (runtime / sub).mkdir(parents=True, exist_ok=True)
        log.append(f"created runtime state dirs: {runtime}")
    if args.with_cloud:
        wf = target / ".github" / "workflows"
        for w in sorted((FACTORY / "workflows").glob("*.disabled")):
            log.append(copy(w, wf / w.name, args.force, dry))
    if dry:
        log.append(f"would stamp: {target / _MANIFEST_REL} (version + created-paths record)")
    else:
        log.append(write_manifest(target, log, prior))

    print("\n".join(log))
    if dry:
        print(f"\nDry run — nothing was written. Rerun without --dry-run to install into {target}")
        return 0
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
