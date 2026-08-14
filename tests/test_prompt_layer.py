"""The station prompt layer — the few properties of `.claude/` a machine can check.

A badly worded instruction passes straight through this suite and through the CLI, so
nothing here judges whether a prompt is *good*. What it does pin is structural: a rule
that exists in several agent files says the same thing in all of them, and a pointer to
a skill leads somewhere real.
"""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
AGENTS = REPO / ".claude" / "agents"
SKILLS = REPO / ".claude" / "skills"

ALL_STATIONS = [
    "factory-triage",
    "factory-spec",
    "factory-implement",
    "factory-code-review",
    "factory-verify",
    "factory-retro",
]
PRODUCERS = ["factory-triage", "factory-spec", "factory-implement"]
CHECKERS = ["factory-code-review", "factory-verify"]

# An agent file becomes its station's system prompt — always in front of the model,
# for the whole run — which the preloaded skill is not. That position is why these
# rules are duplicated instead of pointed at, and drift between the copies is the
# only real cost of duplicating them. Retro is deliberately absent from everything
# but `authority`: it has no work item, no brief, and never calls `advance`.
SHARED_BLOCKS = {
    "authority": ALL_STATIONS,
    "station-run": PRODUCERS + CHECKERS,
    "producer": PRODUCERS,
    "checker": CHECKERS,
}


def _agent_text(station: str) -> str:
    return (AGENTS / f"{station}.md").read_text()


def _block(text: str, name: str) -> str | None:
    """The body between a block's markers, or None when the block isn't there."""
    open_tag, close_tag = f"<!-- factory:{name} -->", f"<!-- /factory:{name} -->"
    if open_tag not in text or close_tag not in text:
        return None
    return text.split(open_tag, 1)[1].split(close_tag, 1)[0]


def _frontmatter(text: str) -> dict:
    return yaml.safe_load(text.split("---", 2)[1])


def test_every_station_agent_carries_its_shared_blocks_byte_identical():
    """A rule duplicated across agent files must be the same rule in each — six copies
    exist for prompt position, not to let six stations drift apart."""
    for block, stations in SHARED_BLOCKS.items():
        bodies = {s: _block(_agent_text(s), block) for s in stations}
        missing = [s for s, body in bodies.items() if body is None]
        assert not missing, f"{block!r} block missing from: {missing}"
        assert len(set(bodies.values())) == 1, f"{block!r} block has drifted: {bodies}"


def test_a_station_agent_carries_no_block_it_did_not_opt_into():
    """Blocks are opt-in per role: a checker that picks up the producer block would tell
    verify to trust chat steering, which is exactly what makes it a checker."""
    for station in ALL_STATIONS:
        text = _agent_text(station)
        for block, stations in SHARED_BLOCKS.items():
            if station not in stations:
                assert _block(text, block) is None, f"{station} carries {block!r} uninvited"


def test_every_preloaded_skill_named_by_a_station_agent_exists():
    """A typo in `skills:` preloads nothing and fails silently — the station then works
    from the agent file alone and improvises the procedure."""
    for station in ALL_STATIONS:
        for skill in _frontmatter(_agent_text(station)).get("skills", []):
            assert (SKILLS / skill / "SKILL.md").is_file(), f"{station} preloads missing {skill}"


def test_every_skill_path_named_in_the_prompt_layer_resolves():
    """A dead on-demand pointer doesn't error, it just doesn't load — and the station
    proceeds without the contract it was told to read."""
    dead = []
    for md in sorted((REPO / ".claude").rglob("*.md")) + sorted((REPO / "templates").glob("*.md")):
        for word in md.read_text().replace("`", " ").split():
            path = word.strip("(),.;:")
            if path.startswith(".claude/skills/") and path.endswith("SKILL.md"):
                if not (REPO / path).is_file():
                    dead.append(f"{md.relative_to(REPO)} → {path}")
    assert not dead, f"pointers to skills that do not exist: {dead}"
