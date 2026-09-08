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
factory-owned files, never the project's own. --upgrade is the merge-aware
middle path: a three-way diff against the manifest's commit upgrades untouched
files, keeps local (retro-made) improvements, and flags real conflicts.

Usage:
    python3 install/install.py /path/to/your/repo --dry-run      # review the plan
    python3 install/install.py /path/to/your/repo
    python3 install/install.py /path/to/your/repo --with-cloud   # also drop workflows
    python3 install/install.py /path/to/your/repo --with-direction  # plant DIRECTION.md
    python3 install/install.py /path/to/your/repo --upgrade      # three-way merge to latest
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
    "skills/write-product-spec",
    "skills/write-tech-spec",
    "skills/research",
    "agents/factory-triage.md",
    "agents/factory-spec.md",
    "agents/factory-implement.md",
    "agents/factory-code-review.md",
    "agents/factory-verify.md",
    "agents/factory-retro.md",
    "commands/factory.md",
    "commands/factory-status.md",
    "hooks/factory_board.py",
]
ROOT_FILES = [
    "line.yml",
    "policies.yml",
    "classifiers.yml",  # the vocabulary stations classify with (policy input)
    "github-labels.yml",  # the factory:<state> conveyor labels mirrored onto issues
    "FACTORY-MANUAL.md",
]

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


# Two marked blocks in the repo's own git config files, planted and stripped by
# the same mechanism as the CLAUDE.md block: what the engine can rebuild isn't
# committed, and what only the factory holds is committed but kept out of the way
# of the change under review.
_GIT_BLOCK_BEGIN = "# factory:begin"
_GIT_BLOCK_END = "# factory:end"

GITIGNORE_BLOCK = (
    f"{_GIT_BLOCK_BEGIN}\n"
    "# Factory scratch: station briefs and scratchpads, rebuildable with\n"
    "# `factory brief`, so not worth committing.\n"
    ".factory/work-items/*/runs/\n"
    f"{_GIT_BLOCK_END}\n"
)

GITATTRIBUTES_BLOCK = (
    f"{_GIT_BLOCK_BEGIN}\n"
    "# The factory's memory: committed so it travels with the repo, but collapsed\n"
    "# by default in PR diffs so it doesn't bury the change under review.\n"
    ".factory/** linguist-generated=true\n"
    f"{_GIT_BLOCK_END}\n"
)


def plant_git_block(target: Path, filename: str, block: str, dry: bool = False) -> str:
    """Plant (or refresh) a marked block in one of the repo's git config files.

    Same contract as the CLAUDE.md block: only the text between the sentinels is
    ever written, so the project's own rules outside them survive byte-for-byte
    and an upgrade refreshes ours without a --force."""
    path = target / filename
    if not path.exists():
        if dry:
            return f"would create: {path}"
        path.write_text(block)
        return f"created: {path}"
    text = path.read_text()
    if _GIT_BLOCK_BEGIN in text and _GIT_BLOCK_END in text:
        if dry:
            return f"would refresh factory block: {path}"
        head, rest = text.split(_GIT_BLOCK_BEGIN, 1)
        tail = rest.split(_GIT_BLOCK_END, 1)[1]
        path.write_text(head + block.rstrip("\n") + tail)
        return f"refreshed factory block: {path}"
    if dry:
        return f"would append factory block: {path}"
    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    path.write_text(text + sep + block)
    return f"appended factory block: {path}"


def strip_git_block(target: Path, filename: str, dry: bool) -> str | None:
    """Reverse plant_git_block: remove the marked block, preserving everything
    else; if the file held nothing but our block, remove the file."""
    path = target / filename
    if not path.exists():
        return None
    text = path.read_text()
    if _GIT_BLOCK_BEGIN not in text or _GIT_BLOCK_END not in text:
        return None
    if dry:
        return f"would strip factory block from: {path}"
    head = text.split(_GIT_BLOCK_BEGIN, 1)[0]
    tail = text.split(_GIT_BLOCK_END, 1)[1]
    remains = (head.rstrip("\n") + "\n\n" + tail.lstrip("\n")).strip("\n")
    if remains:
        path.write_text(remains + "\n")
        return f"stripped factory block from: {path}"
    path.unlink()
    return f"removed: {path} (contained only the factory block)"


def plant_direction(target: Path, dry: bool) -> str:
    """Plant the DIRECTION.md starter at the target root (--with-direction).

    Unlike factory-owned files, it becomes the *project's* document the moment it
    lands: the human fills in the north star and non-negotiables, the spec
    station anchors to it. So it's deliberately untracked — not recorded in the
    manifest, never overwritten (--force included; this skip is unconditional),
    never uninstalled."""
    dst = target / "DIRECTION.md"
    if dst.exists():
        return f"skip (exists — it's yours): {dst}"
    if dry:
        return f"would plant: {dst} (yours after that; untracked, never overwritten)"
    shutil.copy2(FACTORY / "templates" / "DIRECTION.md", dst)
    return f"planted: {dst} (yours now — fill in the north star; untracked, never overwritten)"


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
_SHARED_FILES = {"CLAUDE.md", ".claude/settings.json", ".gitignore", ".gitattributes"}

# Paths the toolkit USED to ship and no longer does, but which the manifest-diff
# prune can't catch because they sit inside a still-shipped directory (so the
# manifest recorded only the parent). Reinstall removes these explicitly so an
# upgrade doesn't leave dead files behind. Append here whenever a shipped file is
# retired from within a kept directory; drop an entry once no live install could
# still carry it.
_RETIRED_PATHS = [
    "templates/PRODUCT.md",  # retired 0.2.0: spec shape moved into the write-product-spec skill
    "templates/TECH.md",  # retired 0.2.0: spec shape moved into the write-tech-spec skill
    "labels.yml",  # retired 0.6.0: renamed github-labels.yml, to free the word for classifiers.yml
    # retired 0.6.4: chat-steering capture superseded by PR review threads as the signal
    ".claude/hooks/record_intervention.py",
]


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
    # Only prune on a genuine upgrade (a prior manifest exists). On a fresh
    # install there is nothing of ours to retire, and we must not touch a
    # same-named file the target already had.
    if not prior:
        return []

    def _remove(rel: str, log: list[str]) -> None:
        p = target / rel
        if not p.exists():
            return
        if dry:
            log.append(f"would remove (retired): {p}")
        else:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
            log.append(f"removed (retired): {p}")

    log: list[str] = []
    # 1. Explicitly-retired sub-paths: files inside a still-shipped directory, so
    #    the manifest never tracked them individually (see _RETIRED_PATHS).
    for rel in _RETIRED_PATHS:
        _remove(rel, log)
    # 2. Manifest-tracked paths the current toolkit no longer ships (e.g. a whole
    #    skill folded into another). Pruned entries also leave the manifest so
    #    they don't resurrect.
    shipped = set(_shipped_paths())
    kept = []
    for rel in prior.get("created", []):
        if rel in shipped or rel in _SHARED_FILES:
            kept.append(rel)
            continue
        if rel in _RETIRED_PATHS:
            continue  # step 1 already took it; a dry run would otherwise log it twice
        _remove(rel, log)
    if not dry:
        prior["created"] = kept
    return log


# --- upgrade: the three-way merge path ----------------------------------------
# `--upgrade` compares, per file: what's installed (I), what the toolkit shipped
# at the manifest's commit (O — the baseline `git show` recovers), and what the
# toolkit ships now (N). Untouched files upgrade cleanly; files the retro (or
# the human) improved locally are kept — reported as the upstreaming radar when
# the toolkit didn't move, as conflicts when both sides did. Nothing the user
# changed is ever clobbered; `--force` remains the explicit clobber.


def _git_show(commit: str | None, rel: str) -> bytes | None:
    """The toolkit file's content at the manifest's commit, or None when there is
    no usable baseline (unknown commit, or the file didn't exist back then)."""
    if not commit or commit == "unknown":
        return None
    try:
        r = subprocess.run(
            ["git", "-C", str(FACTORY), "show", f"{commit}:{rel}"],
            capture_output=True,
            timeout=10,
        )
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _upgrade_pairs(target: Path) -> list[tuple[Path, str, str, bool]]:
    """Every file the current toolkit ships, at file granularity:
    (target_path, toolkit_relpath, manifest_granularity_rel, optional).
    Workflows are optional — they only upgrade if the target opted in."""
    pairs: list[tuple[Path, str, str, bool]] = []

    def add_tree(toolkit_rel: str, manifest_rel: str) -> None:
        src = FACTORY / toolkit_rel
        if src.is_dir():
            for f in sorted(src.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(src)
                    pairs.append(
                        (target / toolkit_rel / rel, f"{toolkit_rel}/{rel}", manifest_rel, False)
                    )
        elif src.is_file():
            pairs.append((target / toolkit_rel, toolkit_rel, manifest_rel, False))

    for i in CLAUDE_ITEMS:
        add_tree(f".claude/{i}", f".claude/{i}")
    for f in ROOT_FILES:
        add_tree(f, f)
    add_tree("templates", "templates")
    for w in sorted((FACTORY / "workflows").glob("*.disabled")):
        pairs.append(
            (
                target / ".github" / "workflows" / w.name,
                f"workflows/{w.name}",
                f".github/workflows/{w.name}",
                True,
            )
        )
    return pairs


def upgrade_files(
    target: Path, prior: dict | None, dry: bool, with_cloud: bool
) -> tuple[list[str], list[str], list[tuple[Path, str, str]], list[tuple[Path, str]]]:
    """Classify and act on every shipped file. Returns (log, created_manifest_rels,
    conflicts, radar) — conflicts/radar as (target_path, toolkit_rel[, reason])."""
    commit = (prior or {}).get("toolkit_commit")
    baseline_ok = bool(commit) and commit != "unknown"
    log: list[str] = []
    created: list[str] = []
    conflicts: list[tuple[Path, str, str]] = []
    radar: list[tuple[Path, str]] = []
    would = "would " if dry else ""
    counts = {"upgraded": 0, "new": 0, "current": 0, "kept": 0, "conflict": 0}
    if not baseline_ok:
        log.append(
            "⚠ no usable toolkit commit in the manifest — two-way compare only "
            "(identical files count as current; any difference is kept as a conflict)"
        )
    for dst, toolkit_rel, manifest_rel, optional in _upgrade_pairs(target):
        new = (FACTORY / toolkit_rel).read_bytes()
        if not dst.exists():
            if optional and not with_cloud:
                continue  # workflows stay opt-in
            counts["new"] += 1
            log.append(f"{would}install (new): {dst}")
            created.append(manifest_rel)
            if not dry:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(new)
            continue
        installed = dst.read_bytes()
        if installed == new:
            counts["current"] += 1
            continue
        original = _git_show(commit, toolkit_rel)
        if original is not None and installed == original:
            counts["upgraded"] += 1
            log.append(f"{would}upgrade: {dst}")
            if not dry:
                dst.write_bytes(new)
        elif original is not None and new == original:
            counts["kept"] += 1
            radar.append((dst, toolkit_rel))
            log.append(f"kept (your changes; toolkit unchanged): {dst}")
        else:
            counts["conflict"] += 1
            why = "both changed" if original is not None else "no baseline for this file"
            conflicts.append((dst, toolkit_rel, why))
            log.append(f"conflict — kept yours: {dst} ({why})")
    log.append(
        f"upgrade summary: {counts['upgraded']} upgraded, {counts['new']} new, "
        f"{counts['current']} already current, {counts['kept']} kept local, "
        f"{counts['conflict']} conflict(s)"
    )
    return log, created, conflicts, radar


def print_upgrade_guidance(
    commit: str | None, conflicts: list[tuple[Path, str, str]], radar: list[tuple[Path, str]]
) -> None:
    """The divergence report: exact commands to see each side, so the human can
    merge by hand — and the radar of local improvements the toolkit may want."""
    show = commit if commit and commit != "unknown" else "<install-commit>"
    if conflicts:
        print("\n⚠ Conflicts — you and the toolkit both changed these; kept YOURS untouched:")
        for dst, rel, why in conflicts:
            print(f"  {dst}  ({why})")
            print(f"    your changes:    git -C {FACTORY} show {show}:{rel} | diff - {dst}")
            print(f"    toolkit changes: git -C {FACTORY} diff {show} HEAD -- {rel}")
        print("  Merge by hand, or adopt the toolkit side wholesale later with --force.")
    if radar:
        print("\n📡 Kept your local improvements (toolkit unchanged) — the upstreaming radar:")
        for dst, rel in radar:
            print(f"  {dst}    (see: git -C {FACTORY} show {show}:{rel} | diff - {dst})")
        print("  If one of these generalizes, consider contributing it back to the toolkit.")


def read_manifest(target: Path) -> dict | None:
    path = target / _MANIFEST_REL
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def write_manifest(
    target: Path, log: list[str], prior: dict | None, extra_created: list[str] | None = None
) -> str:
    created_now = list(extra_created or [])
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
    that's the repo's own history (work items, metrics)."""
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
    log.append(strip_git_block(target, ".gitignore", dry))
    log.append(strip_git_block(target, ".gitattributes", dry))
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
  Left in place: .factory/ — your work items and metrics (the
  factory's memory, including the install manifest). Delete it manually for a
  clean slate. Review the diff and commit when satisfied.
"""
    )
    return 0


def copy(src: Path, dst: Path, force: bool, dry: bool = False) -> str:
    """Copy one shipped path into the target.

    The return verb is load-bearing: only `copied:` feeds the manifest's `created`
    list, so `--force` overwriting a path that was already there reports
    `overwrote:` instead. Otherwise force-installing into a repo that happens to
    own a same-named path (a `templates/` of its own) would enrol it as
    factory-created, and uninstall would take the user's files with it."""
    existed = dst.exists()
    if existed and not force:
        return f"skip (exists): {dst}"
    if dry:
        return f"would {'overwrite' if existed else 'copy'}: {dst}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)
    return f"overwrote: {dst}" if existed else f"copied: {dst}"


# The factory's own hook entries are recognised by the scripts they run — the one
# stable marker in a Claude Code hook entry, which carries no name or id of its own.
# record_intervention.py no longer ships (retired with its hook), but stays a marker
# so upgrade/uninstall still strip its stale settings entry from older installs.
_HOOK_MARKERS = ("factory_board.py", "record_intervention.py")


def _is_factory_hook(entry: object) -> bool:
    return any(m in json.dumps(entry) for m in _HOOK_MARKERS)


def merge_settings(target: Path, dry: bool = False) -> str:
    """Merge the factory's hooks + permission allowlist into the repo's existing
    settings.json rather than clobbering it. settings.json is shared real estate
    (the project's own hooks/permissions live there too), so even --force never
    replaces it wholesale — the merge already refreshes the factory's entries.

    Hooks merge *within* each event, not by replacing it: a repo with its own
    `SessionStart` hook keeps it and gains ours. Replacing the event wholesale
    silently deleted the project's hook on a plain install."""
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
    hooks = existing.setdefault("hooks", {})
    # Sweep our previous entries from EVERY event before re-adding — not just the
    # events we currently ship. A reinstall refreshes rather than stacking, and an
    # event whose hook we retired loses its stale entry instead of carrying it forever.
    for event in list(hooks):
        current = hooks[event]
        if not isinstance(current, list):
            continue
        kept = [e for e in current if not _is_factory_hook(e)]
        if len(kept) == len(current):
            continue  # nothing of ours under this event
        if kept or event in (new.get("hooks") or {}):
            hooks[event] = kept
        else:
            del hooks[event]  # only our entries lived here and we ship none now
    for event, incoming in (new.get("hooks") or {}).items():
        current = hooks.get(event)
        current = current if isinstance(current, list) else []
        incoming = incoming if isinstance(incoming, list) else [incoming]
        hooks[event] = current + incoming
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
    """Reverse merge_settings: remove the factory's own hook entries, permission
    entries, and comment from the repo's settings.json, leaving everything else
    untouched. If nothing but empty husks remain (we created the file and the
    user never added to it), remove the file itself.

    Hooks are removed entry by entry, matching how they were merged — an event
    the project also hooks keeps its own entries and simply loses ours."""
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
    # Every event, not just the ones we currently ship — an entry from a hook we
    # retired since install still carries our marker and must leave with us.
    for event in list(hooks if isinstance(hooks, dict) else {}):
        current = hooks.get(event)
        if not isinstance(current, list):
            continue
        kept = [e for e in current if not _is_factory_hook(e)]
        if len(kept) == len(current):
            continue
        changed = True
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if cur.get("$comment") == fact.get("$comment"):
        del cur["$comment"]
        changed = True
    if not changed:
        return None
    # Drop containers we emptied. A repo that keeps its own settings shouldn't be
    # left holding `"hooks": {}` as the visible residue of having tried the factory.
    if isinstance(hooks, dict) and not hooks:
        cur.pop("hooks", None)
    perms = cur.get("permissions")
    if isinstance(perms, dict):
        if not perms.get("allow"):
            perms.pop("allow", None)
        if not perms:
            cur.pop("permissions", None)
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
        "--with-direction",
        action="store_true",
        help="also plant a DIRECTION.md starter at the repo root (the project north star the "
        "spec station anchors to); yours from then on — untracked, never overwritten or removed",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing factory-owned files (never the project's own; "
        "settings.json is always merged, CLAUDE.md only its marked block)",
    )
    ap.add_argument(
        "--upgrade",
        action="store_true",
        help="three-way upgrade: apply toolkit changes to files you haven't touched since "
        "install (baseline = the manifest's commit), keep and report locally-modified files "
        "(the retro's improvements survive), and flag true conflicts for a hand merge — "
        "never clobbers; --force stays the explicit clobber",
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
    if args.upgrade and (args.force or args.uninstall):
        print("✗ --upgrade cannot combine with --force or --uninstall: upgrade merges, "
              "--force clobbers, --uninstall removes — pick one")
        return 1
    prior = read_manifest(target)
    if args.uninstall:
        return uninstall(target, prior, dry)
    if prior:
        print(
            f"→ previously installed: v{prior.get('toolkit_version', '?')} "
            f"({prior.get('toolkit_commit', '?')}) at {prior.get('installed_at', '?')}; "
            f"{'upgrading to' if args.upgrade else 'installing'} "
            f"v{_toolkit_version()} ({_toolkit_commit()})"
        )

    log = prune_retired(target, prior, dry)
    conflicts: list[tuple[Path, str, str]] = []
    radar: list[tuple[Path, str]] = []
    extra_created: list[str] = []
    if args.upgrade:
        up_log, extra_created, conflicts, radar = upgrade_files(
            target, prior, dry, args.with_cloud
        )
        log += up_log
    else:
        log += [
            copy(FACTORY / ".claude" / i, target / ".claude" / i, args.force, dry)
            for i in CLAUDE_ITEMS
        ]
        log += [copy(FACTORY / f, target / f, args.force, dry) for f in ROOT_FILES]
        log.append(copy(FACTORY / "templates", target / "templates", args.force, dry))
        if args.with_cloud:
            wf = target / ".github" / "workflows"
            for w in sorted((FACTORY / "workflows").glob("*.disabled")):
                log.append(copy(w, wf / w.name, args.force, dry))
    log.append(merge_settings(target, dry))
    if args.with_direction:
        log.append(plant_direction(target, dry))
    log.append(plant_claude_md(target, dry))
    log.append(plant_git_block(target, ".gitignore", GITIGNORE_BLOCK, dry))
    log.append(plant_git_block(target, ".gitattributes", GITATTRIBUTES_BLOCK, dry))
    runtime = target / ".factory"
    subs = ("work-items", "metrics")
    missing = [s for s in subs if not (runtime / s).is_dir()]
    if not missing:
        log.append(f"skip (exists): {runtime}")
    elif dry:
        log.append(f"would create runtime state dirs: {runtime}")
    else:
        for sub in subs:
            (runtime / sub).mkdir(parents=True, exist_ok=True)
        log.append(f"created runtime state dirs: {runtime}")
    if dry:
        log.append(f"would stamp: {target / _MANIFEST_REL} (version + created-paths record)")
    else:
        log.append(write_manifest(target, log, prior, extra_created))

    print("\n".join(log))
    if args.upgrade:
        print_upgrade_guidance((prior or {}).get("toolkit_commit"), conflicts, radar)
    if dry:
        print(f"\nDry run — nothing was written. Rerun without --dry-run to install into {target}")
        return 0
    if args.upgrade:
        print(
            f"\n✓ Factory upgraded in {target}\n"
            "  Review the git diff (upgrades + any conflicts above), merge what needs merging,\n"
            "  and commit when satisfied."
        )
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
