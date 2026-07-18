"""install.py's CLAUDE.md planting, manifest, upgrade, and uninstall — exercised
as a real subprocess against temp target repos (the installer is a standalone
script, not part of the package)."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INSTALL = REPO / "install" / "install.py"

# Everything a toolkit checkout needs for install/upgrade to run.
_TOOLKIT_PARTS = (
    "install",
    ".claude",
    "templates",
    "workflows",
    "line.yml",
    "policies.yml",
    "labels.yml",
    "FACTORY-MANUAL.md",
    "pyproject.toml",
)


def _install(target: Path, *flags: str) -> str:
    r = subprocess.run(
        [sys.executable, str(INSTALL), str(target), *flags],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=T", *args],
        check=True,
        capture_output=True,
        timeout=30,
    )


@pytest.fixture
def toolkit(tmp_path_factory) -> Path:
    """A throwaway toolkit checkout with its own git history, so upgrade tests
    can commit toolkit changes without touching the real repo."""
    clone = tmp_path_factory.mktemp("toolkit")
    for rel in _TOOLKIT_PARTS:
        src = REPO / rel
        dst = clone / rel
        shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
    _git(clone, "init", "-q", "-b", "main")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-q", "-m", "toolkit v1")
    return clone


def _install_from(toolkit: Path, target: Path, *flags: str, expect_rc: int = 0) -> str:
    r = subprocess.run(
        [sys.executable, str(toolkit / "install" / "install.py"), str(target), *flags],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == expect_rc, r.stderr + r.stdout
    return r.stdout


def _bump_toolkit(toolkit: Path, rel: str, text: str) -> None:
    """Commit a toolkit-side change, moving HEAD past the install baseline."""
    (toolkit / rel).write_text(text)
    _git(toolkit, "add", "-A")
    _git(toolkit, "commit", "-q", "-m", f"toolkit change: {rel}")


def test_fresh_repo_gets_claude_md_and_manual(tmp_path: Path):
    """A repo with no CLAUDE.md gets one holding the factory pointer block, and
    the human's FACTORY-MANUAL.md lands at the root — a cold first session (hooks
    not yet trusted, no /factory typed) still discovers the factory this way."""
    _install(tmp_path)
    text = (tmp_path / "CLAUDE.md").read_text()
    assert "## Software factory" in text
    assert ".claude/commands/factory.md" in text
    assert (tmp_path / "FACTORY-MANUAL.md").exists()


def test_existing_claude_md_content_is_preserved(tmp_path: Path):
    """CLAUDE.md is the target project's file — the installer may only append its
    marked block, never touch what the project already wrote."""
    own = "# My project\n\nUse tabs, worship the linter.\n"
    (tmp_path / "CLAUDE.md").write_text(own)
    _install(tmp_path)
    text = (tmp_path / "CLAUDE.md").read_text()
    assert text.startswith(own)
    assert "## Software factory" in text


def test_dry_run_plans_everything_and_writes_nothing(tmp_path: Path):
    """--dry-run exists so an agent (the install-factory skill) can show the human
    the full operation list before touching their repo — it must report the plan
    and leave the target byte-for-byte untouched."""
    out = _install(tmp_path, "--dry-run")
    assert "would copy" in out and "would create" in out
    assert "nothing was written" in out
    assert list(tmp_path.iterdir()) == []


def test_reinstall_refreshes_the_block_without_duplication(tmp_path: Path):
    """Reinstalling must replace a stale block in place (upgrades propagate) and
    never stack a second copy — content outside the markers stays untouched."""
    (tmp_path / "CLAUDE.md").write_text(
        "# My project\n\n<!-- factory:begin -->\nSTALE OLD BLOCK\n<!-- factory:end -->\n\ntrailer\n"
    )
    _install(tmp_path)
    _install(tmp_path)
    text = (tmp_path / "CLAUDE.md").read_text()
    assert text.count("<!-- factory:begin -->") == 1
    assert "STALE OLD BLOCK" not in text
    assert "## Software factory" in text
    assert text.startswith("# My project") and text.rstrip().endswith("trailer")


def test_manifest_stamps_version_and_created_paths(tmp_path: Path):
    """Every install stamps .factory/install-manifest.json with the toolkit
    version/commit and the paths it actually created — the record that makes
    uninstall safe and reinstalls version-aware."""
    _install(tmp_path)
    manifest = json.loads((tmp_path / ".factory" / "install-manifest.json").read_text())
    assert manifest["toolkit_version"] not in ("", "unknown")
    assert "CLAUDE.md" in manifest["created"]
    assert "line.yml" in manifest["created"]


def test_runtime_dirs_report_skip_when_already_present(tmp_path: Path):
    """Regression: dry-run said 'would create .factory' even when the runtime dirs
    already existed — an already-installed repo must see a skip, not a phantom op."""
    _install(tmp_path)
    out = _install(tmp_path, "--dry-run")
    assert "would create runtime state dirs" not in out
    assert f"skip (exists): {tmp_path / '.factory'}" in out


def test_force_merges_settings_instead_of_clobbering(tmp_path: Path):
    """Regression: --force used to replace settings.json wholesale, erasing the
    project's own hooks/permissions. settings.json is shared real estate — even
    --force must merge, and the project's entries must survive."""
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(my-own-tool:*)"]}})
    )
    _install(tmp_path, "--force")
    settings = json.loads((claude / "settings.json").read_text())
    assert "Bash(my-own-tool:*)" in settings["permissions"]["allow"]
    assert settings.get("hooks")  # factory hooks arrived via merge


def test_uninstall_removes_factory_but_preserves_user_content(tmp_path: Path):
    """Uninstall is the confidence valve for adopters: it must remove exactly what
    the installer created (per the manifest), strip only the CLAUDE.md block,
    unmerge only the factory's settings entries, and leave .factory/ (the repo's
    own history) plus everything the user ever wrote."""
    (tmp_path / "CLAUDE.md").write_text("# My project\n\nMy own rules.\n")
    my_skill = tmp_path / ".claude" / "skills" / "my-skill"
    my_skill.mkdir(parents=True)
    (my_skill / "SKILL.md").write_text("mine")
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(my-own-tool:*)"]}})
    )
    _install(tmp_path)
    _install(tmp_path, "--uninstall")
    assert not (tmp_path / ".claude" / "skills" / "factory-triage").exists()
    assert not (tmp_path / "line.yml").exists()
    assert not (tmp_path / "FACTORY-MANUAL.md").exists()
    text = (tmp_path / "CLAUDE.md").read_text()
    assert "My own rules." in text and "factory:begin" not in text
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "Bash(my-own-tool:*)" in settings["permissions"]["allow"]
    assert not settings.get("hooks")
    assert (my_skill / "SKILL.md").exists()
    assert (tmp_path / ".factory").is_dir()  # the repo's history stays


def test_uninstall_dry_run_removes_nothing(tmp_path: Path):
    """--uninstall --dry-run must only report the removal plan."""
    _install(tmp_path)
    out = _install(tmp_path, "--uninstall", "--dry-run")
    assert "would remove" in out and "nothing was removed" in out
    assert (tmp_path / "line.yml").exists()
    assert (tmp_path / "CLAUDE.md").exists()


def test_with_cloud_workflows_round_trip(tmp_path: Path):
    """--with-cloud drops the disabled workflows, the manifest records them, and
    uninstall takes them away again."""
    _install(tmp_path, "--with-cloud")
    wf = list((tmp_path / ".github" / "workflows").glob("*.disabled"))
    assert wf, "expected disabled workflows to be installed"
    _install(tmp_path, "--uninstall")
    assert not list((tmp_path / ".github" / "workflows").glob("*.disabled"))


def test_uninstall_never_deletes_an_enabled_workflow(tmp_path: Path):
    """Enabling a workflow (renaming away .disabled, adding secrets) is a
    deliberate user act — uninstall must leave it running and warn, not silently
    remove live CI."""
    _install(tmp_path, "--with-cloud")
    wf_dir = tmp_path / ".github" / "workflows"
    disabled = sorted(wf_dir.glob("*.disabled"))[0]
    enabled = wf_dir / disabled.name.removesuffix(".disabled")
    disabled.rename(enabled)
    out = _install(tmp_path, "--uninstall")
    assert enabled.exists()
    assert "enabled workflow left in place" in out


def test_uninstall_without_manifest_falls_back_to_standard_set(tmp_path: Path):
    """Pre-manifest installs (before version stamping existed) must still be
    uninstallable: fall back to the standard factory file set, with a warning."""
    _install(tmp_path)
    (tmp_path / ".factory" / "install-manifest.json").unlink()
    out = _install(tmp_path, "--uninstall")
    assert "no install manifest" in out
    assert not (tmp_path / "line.yml").exists()
    assert not (tmp_path / ".claude" / "skills" / "factory-triage").exists()


def test_uninstall_keeps_user_edits_in_a_claude_md_we_created(tmp_path: Path):
    """Even when the installer created CLAUDE.md, the user may have added their
    own instructions since — uninstall strips only the factory block and must
    never blind-delete the file over their content."""
    _install(tmp_path)  # fresh repo: CLAUDE.md is factory-created
    path = tmp_path / "CLAUDE.md"
    path.write_text(path.read_text() + "\n## My own section\nKeep me.\n")
    _install(tmp_path, "--uninstall")
    text = path.read_text()
    assert "Keep me." in text
    assert "factory:begin" not in text


def test_uninstall_removes_untouched_created_files_entirely(tmp_path: Path):
    """The clean opt-out: when the installer created CLAUDE.md and settings.json
    and the user never touched them, uninstall leaves no husks behind — no
    orphan files and no empty .claude/.github parent dirs. Only .factory/
    (the repo's own history) remains, by design."""
    _install(tmp_path, "--with-cloud")  # fresh repo: everything factory-created
    _install(tmp_path, "--uninstall")
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".github").exists()
    assert [p.name for p in tmp_path.iterdir()] == [".factory"]


def test_with_direction_plants_a_user_owned_starter(tmp_path: Path):
    """--with-direction plants DIRECTION.md at the root but the file is the
    project's from birth: absent from the manifest, so uninstall must leave it
    standing while removing the factory."""
    _install(tmp_path, "--with-direction")
    direction = tmp_path / "DIRECTION.md"
    assert "## North star" in direction.read_text()
    manifest = json.loads((tmp_path / ".factory" / "install-manifest.json").read_text())
    assert "DIRECTION.md" not in manifest["created"]
    _install(tmp_path, "--uninstall")
    assert direction.exists()
    assert not (tmp_path / "line.yml").exists()


def test_with_direction_never_overwrites_the_users_file(tmp_path: Path):
    """Once the human fills DIRECTION.md in, it's their vision doc — a reinstall,
    even with --force, must not touch a byte of it."""
    own = "# Direction\n\nShip the exporter above all else.\n"
    (tmp_path / "DIRECTION.md").write_text(own)
    _install(tmp_path, "--with-direction", "--force")
    assert (tmp_path / "DIRECTION.md").read_text() == own


def test_with_direction_dry_run_plants_nothing(tmp_path: Path):
    """The plan must speak about the plant without performing it."""
    out = _install(tmp_path, "--with-direction", "--dry-run")
    assert "would plant" in out
    assert not (tmp_path / "DIRECTION.md").exists()


def test_reinstall_prunes_retired_paths(tmp_path: Path):
    """Regression: a reinstall over an older install left retired paths (items the
    toolkit no longer ships, e.g. a skill folded into another) live in the target
    and stuck in the manifest — an upgrade must remove them from both."""
    _install(tmp_path)
    manifest_path = tmp_path / ".factory" / "install-manifest.json"
    retired = tmp_path / ".claude" / "skills" / "retired-skill"
    retired.mkdir(parents=True)
    (retired / "SKILL.md").write_text("obsolete\n")
    manifest = json.loads(manifest_path.read_text())
    manifest["created"].append(".claude/skills/retired-skill")
    manifest_path.write_text(json.dumps(manifest))
    out = _install(tmp_path, "--force")
    assert f"removed (retired): {retired}" in out
    assert not retired.exists()
    manifest = json.loads(manifest_path.read_text())
    assert ".claude/skills/retired-skill" not in manifest["created"]
    assert ".claude/skills/council" in manifest["created"]  # current items survive


def test_reinstall_prune_dry_run_removes_nothing(tmp_path: Path):
    """The prune must obey --dry-run like every other operation: report the
    retired path it would remove, but leave disk and manifest untouched."""
    _install(tmp_path)
    manifest_path = tmp_path / ".factory" / "install-manifest.json"
    retired = tmp_path / ".claude" / "skills" / "retired-skill"
    retired.mkdir(parents=True)
    (retired / "SKILL.md").write_text("obsolete\n")
    manifest = json.loads(manifest_path.read_text())
    manifest["created"].append(".claude/skills/retired-skill")
    manifest_path.write_text(json.dumps(manifest))
    out = _install(tmp_path, "--force", "--dry-run")
    assert f"would remove (retired): {retired}" in out
    assert retired.exists()
    assert ".claude/skills/retired-skill" in json.loads(manifest_path.read_text())["created"]


def test_reinstall_prunes_retired_subpath_inside_kept_dir(tmp_path: Path):
    """Regression: files retired from *within* a still-shipped directory (the spec
    templates that moved into the spec-writing skills) aren't in the manifest by
    name — the parent dir is — so only the explicit _RETIRED_PATHS list catches
    them. An upgrade must delete the orphan; a fresh install must never touch a
    same-named file the repo already had."""
    _install(tmp_path)  # real install: templates/ ships, but not PRODUCT.md/TECH.md
    orphan = tmp_path / "templates" / "PRODUCT.md"
    orphan.write_text("stale spec template from an older toolkit\n")  # simulate prior version
    out = _install(tmp_path, "--force")
    assert f"removed (retired): {orphan}" in out
    assert not orphan.exists()
    assert (tmp_path / "templates" / "REVIEW-PACKET.md").exists()  # kept dir survives


# --- the three-way upgrade path ----------------------------------------------


def test_upgrade_applies_toolkit_changes_to_untouched_files(toolkit: Path, tmp_path: Path):
    """The clean-upgrade leg: a file the adopter never touched (installed ==
    baseline) must take the toolkit's new version."""
    _install_from(toolkit, tmp_path)
    new_manual = "# FACTORY MANUAL v2\n\nEntirely reworded.\n"
    _bump_toolkit(toolkit, "FACTORY-MANUAL.md", new_manual)
    out = _install_from(toolkit, tmp_path, "--upgrade")
    assert f"upgrade: {tmp_path / 'FACTORY-MANUAL.md'}" in out
    assert (tmp_path / "FACTORY-MANUAL.md").read_text() == new_manual


def test_upgrade_keeps_local_improvements_and_reports_the_radar(toolkit: Path, tmp_path: Path):
    """The retro's survival leg: a locally-improved file the toolkit didn't touch
    must be kept byte-for-byte and reported as upstreaming-radar material — the
    exact case --force used to clobber."""
    _install_from(toolkit, tmp_path)
    local = "# Triage skill\n\nLocally sharpened by a retro.\n"
    skill = tmp_path / ".claude" / "skills" / "factory-triage" / "SKILL.md"
    skill.write_text(local)
    out = _install_from(toolkit, tmp_path, "--upgrade")
    assert skill.read_text() == local
    assert "kept (your changes; toolkit unchanged)" in out
    assert "upstreaming radar" in out


def test_upgrade_flags_conflicts_and_keeps_yours(toolkit: Path, tmp_path: Path):
    """Both sides changed: the upgrade must keep the adopter's version untouched
    and print the two diff commands a human merge needs — never silently pick a
    winner."""
    _install_from(toolkit, tmp_path)
    local = "# labels — locally customized\nversion: 1\nlabels: []\n"
    (tmp_path / "labels.yml").write_text(local)
    _bump_toolkit(toolkit, "labels.yml", "# labels — toolkit reworked\nversion: 2\nlabels: []\n")
    out = _install_from(toolkit, tmp_path, "--upgrade")
    assert (tmp_path / "labels.yml").read_text() == local
    assert "conflict — kept yours" in out and "both changed" in out
    assert "your changes:" in out and "toolkit changes:" in out


def test_upgrade_installs_files_the_toolkit_added(toolkit: Path, tmp_path: Path):
    """A file the new toolkit ships that the install predates must arrive on
    upgrade — an upgrade is also a gap-fill."""
    _install_from(toolkit, tmp_path)
    _bump_toolkit(toolkit, "templates/NEW-SHAPE.md", "# A template added in v2\n")
    out = _install_from(toolkit, tmp_path, "--upgrade")
    assert "install (new)" in out
    assert (tmp_path / "templates" / "NEW-SHAPE.md").read_text() == "# A template added in v2\n"


def test_upgrade_without_a_baseline_falls_back_to_conservative_two_way(
    toolkit: Path, tmp_path: Path
):
    """No usable manifest commit means no way to tell who changed a file — every
    difference must be kept as a conflict (warned), never applied over the
    adopter's copy."""
    _install_from(toolkit, tmp_path)
    manifest_path = tmp_path / ".factory" / "install-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["toolkit_commit"] = "unknown"
    manifest_path.write_text(json.dumps(manifest))
    _bump_toolkit(toolkit, "FACTORY-MANUAL.md", "# reworded\n")
    before = (tmp_path / "FACTORY-MANUAL.md").read_text()
    out = _install_from(toolkit, tmp_path, "--upgrade")
    assert "no usable toolkit commit" in out
    assert "conflict — kept yours" in out and "no baseline" in out
    assert (tmp_path / "FACTORY-MANUAL.md").read_text() == before


def test_upgrade_dry_run_changes_nothing(toolkit: Path, tmp_path: Path):
    """--dry-run must narrate the would-upgrades and leave every byte in place."""
    _install_from(toolkit, tmp_path)
    _bump_toolkit(toolkit, "FACTORY-MANUAL.md", "# reworded\n")
    before = (tmp_path / "FACTORY-MANUAL.md").read_text()
    out = _install_from(toolkit, tmp_path, "--upgrade", "--dry-run")
    assert "would upgrade:" in out
    assert (tmp_path / "FACTORY-MANUAL.md").read_text() == before


def test_upgrade_restamps_the_manifest(toolkit: Path, tmp_path: Path):
    """After an upgrade the manifest must carry the new toolkit commit — the next
    upgrade's baseline; a stale stamp would mis-classify every later diff."""
    _install_from(toolkit, tmp_path)
    _bump_toolkit(toolkit, "FACTORY-MANUAL.md", "# reworded\n")
    _install_from(toolkit, tmp_path, "--upgrade")
    head = subprocess.run(
        ["git", "-C", str(toolkit), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    manifest = json.loads((tmp_path / ".factory" / "install-manifest.json").read_text())
    assert manifest["toolkit_commit"] == head


def test_upgrade_refuses_the_force_combination(toolkit: Path, tmp_path: Path):
    """--upgrade merges and --force clobbers — passing both must be an explicit
    error, not a silent pick of one behavior."""
    _install_from(toolkit, tmp_path)
    out = _install_from(toolkit, tmp_path, "--upgrade", "--force", expect_rc=1)
    assert "--upgrade cannot combine" in out


def test_fresh_install_never_prunes_a_preexisting_file(tmp_path: Path):
    """The retired-path prune is upgrade-only: with no prior manifest, a repo that
    happens to already have templates/PRODUCT.md keeps it — we only clean up our
    own past installs, never a stranger's file."""
    (tmp_path / "templates").mkdir()
    own = "the user's own unrelated product template\n"
    (tmp_path / "templates" / "PRODUCT.md").write_text(own)
    _install(tmp_path)  # first install: prior manifest is None
    assert (tmp_path / "templates" / "PRODUCT.md").read_text() == own
