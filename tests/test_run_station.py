"""Tests for the one `claude -p` invocation, with `claude` replaced by a script that records what
it was asked and answers a canned result. The toolkit and the default definition are this
repository, so the skills the runner stages are the real ones."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github" / "scripts" / "run-station.sh"

RESULT = {"type": "result", "subtype": "success", "session_id": "s1", "num_turns": 2,
          "duration_ms": 1500, "total_cost_usd": 0.1234,
          "modelUsage": {"claude-sonnet": {"costUSD": 0.12}}}


@pytest.fixture
def run(tmp_path):
    """A product checkout as cwd, a fresh HOME, a fake `claude` first on PATH. Returns a callable
    taking the station and extra environment; the fake's record is in `run.fake`."""
    fake = tmp_path / "fake"
    fake.mkdir()
    claude = fake / "claude"
    claude.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$@\" > {fake}/args\n"
        f"env | grep -E '^(GH_TOKEN|FACTORY_TOKEN)=' > {fake}/env || true\n"
        f"cat {fake}/result.json\n")
    claude.chmod(0o755)
    (fake / "result.json").write_text(json.dumps(
        RESULT | {"structured_output": {"verdict": "ready_to_implement", "summary": "ok"}}))
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (tmp_path / "packet").mkdir()

    def go(station, **env):
        base = {"PATH": f"{fake}:{os.environ['PATH']}", "HOME": str(tmp_path / "home"),
                "STATION": station, "TOOLKIT": str(ROOT), "DEFINITION": str(ROOT),
                "DEFINITION_REPO": "o/factory", "GH_REPO": "o/app", "GH_TOKEN": "run-token",
                "PACKET": str(tmp_path / "packet"), "OUT": str(tmp_path / "out"),
                "OAUTH_TOKEN": "oauth", "ISSUE": "7", "PR": "12"}
        return subprocess.run(["bash", str(SCRIPT)], cwd=checkout, env=base | env,
                              capture_output=True, text=True)

    go.fake, go.checkout, go.home = fake, checkout, tmp_path / "home"
    return go


def args_of(run):
    return (run.fake / "args").read_text().splitlines()


def test_station_runs_the_definitions_skills_and_leaves_the_checkouts_alone(run, tmp_path):
    """The skills come from the definition, staged where Claude Code prefers them over a
    project's own; the product repository's .claude/ is neither read for them nor touched."""
    own = run.checkout / ".claude" / "skills" / "repository-conventions" / "SKILL.md"
    own.parent.mkdir(parents=True)
    own.write_text("---\nname: repository-conventions\n---\nours\n")
    proc = run("triage")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    staged = run.home / ".claude" / "skills"
    assert (staged / "factory-triage" / "SKILL.md").read_text() == (
        ROOT / "skills" / "factory-triage" / "SKILL.md").read_text()
    assert {p.name for p in staged.iterdir()} == {p.name for p in (ROOT / "skills").iterdir()}
    assert own.read_text() == "---\nname: repository-conventions\n---\nours\n"
    args = args_of(run)
    assert args[:2] == ["-p", f"/factory-triage Issue #7. Packet: {tmp_path / 'packet'}/."]
    assert args[args.index("--model") + 1] == "sonnet"  # from the real skill's frontmatter
    assert "--add-dir" not in args
    report = json.loads((tmp_path / "out" / "report.json").read_text())
    assert (report["station"], report["verdict"], report["cost_usd"], report["model"]) == (
        "triage", "ready_to_implement", 0.1234, "claude-sonnet")


def test_a_checkout_carrying_factory_skills_is_refused_before_claude_runs(run):
    """Two copies of one procedure is the seam this closes: a product repository that still holds
    a factory-* skill (the v2.1 install) is told to delete it, and no tokens are spent."""
    for name in ("factory-review", "council"):
        (run.checkout / ".claude" / "skills" / name).mkdir(parents=True)
    proc = run("review")
    assert proc.returncode == 1
    assert "::error::this repository carries factory skills at .claude/skills/{factory-review}" in (
        proc.stdout)
    assert "o/factory is their only source" in proc.stdout
    assert not (run.fake / "args").exists()


def test_a_definition_missing_the_station_or_the_layout_is_refused(run, tmp_path):
    """A definition is a repository with skills/; each station it runs is a skill in there."""
    partial = tmp_path / "partial"
    (partial / "skills" / "factory-triage").mkdir(parents=True)
    (partial / "skills" / "factory-triage" / "SKILL.md").write_text("---\nmodel: haiku\n---\n")
    proc = run("review", DEFINITION=str(partial))
    assert proc.returncode == 1 and "o/factory has no factory-review skill" in proc.stdout
    (tmp_path / "empty").mkdir()
    proc = run("triage", DEFINITION=str(tmp_path / "empty"))
    assert proc.returncode == 1 and "has no skills/ directory" in proc.stdout
    assert not (run.fake / "args").exists()


def test_retro_edits_the_definition_and_needs_a_token_that_can_write_there(run, tmp_path):
    """Retro's PR goes to the definition. Another repository's definition needs FACTORY_TOKEN
    before anything runs; this repository as its own definition runs on the run's token."""
    (run.fake / "result.json").write_text(json.dumps(
        RESULT | {"structured_output": {"verdict": "nothing_to_learn", "summary": "quiet"}}))
    proc = run("retro")
    assert proc.returncode == 1 and "FACTORY_TOKEN" in proc.stdout
    assert not (run.fake / "args").exists()

    proc = run("retro", FACTORY_TOKEN="def-token")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    args = args_of(run)
    assert args[1] == (
        f"/factory-retro Packet: {tmp_path / 'packet'}/. Definition: {ROOT}/ (o/factory).")
    assert args[args.index("--add-dir") + 1] == str(ROOT)
    env = dict(line.split("=", 1) for line in (run.fake / "env").read_text().splitlines())
    assert env == {"GH_TOKEN": "run-token", "FACTORY_TOKEN": "def-token"}

    proc = run("retro", DEFINITION_REPO="o/app")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    env = dict(line.split("=", 1) for line in (run.fake / "env").read_text().splitlines())
    assert env["FACTORY_TOKEN"] == "run-token"
