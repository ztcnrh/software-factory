import argparse
import json
import subprocess
from pathlib import Path

import pytest

from factory.adapters import github
from factory.cli import _print_action, _resolve_actor, main
from factory.dispatch import Action, Dispatcher
from factory.line import Line
from factory.model import StationReport


def _gate_action(gate: str, state: str) -> Action:
    return Action(type="human_gate", item_id="WI-0001", state=state, gate=gate, message="Gate")


def test_blocked_gate_renders_a_distinct_glyph(capsys, factory_root: Path):
    """The blocked gate prints ⛔ (a station blocked itself — routed verdict or escape hatch),
    visually distinct from a routine checkpoint. Guards the gate-name special case
    in _print_action against a future 'collapse back to one icon lookup' regression."""
    _print_action(_gate_action("blocked", "blocked"), Line.load(factory_root / "line.yml"))
    assert "⛔" in capsys.readouterr().out


def test_routine_gate_keeps_the_plain_gate_glyph(capsys, factory_root: Path):
    """A normal human gate (ship_review) keeps ✋ and is never dressed as blocked —
    the ⛔ special case must stay scoped to the blocked gate alone."""
    _print_action(_gate_action("ship_review", "ship_review"), Line.load(factory_root / "line.yml"))
    out = capsys.readouterr().out
    assert "✋" in out
    assert "⛔" not in out


def test_resolve_actor_prefers_explicit_by_then_env(monkeypatch, tmp_path):
    """A gate signature must be a real identity. Explicit --by wins over everything;
    absent that, $FACTORY_USER — so decisions are attributable, never a bare 'human'."""
    monkeypatch.setenv("FACTORY_USER", "env-user")
    assert _resolve_actor(argparse.Namespace(by="alice", root=str(tmp_path))) == "alice"
    assert _resolve_actor(argparse.Namespace(by=None, root=str(tmp_path))) == "env-user"


def test_resolve_actor_falls_back_to_git_identity(monkeypatch, tmp_path):
    """With no --by and no env var, the repo's git identity signs the decision — the
    common local case, so signatures happen with zero extra effort from the human."""
    monkeypatch.delenv("FACTORY_USER", raising=False)
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Repo Owner"], cwd=tmp_path, check=True, capture_output=True
    )
    assert _resolve_actor(argparse.Namespace(by=None, root=str(tmp_path))) == "Repo Owner"


# --- input-trap regressions ---------------------------------------------------
# Every test below pins a case where the CLI used to silently drop or misroute
# caller input instead of failing (or warning) loudly.


def _item_at(factory_root: Path, state: str) -> str:
    """A persisted work item parked at the given state, ready to drive via main()."""
    d = Dispatcher(factory_root)
    item = d.new_item("test item")
    item.state = state
    d.store.save(item)
    return item.id


def test_gate_produced_flags_are_mutually_exclusive(factory_root: Path, capsys):
    """--produced and --produced-file must conflict loudly — the file used to
    silently win, discarding the inline evidence meant for the intervention record."""
    item_id = _item_at(factory_root, "spec_review")
    with pytest.raises(SystemExit) as exc:
        main(
            ["--root", str(factory_root), "gate", item_id, "--decision", "approved",
             "--produced", "inline", "--produced-file", "somewhere.md"]
        )
    assert exc.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_policy_list_and_reinstate_flow(factory_root: Path, capsys):
    """The operator's view of the ratchet: list shows live status per rule
    (active/dormant/suspended with the why), reinstate re-arms, and a second
    reinstate fails loudly instead of pretending."""
    import yaml

    from factory.policies import PolicyState

    (factory_root / "policies.yml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "rules": [
                    {"id": "r-docs", "gate": "spec_review", "decision": "approved",
                     "when": {"labels_any": ["docs"]}, "approved_by": "johndoe"},
                    {"id": "r-dormant", "gate": "ship_review", "decision": "approved",
                     "when": "all", "approved_by": None},
                ],
            }
        )
    )
    PolicyState(factory_root).suspend("r-docs", "WI-0009", "steer at ship_review")
    rc = main(["--root", str(factory_root), "policy", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SUSPENDED" in out and "WI-0009" in out
    assert "dormant" in out

    rc = main(["--root", str(factory_root), "policy", "reinstate", "r-docs",
               "--by", "johndoe", "--notes", "reviewed"])
    assert rc == 0
    rc = main(["--root", str(factory_root), "policy", "list"])
    assert "SUSPENDED" not in capsys.readouterr().out.replace("reinstate", "")
    rc = main(["--root", str(factory_root), "policy", "reinstate", "r-docs"])
    assert rc == 1
    assert "not suspended" in capsys.readouterr().err


def test_brief_writes_the_run_packet_and_reuses_it(factory_root: Path, capsys):
    """The driver→station handoff becomes a file on disk: brief writes
    runs/<state>-<attempt>-brief.md once, and a re-run reuses it rather than
    clobbering the session context the driver may have appended."""
    d = Dispatcher(factory_root)
    item = d.new_item("Add CSV export", body="Users need CSV downloads.")
    item.state = "implement"
    d.store.save(item)
    rc = main(["--root", str(factory_root), "brief", item.id])
    out = capsys.readouterr().out
    assert rc == 0
    assert "# Station brief" in out and "## Session context (driver-added)" in out
    path = factory_root / ".factory" / "work-items" / item.id / "runs" / "implement-1-brief.md"
    assert path.exists()

    with open(path, "a") as f:
        f.write("\nInterview: prefer streaming export.\n")
    rc = main(["--root", str(factory_root), "brief", item.id])
    captured = capsys.readouterr()
    assert rc == 0
    assert "Interview: prefer streaming export." in captured.out  # reused, additions intact
    assert "reused" in captured.err

    rc = main(["--root", str(factory_root), "brief", item.id, "--force"])
    assert rc == 0
    assert "Interview" not in capsys.readouterr().out  # regenerated deterministically


def test_brief_marks_a_checking_station_session_section_closed(factory_root: Path, capsys):
    """A checking station's brief must say its session section is deliberately
    empty — the steering-blindness of checkers is part of the packet contract,
    not driver folklore."""
    d = Dispatcher(factory_root)
    item = d.new_item("Change under review")
    item.state = "code_review"
    d.store.save(item)
    rc = main(["--root", str(factory_root), "brief", item.id])
    out = capsys.readouterr().out
    assert rc == 0
    assert "deliberately empty" in out and "checking station" in out


def test_brief_surfaces_retry_context_and_the_review_conversation(factory_root: Path, capsys):
    """An implement retry's brief must carry what sent it back and point at the
    latest review conversation file — the retry starts from the worklist, not
    from archaeology."""
    d = Dispatcher(factory_root)
    item = d.new_item("Feature")
    item.state = "implement"
    d.store.save(item)
    item = d.store.load(item.id)
    d.advance(item, StationReport(station="implement", verdict="implemented"))
    review_dir = factory_root / ".factory" / "work-items" / item.id
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "review-1.md").write_text("## Worklist\n1. add tests")
    d.advance(
        item, StationReport(station="code_review", verdict="changes_requested", summary="no tests")
    )
    rc = main(["--root", str(factory_root), "brief", item.id])
    out = capsys.readouterr().out
    assert rc == 0
    assert "(attempt 2" in out
    assert "Routed here by:" in out and "no tests" in out
    assert "review-1.md" in out


def test_brief_refuses_a_gate_and_points_at_the_packet_flow(factory_root: Path, capsys):
    """Briefs are for station runs; at a human gate the right artifact is the
    review packet + gate --open — the error must teach the flow, not just fail."""
    item_id = _item_at(factory_root, "ship_review")
    rc = main(["--root", str(factory_root), "brief", item_id])
    err = capsys.readouterr().err
    assert rc == 1
    assert "review packet" in err and "--open" in err


def test_gate_open_rejects_decision_only_flags(factory_root: Path, capsys):
    """--open binds a review; decision flags riding along would be silently
    meaningless — reject them loudly instead of half-doing two verbs."""
    item_id = _item_at(factory_root, "spec_review")
    rc = main(
        ["--root", str(factory_root), "gate", item_id, "--open", "--decision", "approved"]
    )
    assert rc == 1
    assert "--open only binds" in capsys.readouterr().err


def test_gate_requires_a_decision_or_an_open(factory_root: Path, capsys):
    """A bare `factory gate <id>` does nothing recordable — demand one of the
    two verbs rather than exiting silently successful."""
    item_id = _item_at(factory_root, "spec_review")
    rc = main(["--root", str(factory_root), "gate", item_id])
    assert rc == 1
    assert "--decision is required" in capsys.readouterr().err


def test_gate_packet_flag_requires_open(factory_root: Path, capsys):
    """--packet outside --open would be silently dropped; the caller meant to
    bind a review, so say so."""
    item_id = _item_at(factory_root, "spec_review")
    rc = main(
        ["--root", str(factory_root), "gate", item_id, "--decision", "approved",
         "--packet", "nowhere.md"]
    )
    assert rc == 1
    assert "--packet only means something with --open" in capsys.readouterr().err


def test_gate_open_decide_drift_flow_end_to_end(factory_root: Path, capsys):
    """The full CLI arc: open binds (with a packet file), a post-review edit is
    refused with the culprit named, and --accept-drift records it — the codex
    TOCTOU guard as an operator actually drives it."""
    d = Dispatcher(factory_root)
    item = d.new_item("gated work")
    item.state = "ship_review"
    item.artifacts = ["evidence.md"]
    d.store.save(item)
    (factory_root / "evidence.md").write_text("all tests green")
    packet = factory_root / "packet.md"
    packet.write_text("# Review packet\nAll good.")

    rc = main(
        ["--root", str(factory_root), "gate", item.id, "--open", "--packet", str(packet)]
    )
    assert rc == 0
    assert "gate opened" in capsys.readouterr().out

    (factory_root / "evidence.md").write_text("actually, one test was skipped")
    rc = main(["--root", str(factory_root), "gate", item.id, "--decision", "approved"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "evidence.md" in err and "--accept-drift" in err

    rc = main(
        ["--root", str(factory_root), "gate", item.id, "--decision", "approved",
         "--accept-drift"]
    )
    assert rc == 0
    assert d.store.load(item.id).state == "deploy"


def test_gate_steering_without_notes_warns_but_records(factory_root: Path, capsys):
    """A send-back with no --notes still goes through (never block a human at a
    gate), but warns loudly: an intervention record without a why is a learning-loop
    entry the retro can't use."""
    item_id = _item_at(factory_root, "spec_review")
    rc = main(["--root", str(factory_root), "gate", item_id, "--decision", "needs_revision"])
    assert rc == 0
    assert "no --notes" in capsys.readouterr().err
    assert Dispatcher(factory_root).store.load(item_id).state == "spec"


def test_gate_plain_approval_does_not_warn(factory_root: Path, capsys):
    """The notes nudge is scoped to steering — a clean approval carries no learning
    signal to lose, so it must stay quiet."""
    item_id = _item_at(factory_root, "spec_review")
    rc = main(["--root", str(factory_root), "gate", item_id, "--decision", "approved"])
    assert rc == 0
    assert "no --notes" not in capsys.readouterr().err


def test_gate_warns_when_intervention_fields_ride_a_non_steer(factory_root: Path, capsys):
    """--expected/--category/--produced only land in an intervention record, which a
    plain approval never writes — they used to vanish silently; now the human is told
    to add --changed if they actually steered."""
    item_id = _item_at(factory_root, "spec_review")
    rc = main(
        ["--root", str(factory_root), "gate", item_id, "--decision", "approved",
         "--category", "missing-edge-case"]
    )
    assert rc == 0
    assert "add --changed" in capsys.readouterr().err


def test_advance_label_flag_lands_on_the_item(factory_root: Path):
    """`factory advance --label` must persist the label on the work item. Regression:
    the triage skill instructed stations to add labels, but advance had no --label
    flag — a phantom instruction with no channel, so classifications were dropped."""
    item_id = _item_at(factory_root, "triage")
    rc = main(
        ["--root", str(factory_root), "advance", item_id,
         "--verdict", "needs_spec", "--label", "read-only", "--label", "docs"]
    )
    assert rc == 0
    assert Dispatcher(factory_root).store.load(item_id).labels == ["read-only", "docs"]


def test_advance_label_conflicts_with_report(factory_root: Path, capsys):
    """--label is an inline flag, so pairing it with --report must be rejected like
    the others rather than silently dropped (labels carry into the StationReport JSON)."""
    item_id = _item_at(factory_root, "triage")
    report = factory_root / "report.json"
    report.write_text(json.dumps({"station": "triage", "verdict": "needs_spec"}))
    rc = main(
        ["--root", str(factory_root), "advance", item_id,
         "--report", str(report), "--label", "read-only"]
    )
    assert rc == 1
    assert "--label" in capsys.readouterr().err


def test_advance_report_conflicts_with_inline_flags(factory_root: Path, capsys):
    """--report used to silently ignore every inline flag passed alongside it;
    the combination must be rejected, naming the clashing flags."""
    item_id = _item_at(factory_root, "triage")
    report = factory_root / "report.json"
    report.write_text(json.dumps({"station": "triage", "verdict": "needs_spec"}))
    rc = main(
        ["--root", str(factory_root), "advance", item_id,
         "--report", str(report), "--verdict", "needs_spec"]
    )
    assert rc == 1
    assert "--verdict" in capsys.readouterr().err


def test_advance_report_station_mismatch_is_rejected(factory_root: Path, capsys):
    """A report file claiming a different station than the item's current state is
    almost certainly stale — reject it before it misattributes metrics, and leave
    the item untouched."""
    item_id = _item_at(factory_root, "triage")
    report = factory_root / "report.json"
    report.write_text(json.dumps({"station": "spec", "verdict": "ready_for_review"}))
    rc = main(["--root", str(factory_root), "advance", item_id, "--report", str(report)])
    assert rc == 1
    assert "stale" in capsys.readouterr().err
    assert Dispatcher(factory_root).store.load(item_id).state == "triage"


def test_advance_human_reason_requires_escalation(factory_root: Path, capsys):
    """--human-reason without --human-required used to vanish silently (dispatch
    only reads it on the escape-hatch branch) — now it's an explicit error."""
    item_id = _item_at(factory_root, "triage")
    rc = main(
        ["--root", str(factory_root), "advance", item_id,
         "--verdict", "needs_spec", "--human-reason", "why"]
    )
    assert rc == 1
    assert "--human-required" in capsys.readouterr().err


def test_advance_spawn_body_requires_spawn_title(factory_root: Path, capsys):
    """--spawn-body without --spawn-title used to spawn nothing, silently — the
    follow-up item the station meant to file just disappeared."""
    item_id = _item_at(factory_root, "triage")
    rc = main(
        ["--root", str(factory_root), "advance", item_id,
         "--verdict", "needs_spec", "--spawn-body", "details"]
    )
    assert rc == 1
    assert "--spawn-title" in capsys.readouterr().err


def test_advance_risk_rejects_unknown_levels(factory_root: Path, capsys):
    """`advance --risk` takes the same closed set as `new --risk` — a typo'd level
    must fail at the parser, not silently pollute the item record."""
    item_id = _item_at(factory_root, "triage")
    with pytest.raises(SystemExit) as exc:
        main(
            ["--root", str(factory_root), "advance", item_id,
             "--verdict", "needs_spec", "--risk", "lo"]
        )
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_advance_confidence_must_be_in_unit_range(factory_root: Path, capsys):
    """Confidence is a 0-1 self-assessment; out-of-range values fail at the parser
    instead of skewing any future confidence-weighted policy."""
    item_id = _item_at(factory_root, "triage")
    with pytest.raises(SystemExit) as exc:
        main(
            ["--root", str(factory_root), "advance", item_id,
             "--verdict", "needs_spec", "--confidence", "1.5"]
        )
    assert exc.value.code == 2
    assert "between 0.0 and 1.0" in capsys.readouterr().err


def test_advance_human_required_needs_no_verdict(factory_root: Path):
    """The escape hatch bypasses routing, so forcing the (confused, escalating)
    station to invent a --verdict was pointless friction — escalation alone must
    land the item in blocked."""
    item_id = _item_at(factory_root, "triage")
    rc = main(
        ["--root", str(factory_root), "advance", item_id,
         "--human-required", "--human-reason", "ambiguous scope"]
    )
    assert rc == 0
    assert Dispatcher(factory_root).store.load(item_id).state == "blocked"


def test_new_parent_links_the_lineage(factory_root: Path, capsys):
    """A follow-up created with --parent must persist the origin link — it's the
    thread a retro follows from a regression back to the shipped change."""
    parent_id = _item_at(factory_root, "done")
    rc = main(
        ["--root", str(factory_root), "new", "Fix regression in export", "--parent", parent_id]
    )
    assert rc == 0
    d = Dispatcher(factory_root)
    child = [i for i in d.store.list_items() if i.id != parent_id][0]
    assert child.parent == parent_id
    main(["--root", str(factory_root), "status", child.id])
    assert f"parent: {parent_id}" in capsys.readouterr().out


def test_new_rejects_a_dangling_parent(factory_root: Path, capsys):
    """A typo'd --parent must fail loudly with nothing created — a silent dangling
    pointer would break the lineage exactly when someone tried to record it."""
    rc = main(["--root", str(factory_root), "new", "Follow-up", "--parent", "WI-9999"])
    assert rc == 1
    assert "not a known work item" in capsys.readouterr().err
    assert Dispatcher(factory_root).store.list_ids() == []


def test_new_source_ref_defaults_source_to_github(factory_root: Path, capsys):
    """--source-ref alone must mark the item as a github mirror (the one adapter
    that exists) while an explicit --source wins — the mirror link is what makes
    an issue-ingested item recognizable and deduplicatable."""
    rc = main(["--root", str(factory_root), "new", "From issue", "--source-ref", "42"])
    assert rc == 0
    d = Dispatcher(factory_root)
    item = d.store.list_items()[0]
    assert (item.source, item.source_ref) == ("github", "42")
    main(["--root", str(factory_root), "status", item.id])
    assert "source: github 42" in capsys.readouterr().out


def _capture_label_syncs(monkeypatch) -> list[tuple]:
    """Record (issue, new_state, old_state) for every label sync, with gh present."""
    calls: list[tuple] = []
    monkeypatch.setattr(github, "available", lambda: True)
    monkeypatch.setattr(
        github,
        "sync_label",
        lambda issue, new_state, old_state=None, repo=None: (
            calls.append((issue, new_state, old_state)) or (0, "")
        ),
    )
    return calls


def test_new_source_ref_stamps_the_issue_label(factory_root: Path, monkeypatch):
    """Creating an item that mirrors an issue stamps factory:<start> on the issue at
    birth (as intake does) — an externally-sourced item is visible on its issue from
    the moment it joins the line."""
    calls = _capture_label_syncs(monkeypatch)
    main(["--root", str(factory_root), "new", "From issue", "--source-ref", "7"])
    assert calls == [("7", "triage", None)]


def test_advance_mirrors_new_state_onto_the_source_issue(factory_root: Path, monkeypatch):
    """Every transition of a tracker-sourced item projects onto its issue label — old
    state removed, new added — so the issue is a live state anchor, not a birth-only
    stamp. Closes the gap where sync_label fired only at intake."""
    calls = _capture_label_syncs(monkeypatch)
    main(["--root", str(factory_root), "new", "From issue", "--source-ref", "7"])
    calls.clear()
    main(["--root", str(factory_root), "advance", "WI-0001", "--verdict", "needs_spec"])
    assert calls == [("7", "spec", "triage")]


def test_local_items_never_reach_for_github(factory_root: Path, monkeypatch):
    """A factory driven with no tracker integration must never touch gh: the mirror
    keys off an item's source, so a local item's transitions are side-effect-free —
    the source check short-circuits before the adapter is even consulted."""
    touched: list[str] = []
    monkeypatch.setattr(github, "available", lambda: touched.append("available") or True)
    monkeypatch.setattr(github, "sync_label", lambda *a, **k: touched.append("sync") or (0, ""))
    main(["--root", str(factory_root), "new", "Local task"])
    main(["--root", str(factory_root), "advance", "WI-0001", "--verdict", "needs_spec"])
    assert touched == []


def test_transition_label_sync_failure_warns_but_advances(
    factory_root: Path, monkeypatch, capsys
):
    """A failed label sync on a transition is best-effort: it warns but never rolls
    back or fails the advance — local state is the source of truth, the label only
    projects it."""
    monkeypatch.setattr(github, "available", lambda: True)
    monkeypatch.setattr(github, "sync_label", lambda *a, **k: (1, "label not found"))
    main(["--root", str(factory_root), "new", "From issue", "--source-ref", "7"])
    rc = main(["--root", str(factory_root), "advance", "WI-0001", "--verdict", "needs_spec"])
    assert rc == 0
    assert "label sync failed" in capsys.readouterr().err


def test_revive_via_cli_lands_back_in_the_loop(factory_root: Path, capsys):
    """The full revive path through main(): the parked item re-enters the line
    and the operator gets the NEXT: directive to keep driving."""
    item_id = _item_at(factory_root, "parked")
    rc = main(["--root", str(factory_root), "revive", item_id, "--notes", "back on"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "revived" in out and "NEXT:" in out
    assert Dispatcher(factory_root).store.load(item_id).state == "triage"


def test_parked_next_action_advertises_revive(factory_root: Path, capsys):
    """`factory next` on a parked item must say how to get it back — a terminal
    message with no way forward makes parked feel like a dead end."""
    item_id = _item_at(factory_root, "parked")
    rc = main(["--root", str(factory_root), "next", item_id])
    assert rc == 0
    assert f"factory revive {item_id}" in capsys.readouterr().out


def test_correct_requires_state_and_reason(factory_root: Path, capsys):
    """`factory correct` without --state/--reason must fail at the parser — an
    unexplained correction would be an audit-trail hole, not a convenience."""
    item_id = _item_at(factory_root, "spec")
    with pytest.raises(SystemExit) as exc:
        main(["--root", str(factory_root), "correct", item_id, "--state", "triage"])
    assert exc.value.code == 2
    assert "--reason" in capsys.readouterr().err


def test_correct_moves_the_item_via_the_cli(factory_root: Path, capsys):
    """The full correct path through main(): state set, audit note in the output,
    and the next action printed so the operator lands back in the loop."""
    item_id = _item_at(factory_root, "spec")
    rc = main(
        ["--root", str(factory_root), "correct", item_id,
         "--state", "triage", "--reason", "advanced the wrong item", "--by", "alice"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "corrected spec → triage" in out
    assert "NEXT:" in out
    assert Dispatcher(factory_root).store.load(item_id).state == "triage"


def test_metrics_prints_trend_only_with_a_prior_window(factory_root: Path, capsys):
    """`factory metrics` shows the recent-vs-prior trend line once a prior window
    exists, and hides it before that — an early 'trend' over too few ships would
    be noise dressed as signal."""
    from factory.metrics import Metrics

    m = Metrics(factory_root)
    for i in range(3):
        m.emit(kind="shipped", item=f"s{i}", steers=0, cost=1.0)
    main(["--root", str(factory_root), "metrics"])
    assert "trend:" not in capsys.readouterr().out
    for i in range(4):
        m.emit(kind="shipped", item=f"t{i}", steers=1, cost=1.0)
    main(["--root", str(factory_root), "metrics"])
    out = capsys.readouterr().out
    assert "trend:" in out
    assert "last 5 ships" in out and "prior 2" in out


def test_triage_decomposition_report_spawns_leaves_and_parks_the_umbrella(
    factory_root: Path, capsys
):
    """The exact recipe the triage skill prescribes for oversized items — a
    --report file with verdict park + a spawn list — must fan the leaves into
    triage (parented to the umbrella) and shelve the umbrella revivably."""
    item_id = _item_at(factory_root, "triage")
    report = factory_root / "report.json"
    report.write_text(
        json.dumps(
            {
                "verdict": "park",
                "summary": "decomposed into leaf items",
                "spawn": [
                    {"title": "Leaf: export CSV", "body": "self-contained"},
                    {"title": "Leaf: export JSON", "body": "self-contained"},
                ],
            }
        )
    )
    rc = main(["--root", str(factory_root), "advance", item_id, "--report", str(report)])
    assert rc == 0
    d = Dispatcher(factory_root)
    umbrella = d.store.load(item_id)
    assert umbrella.state == "parked"
    leaves = [i for i in d.store.list_items() if i.parent == item_id]
    assert sorted(x.title for x in leaves) == ["Leaf: export CSV", "Leaf: export JSON"]
    assert all(x.state == "triage" for x in leaves)


def test_ledger_round_trip_via_cli(factory_root: Path, capsys):
    """The retro station drives the ledger through the CLI — add, update, and the
    open-rows list must round-trip, and the rendered LEDGER.md must land."""
    rc = main(
        ["--root", str(factory_root), "ledger", "add", "--title", "sharpen spec skill",
         "--lever", "skill-edit", "--signal", "validation send-backs stop",
         "--file", ".claude/skills/write-product-spec/SKILL.md"]
    )
    assert rc == 0
    assert "RP-0001" in capsys.readouterr().out
    rc = main(
        ["--root", str(factory_root), "ledger", "update", "RP-0001",
         "--status", "applied", "--pr", "https://pr/7"]
    )
    assert rc == 0
    capsys.readouterr()
    main(["--root", str(factory_root), "ledger", "list", "--open"])
    out = capsys.readouterr().out
    assert "RP-0001" in out and "[applied open]" in out
    assert (factory_root / ".factory" / "retro" / "LEDGER.md").exists()


def test_help_renders_usage_examples(capsys):
    """The parser is the CLI's source-of-truth documentation: `-h` on the three
    workhorse commands must render the Examples epilog (cheap drift protection)."""
    for cmd in ("new", "advance", "gate"):
        with pytest.raises(SystemExit) as exc:
            main([cmd, "-h"])
        assert exc.value.code == 0
        assert "Examples:" in capsys.readouterr().out


def test_doctor_reports_healthy_on_a_clean_root(factory_root: Path, capsys):
    """The baseline: a fresh, consistent factory must exit 0 with zero errors —
    doctor's silence has to be trustworthy before its noise can be."""
    d = Dispatcher(factory_root)
    d.new_item("clean item")
    rc = main(["--root", str(factory_root), "doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "0 error(s)" in out


def test_doctor_catches_a_corrupt_item_and_an_unknown_state(factory_root: Path, capsys):
    """The two hard failures a crashed or hand-edited store can leave: an
    unparseable item JSON and an item stranded on a state the line doesn't
    know. Both must be errors (exit 1), not warnings."""
    d = Dispatcher(factory_root)
    item = d.new_item("will be corrupted")
    stranded = d.new_item("off the line")
    stranded.state = "no_such_state"
    d.store.save(stranded)
    (factory_root / ".factory" / "work-items" / f"{item.id}.json").write_text("{TORN")
    rc = main(["--root", str(factory_root), "doctor"])
    captured = capsys.readouterr()
    assert rc == 1
    assert item.id in captured.err
    assert "no_such_state" in captured.err


def test_doctor_warns_on_lineage_bindings_and_overlay_drift(factory_root: Path, capsys):
    """The soft inconsistencies that rot silently: a dangling parent pointer, a
    stale gate binding on a non-gate state, and a suspension for a rule that
    left policies.yml — surfaced as warnings, exit 0."""
    from factory.policies import PolicyState

    d = Dispatcher(factory_root)
    item = d.new_item("orphan child")
    item.parent = "WI-9999"
    item.metadata["gate_open"] = {"gate": "spec_review"}
    d.store.save(item)  # at triage (not a gate) with a binding + missing parent
    PolicyState(factory_root).suspend("ghost-rule", "WI-0001", "steer")
    rc = main(["--root", str(factory_root), "doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "WI-9999" in out
    assert "gate_open" in out
    assert "ghost-rule" in out
    assert "3 warning(s)" in out
