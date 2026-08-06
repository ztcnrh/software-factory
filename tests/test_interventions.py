"""Intervention record formatting."""

from factory.interventions import Interventions
from factory.model import GateDecision, WorkItem


def _record(tmp_path, produced: str) -> str:
    item = WorkItem(id="WI-0001", title="test item", state="spec_review")
    decision = GateDecision(
        gate="spec_review", decision="needs_revision", changed=True, notes="why"
    )
    path = Interventions(tmp_path).record(item, decision, "spec_review", produced=produced)
    return path.read_text()


def test_produced_markdown_is_fenced(tmp_path):
    """Embedded station output must not break the record's own heading structure —
    a produced artifact with its own H1 and code blocks stays inside a wrapper fence
    (regression: raw interpolation spliced two documents into one outline)."""
    produced = "# Product Spec — WI-0001\n\nSome spec.\n\n```python\nx = 1\n```\n"
    text = _record(tmp_path, produced)
    fenced = text[text.index("````markdown") : text.index("\n````\n")]
    assert "# Product Spec — WI-0001" in fenced
    assert "```python" in fenced
    # The record's own sections survive intact after the embedded content.
    assert "## What the human wanted instead" in text.split("````", 2)[2]


def test_fence_outranks_embedded_backtick_runs(tmp_path):
    """The wrapper fence must always be longer than any backtick run in the
    content, or the embedded artifact could close it early."""
    produced = "````\nfour ticks inside\n````"
    text = _record(tmp_path, produced)
    assert "`````markdown" in text


def test_empty_produced_stays_a_plain_placeholder(tmp_path):
    """No artifact given means the placeholder speaks in the record's own voice —
    fencing it would present prose as embedded content."""
    text = _record(tmp_path, "")
    assert "(see work item artifacts)" in text
    assert "markdown" not in text.split("---")[0].split("## What the station produced")[1]


def _steer(tmp_path, produced: str = "", notes: str = "why", category: str = "missing-edge-case"):
    item = WorkItem(id="WI-0001", title="test item", state="spec_review")
    decision = GateDecision(
        gate="spec_review",
        decision="needs_revision",
        changed=True,
        notes=notes,
        category=category,
    )
    Interventions(tmp_path).record(item, decision, "spec_review", produced=produced)
    return Interventions(tmp_path).records()[0]


def test_records_parses_the_whole_machine_block(tmp_path):
    """The block advertises itself as machine-readable, so every field in it must
    reach the reader typed — not a hand-picked three, and not `changed` as the
    string "false" (write-only fields are how a signal dies unnoticed)."""
    rec = _steer(tmp_path)
    assert rec["item"] == "WI-0001"
    assert rec["gate"] == "spec_review"
    assert rec["decision"] == "needs_revision"
    assert rec["category"] == "missing-edge-case"
    assert rec["changed"] is True
    assert rec["state_before"] == "spec_review"
    assert rec["ts"].endswith("Z") and "T" in rec["ts"]


def test_embedded_yaml_in_the_produced_artifact_does_not_shadow_the_block(tmp_path):
    """A sent-back spec quoting a yaml snippet is ordinary here (this repo's own
    specs quote line.yml), and the old line-grep took the FIRST match — so the
    artifact's `item:` won and the record described the wrong work item."""
    produced = '```yaml\nitem: WI-9999\ngate: ship_review\ncategory: "wrong-scope"\n```\n'
    rec = _steer(tmp_path, produced=produced)
    assert rec["item"] == "WI-0001"
    assert rec["category"] == "missing-edge-case"


def test_unterminated_yaml_fence_in_notes_does_not_swallow_the_block(tmp_path):
    """--notes is interpolated unfenced, so an unclosed ```yaml in it would pair
    with the machine block's OPENING fence — making the last fence in the file a
    garbage match. Anchoring on the marker is what makes this survivable."""
    rec = _steer(tmp_path, notes="I wanted:\n```yaml\nitem: WI-9999\n")
    assert rec["item"] == "WI-0001"
    assert rec["gate"] == "spec_review"


def test_two_steers_in_the_same_second_both_survive(tmp_path):
    """Filenames carry second resolution, so a gate steered twice inside one second
    used to have the later record silently overwrite the earlier — losing a steer
    the retro can never recover (found driving the real CLI, not by the suite)."""
    item = WorkItem(id="WI-0001", title="test item", state="spec_review")
    ints = Interventions(tmp_path)
    for cat in ("missing-edge-case", "wrong-scope"):
        ints.record(
            item,
            GateDecision(gate="spec_review", decision="needs_revision", category=cat),
            "spec_review",
        )
    recs = ints.records()
    assert len(recs) == 2
    assert {r["category"] for r in recs} == {"missing-edge-case", "wrong-scope"}
    # The suffixed name must still yield a timestamp, or the second record drops
    # out of the recurrence join it was just rescued for.
    assert all(r.get("ts") for r in recs)


def test_records_survive_a_record_with_no_machine_block(tmp_path):
    """Best-effort is the contract: a hand-written or truncated record still
    contributes its path and timestamp rather than dropping out of the join set."""
    d = tmp_path / ".factory" / "interventions"
    d.mkdir(parents=True)
    (d / "WI-0002-ship_review-2026-07-26T10-00-00Z.md").write_text("# just prose\n")
    rec = Interventions(tmp_path).records()[0]
    assert rec["ts"] == "2026-07-26T10:00:00Z"
    assert "category" not in rec


def test_malformed_signal_lines_become_markers(tmp_path):
    """The hook appends to _signals.jsonl blindly (fail-open), so a corrupt line
    must neither break parsing nor vanish silently — it leaves an in-place marker
    so the retro knows a steer was lost, and the briefing renders that blip."""
    from factory.retro import briefing

    sig_dir = tmp_path / ".factory" / "interventions"
    sig_dir.mkdir(parents=True)
    (sig_dir / "_signals.jsonl").write_text(
        '{"ts": "t1", "waiting_items": ["WI-0001"], "steering": "add validation"}\n'
        "not json at all\n"
        '{"ts": "t2", "waiting_items": ["WI-0002"], "steering": "wrong scope"}\n'
    )
    signals = Interventions(tmp_path).signals()
    assert [s.get("ts") for s in signals] == ["t1", None, "t2"]
    assert signals[1] == {"malformed": True}
    assert "a steer was lost here" in briefing(tmp_path)


def test_briefing_flags_repeated_station_runs(tmp_path):
    """A station re-running past the threshold writes no intervention record, so
    the briefing must surface it by attempt count — labeled enough to orient a
    stateless agent, which then diagnoses the cause from the item's history."""
    from factory.retro import briefing
    from factory.store import Store

    store = Store(tmp_path)
    hot = WorkItem(id="WI-0001", title="churny feature", state="ship_review")
    hot.attempts = {"implement": 4, "code_review": 3, "triage": 1}
    store.save(hot)
    text = briefing(tmp_path)
    assert "## Items with repeated station runs" in text
    assert "WI-0001" in text and "`implement`×4" in text and "`code_review`×3" in text
    assert "Item current state: ship_review" in text  # labeled, not a bare dump
    assert "`triage`×1" not in text  # below threshold — noise stays out


def test_briefing_omits_churn_section_when_all_quiet(tmp_path):
    """Items that moved through cleanly must not manufacture a churn section —
    an empty warning dilutes the briefing's signal."""
    from factory.retro import briefing
    from factory.store import Store

    calm = WorkItem(id="WI-0001", title="clean feature", state="done")
    calm.attempts = {"implement": 1, "code_review": 1}
    Store(tmp_path).save(calm)
    assert "## Items with repeated station runs" not in briefing(tmp_path)


def test_briefing_includes_chat_signals(tmp_path):
    """Regression: _signals.jsonl used to be written by the hook but never read —
    chat steering must reach the retro station via the briefing."""
    from factory.retro import briefing

    sig_dir = tmp_path / ".factory" / "interventions"
    sig_dir.mkdir(parents=True)
    (sig_dir / "_signals.jsonl").write_text(
        '{"ts": "t1", "waiting_items": ["WI-0001"], "steering": "spec misses rate limiting"}\n'
    )
    text = briefing(tmp_path)
    assert "## Chat steering signals" in text
    assert "spec misses rate limiting" in text
