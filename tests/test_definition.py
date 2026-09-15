"""The shape of a factory definition, checked on the one this repository ships, and the contract
between the caller a product repository commits and the reusable workflow it calls."""

import re
from pathlib import Path

from factory import cli

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"
CALLER = (ROOT / "templates" / "factory.yml").read_text()
WORKFLOW = (ROOT / ".github" / "workflows" / "factory.yml").read_text()


def frontmatter(skill: str) -> dict:
    text = (SKILLS / skill / "SKILL.md").read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, flags=re.S)
    assert m, f"{skill} has no frontmatter"
    return dict(line.split(":", 1) for line in m[1].splitlines() if ":" in line)


def keys(text: str, header: str) -> set[str]:
    """The keys directly under a block whose header line is exactly `header`."""
    indent = len(header) - len(header.lstrip())
    out, inside = set(), False
    for line in text.splitlines():
        if line == header:
            inside = True
            continue
        if inside:
            if line.strip() and (len(line) - len(line.lstrip())) <= indent:
                break
            if m := re.match(rf"^ {{{indent + 2}}}([\w-]+):", line):
                out.add(m[1])
    assert out, f"no keys under {header!r}"
    return out


def test_the_shipped_definition_has_every_station_with_a_model_and_its_tools():
    """run-station.sh reads `model:` and `allowed-tools:` from the station's frontmatter; a
    station without them fails at run time, after the workflow already spent a runner."""
    for station in (*cli.STATIONS, "retro"):
        fm = frontmatter(f"factory-{station}")
        assert fm["model"].strip() and fm["allowed-tools"].strip(), station


def test_the_skills_a_station_reads_by_path_are_in_the_definition():
    """A station names its helper skills relative to its own directory so the reference holds
    wherever the definition's skills are staged; every one it names has to ship with it."""
    for station in (*cli.STATIONS, "retro"):
        text = (SKILLS / f"factory-{station}" / "SKILL.md").read_text()
        for helper in re.findall(r"\$\{CLAUDE_SKILL_DIR\}/\.\./([\w-]+)/SKILL\.md", text):
            assert (SKILLS / helper / "SKILL.md").is_file(), f"{station} names {helper}"
        assert ".claude/skills/" not in text, f"{station} points into a product checkout"


def test_no_skill_lives_where_a_checkout_would_load_it_as_a_slash_command():
    """The definition is data the runner stages; nothing in this repository's own .claude/ may
    offer a station as a project skill, or a laptop with Claude Code becomes a driver."""
    assert not (ROOT / ".claude" / "skills").exists()


def test_the_caller_passes_only_inputs_and_secrets_the_workflow_declares():
    """A caller passing an unknown input fails at GitHub's validation on the adopter's side; the
    two files are edited together and checked here."""
    inputs = keys(WORKFLOW, "    inputs:")
    secrets = keys(WORKFLOW, "    secrets:")
    assert keys(CALLER, "    with:") <= inputs
    assert keys(CALLER, "    secrets:") == secrets
    assert {"definition", "definition_ref", "toolkit", "ref"} <= inputs
    assert re.search(r"uses: \S+/\.github/workflows/factory\.yml@\w+", CALLER)
