#!/usr/bin/env python3
"""Drive install/install.py as a real command across the full adoption lifecycle.

Not a substitute for the suite — this exists because the last several installer
bugs were invisible to it. Every scenario runs the actual script against a real
git repo and asserts on the resulting filesystem.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FACTORY = Path(__file__).resolve().parents[1]
INSTALL = FACTORY / "install" / "install.py"
BASE = Path(tempfile.mkdtemp(prefix="factory-install-drive-"))

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(
        f"  {'PASS' if cond else 'FAIL'}  {name}"
        + (f"   [{detail}]" if detail and not cond else "")
    )


def run(target, *flags, toolkit=FACTORY, expect_rc=0):
    script = Path(toolkit) / "install" / "install.py"
    r = subprocess.run(
        [sys.executable, str(script), str(target), *flags], capture_output=True, text=True
    )
    assert r.returncode == expect_rc, f"rc={r.returncode} flags={flags}\n{r.stdout}\n{r.stderr}"
    return r.stdout


def git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=T", *args],
        check=True,
        capture_output=True,
    )


def fresh(name, *, populated=False):
    d = BASE / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    git(d, "init", "-q")
    if populated:
        (d / ".claude").mkdir()
        (d / ".claude" / "settings.json").write_text(
            json.dumps(
                {
                    "model": "opus",
                    "permissions": {"allow": ["Bash(my-own-tool:*)"]},
                    "hooks": {
                        "SessionStart": [
                            {"hooks": [{"type": "command", "command": "python3 ./banner.py"}]}
                        ],
                        "PreToolUse": [
                            {"hooks": [{"type": "command", "command": "python3 ./guard.py"}]}
                        ],
                    },
                },
                indent=2,
            )
        )
        (d / "CLAUDE.md").write_text("# My project\n\nRules that matter to me.\n")
        (d / ".gitignore").write_text("node_modules/\n*.pyc\n")
        (d / ".gitattributes").write_text("*.png binary\n")
        (d / "templates").mkdir()
        (d / "templates" / "MY-TEMPLATE.md").write_text("mine\n")
        (d / "line.yml").write_text("# my own unrelated line.yml\n")
    return d


def snapshot(d):
    return {
        p.relative_to(d).as_posix(): p.read_bytes()
        for p in sorted(d.rglob("*"))
        if p.is_file() and ".git/" not in p.relative_to(d).as_posix()
    }


print("\n=== 1. dry-run writes nothing ===")
d = fresh("dryrun")
before = snapshot(d)
out = run(d, "--dry-run")
check("dry-run leaves the tree byte-identical", snapshot(d) == before)
check("dry-run says nothing was written", "Dry run — nothing was written" in out)

print("\n=== 2. fresh install into an empty repo ===")
d = fresh("empty")
run(d)
for rel in (
    ".claude/skills/factory-triage/SKILL.md",
    ".claude/agents/factory-spec.md",
    ".claude/commands/factory.md",
    ".claude/hooks/factory_board.py",
    "line.yml",
    "policies.yml",
    "classifiers.yml",
    "github-labels.yml",
    "FACTORY-MANUAL.md",
    "templates/REVIEW-PACKET.md",
    "CLAUDE.md",
    ".factory/install-manifest.json",
):
    check(f"shipped {rel}", (d / rel).exists())
check("runtime dirs created", (d / ".factory/work-items").is_dir())
check("no workflows without --with-cloud", not (d / ".github/workflows").exists())
check("no DIRECTION.md without --with-direction", not (d / "DIRECTION.md").exists())

print("\n=== 3. fresh install into a populated repo (the real case) ===")
d = fresh("populated", populated=True)
mine = snapshot(d)
run(d)
s = json.loads((d / ".claude/settings.json").read_text())
check("project's own model key survives", s.get("model") == "opus")
check("project's own permission survives", "Bash(my-own-tool:*)" in s["permissions"]["allow"])
check("factory permissions added", "Bash(factory:*)" in s["permissions"]["allow"])
sess = json.dumps(s["hooks"]["SessionStart"])
check("project's SessionStart hook survives", "./banner.py" in sess)
check("factory SessionStart hook added", "factory_board.py" in sess)
check(
    "project's unrelated PreToolUse hook untouched",
    "./guard.py" in json.dumps(s["hooks"]["PreToolUse"]),
)
check(
    "no retired steering-capture hook installed",
    "record_intervention.py" not in json.dumps(s["hooks"]),
)
claude_md = (d / "CLAUDE.md").read_text()
check("project's CLAUDE.md prose survives", "Rules that matter to me." in claude_md)
check("factory block appended once", claude_md.count("<!-- factory:begin -->") == 1)
gi = (d / ".gitignore").read_text()
check("project's gitignore rules survive", "node_modules/" in gi and "*.pyc" in gi)
check("factory gitignore block added", ".factory/work-items/*/runs/" in gi)
check("project's gitattributes survive", "*.png binary" in (d / ".gitattributes").read_text())
check(
    "project's templates/ file untouched", (d / "templates/MY-TEMPLATE.md").read_text() == "mine\n"
)
check(
    "project's own line.yml NOT overwritten",
    "# my own unrelated line.yml" in (d / "line.yml").read_text(),
)
created = json.loads((d / ".factory/install-manifest.json").read_text())["created"]
check("skipped line.yml not claimed in manifest", "line.yml" not in created)
check("skipped templates/ not claimed in manifest", "templates" not in created)

print("\n=== 4. reinstall is idempotent ===")
run(d)
claude_md = (d / "CLAUDE.md").read_text()
check("CLAUDE.md block still single", claude_md.count("<!-- factory:begin -->") == 1)
check("gitignore block still single", (d / ".gitignore").read_text().count("# factory:begin") == 1)
s = json.loads((d / ".claude/settings.json").read_text())
check(
    "factory hook not stacked",
    json.dumps(s["hooks"]["SessionStart"]).count("factory_board.py") == 1,
)
check(
    "project hook still there after reinstall",
    "./banner.py" in json.dumps(s["hooks"]["SessionStart"]),
)
check(
    "permission allowlist not duplicated", s["permissions"]["allow"].count("Bash(factory:*)") == 1
)

print("\n=== 5. --force does not enrol the project's own paths ===")
d5 = fresh("forced", populated=True)
run(d5, "--force")
created = json.loads((d5 / ".factory/install-manifest.json").read_text())["created"]
check("pre-existing templates/ not manifest-owned", "templates" not in created)
check("pre-existing line.yml not manifest-owned", "line.yml" not in created)
check(
    "--force did overwrite line.yml on disk",
    "# my own unrelated line.yml" not in (d5 / "line.yml").read_text(),
)
check("--force kept the project's template file", (d5 / "templates/MY-TEMPLATE.md").exists())
s = json.loads((d5 / ".claude/settings.json").read_text())
check("--force still merges settings", "./banner.py" in json.dumps(s["hooks"]["SessionStart"]))

print("\n=== 6. uninstall leaves the project exactly as it was ===")
d6 = fresh("roundtrip", populated=True)
before = snapshot(d6)
run(d6)
run(d6, "--uninstall")
after = snapshot(d6)
leftovers = {k: v for k, v in after.items() if k not in before and not k.startswith(".factory/")}
check("no factory files left behind", not leftovers, str(sorted(leftovers))[:200])
for rel in sorted(before):
    if rel == ".factory/install-manifest.json":
        continue
    if rel.endswith(".json"):
        # A JSON merge has to reserialize, so byte-equality is not on offer here.
        # The contract is that no key, hook, or permission of theirs is lost.
        check(
            f"restored semantically: {rel}",
            json.loads(after.get(rel, b"null")) == json.loads(before[rel]),
        )
    else:
        check(f"restored byte-identical: {rel}", after.get(rel) == before[rel])
check(".factory/ deliberately kept", (d6 / ".factory").is_dir())
check(
    ".claude/ removed (held only factory files? no — user had settings)",
    (d6 / ".claude/settings.json").exists(),
)

print("\n=== 7. uninstall from a repo that had nothing of its own ===")
d7 = fresh("clean-exit")
run(d7)
run(d7, "--uninstall")
check("CLAUDE.md removed (was ours alone)", not (d7 / "CLAUDE.md").exists())
check(".gitignore removed (was ours alone)", not (d7 / ".gitignore").exists())
check(".gitattributes removed (was ours alone)", not (d7 / ".gitattributes").exists())
check(".claude/ removed entirely", not (d7 / ".claude").exists())
check(
    "settings.json removed (held only factory settings)",
    not (d7 / ".claude/settings.json").exists(),
)
check(".factory/ kept", (d7 / ".factory").is_dir())

print("\n=== 8. opt-ins: --with-cloud, --with-direction ===")
d8 = fresh("optins")
run(d8, "--with-cloud", "--with-direction")
check("workflows shipped disabled", any((d8 / ".github/workflows").glob("*.disabled")))
check("DIRECTION.md planted", (d8 / "DIRECTION.md").exists())
(d8 / "DIRECTION.md").write_text("MY NORTH STAR\n")
run(d8, "--with-direction", "--force")
check(
    "DIRECTION.md never overwritten, even with --force",
    (d8 / "DIRECTION.md").read_text() == "MY NORTH STAR\n",
)
created = json.loads((d8 / ".factory/install-manifest.json").read_text())["created"]
check("DIRECTION.md untracked in manifest", "DIRECTION.md" not in created)
run(d8, "--uninstall")
check("DIRECTION.md survives uninstall", (d8 / "DIRECTION.md").exists())

print("\n=== 9. enabled workflow is warned about, never deleted ===")
d9 = fresh("enabled-wf")
run(d9, "--with-cloud")
wf = next((d9 / ".github/workflows").glob("*.disabled"))
live = wf.with_suffix("")
wf.rename(live)
out = run(d9, "--uninstall")
check("enabled workflow left in place", live.exists())
check("uninstall warns about it", "enabled workflow left in place" in out)

print("\n=== 10. upgrade: three-way merge against a real toolkit checkout ===")
tk = BASE / "toolkit"
shutil.rmtree(tk, ignore_errors=True)
tk.mkdir(parents=True)
for part in (
    "install",
    ".claude",
    "templates",
    "workflows",
    "line.yml",
    "policies.yml",
    "classifiers.yml",
    "github-labels.yml",
    "FACTORY-MANUAL.md",
    "pyproject.toml",
):
    src = FACTORY / part
    (shutil.copytree if src.is_dir() else shutil.copy2)(src, tk / part)
git(tk, "init", "-q")
git(tk, "add", "-A")
git(tk, "commit", "-qm", "v1")

d10 = fresh("upgrade")
run(d10, toolkit=tk)
# (a) a file the human/retro improved locally, toolkit unchanged  -> kept + radar
(d10 / ".claude/skills/factory-triage/SKILL.md").write_text("MY LOCAL RETRO IMPROVEMENT\n")
# (b) a file only the toolkit changed                              -> upgraded
(tk / ".claude/agents/factory-verify.md").write_text("TOOLKIT MOVED THIS\n")
# (c) a file both sides changed                                    -> conflict, kept mine
(d10 / ".claude/commands/factory.md").write_text("MY VERSION\n")
(tk / ".claude/commands/factory.md").write_text("TOOLKIT VERSION\n")
git(tk, "add", "-A")
git(tk, "commit", "-qm", "v2")
out = run(d10, "--upgrade", toolkit=tk)
check(
    "local improvement kept",
    (d10 / ".claude/skills/factory-triage/SKILL.md").read_text() == "MY LOCAL RETRO IMPROVEMENT\n",
)
check("kept improvement shown on the radar", "📡" in out)
check(
    "toolkit-only change applied",
    (d10 / ".claude/agents/factory-verify.md").read_text() == "TOOLKIT MOVED THIS\n",
)
check("both-changed kept mine", (d10 / ".claude/commands/factory.md").read_text() == "MY VERSION\n")
check("conflict reported", "conflict — kept yours" in out)
check("upgrade prints a summary", "upgrade summary:" in out)

print("\n=== 11. upgrade with no baseline (squashed toolkit history) ===")
d11 = fresh("nobaseline")
run(d11, toolkit=tk)
mf = d11 / ".factory/install-manifest.json"
m = json.loads(mf.read_text())
m["toolkit_commit"] = "unknown"
mf.write_text(json.dumps(m, indent=2))
out = run(d11, "--upgrade", toolkit=tk)
check("no-baseline degrades honestly, not silently", "no usable toolkit commit" in out)

print("\n=== 12. flag conflicts are refused ===")
d12 = fresh("badflags")
run(d12, "--upgrade", "--force", expect_rc=1)
run(d12, "--upgrade", "--uninstall", expect_rc=1)
check("--upgrade + --force refused", True)
check("--upgrade + --uninstall refused", True)

print("\n=== 13. retired paths are pruned on reinstall ===")
d13 = fresh("retired")
run(d13)
(d13 / "templates/PRODUCT.md").write_text("stale from 0.1\n")
(d13 / "labels.yml").write_text("stale from 0.5\n")
(d13 / ".claude/hooks/record_intervention.py").write_text("# stale from 0.6.2\n")
stale_settings = json.loads((d13 / ".claude/settings.json").read_text())
stale_settings["hooks"]["UserPromptSubmit"] = [
    {"hooks": [{"type": "command", "command": "python3 hooks/record_intervention.py"}]}
]
(d13 / ".claude/settings.json").write_text(json.dumps(stale_settings, indent=2))
out = run(d13)
check("retired templates/PRODUCT.md pruned", not (d13 / "templates/PRODUCT.md").exists())
check("retired labels.yml pruned", not (d13 / "labels.yml").exists())
check(
    "retired steering-capture hook pruned",
    not (d13 / ".claude/hooks/record_intervention.py").exists(),
)
s13 = json.loads((d13 / ".claude/settings.json").read_text())
check(
    "its stale settings entry stripped on upgrade",
    "record_intervention.py" not in json.dumps(s13.get("hooks", {})),
)

print("\n=== 14. malformed settings.json hook shapes don't crash the merge ===")
d14 = fresh("weird")
(d14 / ".claude").mkdir()
(d14 / ".claude/settings.json").write_text(
    json.dumps({"hooks": {"SessionStart": {"not": "a list"}, "UserPromptSubmit": "a bare string"}})
)
run(d14)
s = json.loads((d14 / ".claude/settings.json").read_text())
check("non-list hook value replaced, not crashed", isinstance(s["hooks"]["SessionStart"], list))
check("factory hook still installed", "factory_board.py" in json.dumps(s["hooks"]["SessionStart"]))

print("\n=== 15. non-directory target is refused ===")
f = BASE / "afile.txt"
f.write_text("x")
run(f, expect_rc=1)
check("file target refused with rc=1", True)

failed = [n for n, ok, _ in RESULTS if not ok]
print(f"\n{'=' * 60}\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
if failed:
    print("FAILED:")
    for n in failed:
        print(f"  - {n}")
shutil.rmtree(BASE, ignore_errors=True)
sys.exit(1 if failed else 0)
