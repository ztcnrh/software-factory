"""install.py's CLAUDE.md planting, manifest, and uninstall — exercised as a real
subprocess against temp target repos (the installer is a standalone script, not
part of the package)."""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INSTALL = REPO / "install" / "install.py"


def _install(target: Path, *flags: str) -> str:
    r = subprocess.run(
        [sys.executable, str(INSTALL), str(target), *flags],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


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
