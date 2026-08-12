from pathlib import Path

import pytest
import yaml

from factory.dispatch import Dispatcher
from factory.model import GateDecision, StationReport, WorkItem
from factory.policies import Policies, PolicyError, PolicyState
from factory.retro import briefing


def _item(labels: list[str] | None = None, **kw) -> WorkItem:
    item = WorkItem(id="WI-0001", title="t", **kw)
    for name in labels or []:
        item.add_label(name, by="triage")
    return item


def test_dormant_rule_is_ignored():
    """A retro-proposed rule with no approver must NOT auto-clear a gate — the
    human's signature is the activation switch."""
    pol = Policies(
        {
            "rules": [
                {
                    "id": "r",
                    "gate": "spec_review",
                    "decision": "approved",
                    "when": {"labels_any": ["docs"]},
                    "approved_by": None,
                }
            ]
        }
    )
    assert pol.auto_decision("spec_review", _item(labels=["docs"], risk="low")) is None


def test_approved_rule_respects_labels_gate_and_risk_ceiling():
    """An approved rule clears the gate only when the gate, labels, and risk
    ceiling all match — so a learned shortcut can't leak onto riskier work."""
    rule = {
        "id": "r",
        "gate": "spec_review",
        "decision": "approved",
        "when": {"labels_any": ["docs"], "max_risk": "low"},
        "approved_by": "johndoe",
    }
    pol = Policies({"rules": [rule]})
    assert pol.auto_decision("spec_review", _item(labels=["docs"], risk="low")) == rule
    assert pol.auto_decision("spec_review", _item(labels=["docs"], risk="high")) is None
    assert pol.auto_decision("ship_review", _item(labels=["docs"], risk="low")) is None


def test_approved_policy_clears_gate_with_no_human_touch(factory_root: Path):
    """End to end: an approved policy lets the dispatcher walk past a gate as an
    'auto_gate', advancing the item without incrementing human_touches. This is
    the mechanism that grows the hands-off share over time."""
    (factory_root / "policies.yml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "default": "require_human",
                "rules": [
                    {
                        "id": "auto-docs-spec",
                        "gate": "spec_review",
                        "decision": "approved",
                        "when": {"labels_any": ["docs"], "max_risk": "low"},
                        "approved_by": "johndoe",
                    }
                ],
            }
        )
    )
    d = Dispatcher(factory_root)
    item = d.new_item("Docs change", labels=["docs"], risk="low")
    d.advance(item, StationReport(station="triage", verdict="needs_spec"))
    d.advance(item, StationReport(station="spec", verdict="ready_for_review"))
    assert item.state == "spec_review"

    action = d.next_action(item)
    assert action.type == "auto_gate"
    d.apply_auto_gate(item, "spec_review", d.policies.auto_decision("spec_review", item))
    assert item.state == "implement"
    assert item.human_touches == 0


# --- the autonomy ratchet: promotion is human, demotion is automatic ---


def _write_docs_rule(factory_root: Path) -> None:
    (factory_root / "policies.yml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "default": "require_human",
                "rules": [
                    {
                        "id": "auto-docs-spec",
                        "gate": "spec_review",
                        "decision": "approved",
                        "when": {"labels_any": ["docs"], "max_risk": "low"},
                        "approved_by": "johndoe",
                    }
                ],
            }
        )
    )


def _auto_clear_to_implement(d: Dispatcher) -> WorkItem:
    item = d.new_item("Docs change", labels=["docs"], risk="low")
    d.advance(item, StationReport(station="triage", verdict="needs_spec"))
    d.advance(item, StationReport(station="spec", verdict="ready_for_review"))
    rule = d.active_auto_rule("spec_review", item)
    d.apply_auto_gate(item, "spec_review", rule)
    assert item.state == "implement"
    return item


def test_a_steer_on_an_auto_cleared_item_suspends_the_rule(factory_root: Path):
    """The demotion half of the ratchet: a rule that vouched for an item which
    later needed human rework is suspended — its gate returns to the human —
    and the next matching item must NOT auto-clear."""
    _write_docs_rule(factory_root)
    d = Dispatcher(factory_root)
    item = _auto_clear_to_implement(d)
    d.advance(item, StationReport(station="implement", verdict="implemented"))
    d.advance(item, StationReport(station="code_review", verdict="pass"))
    d.advance(item, StationReport(station="verify", verdict="verified"))
    d.gate(item, GateDecision(gate="ship_review", decision="not_ready", notes="broken UX"))
    assert "auto-docs-spec" in d.policy_state.suspended()
    assert any("suspended" in (e.note or "") for e in item.history)

    second = d.new_item("Another docs change", labels=["docs"], risk="low")
    d.advance(second, StationReport(station="triage", verdict="needs_spec"))
    d.advance(second, StationReport(station="spec", verdict="ready_for_review"))
    assert d.next_action(second).type == "human_gate"  # the gate is human again


def test_a_block_on_an_auto_cleared_item_also_suspends(factory_root: Path):
    """Autonomy breaking at a station (blocked) is the same failure signal as a
    gate steer — the rules that vouched for the item are suspended either way."""
    _write_docs_rule(factory_root)
    d = Dispatcher(factory_root)
    item = _auto_clear_to_implement(d)
    d.advance(
        item,
        StationReport(
            station="implement", verdict="", human_required=True, human_reason="stuck"
        ),
    )
    assert item.state == "blocked"
    assert "auto-docs-spec" in d.policy_state.suspended()


def test_reinstate_rearms_a_suspended_rule(factory_root: Path):
    """Reinstatement is the human's half of the ratchet: after review, the rule
    fires again — and reinstating something never suspended fails loudly."""
    _write_docs_rule(factory_root)
    d = Dispatcher(factory_root)
    d.policy_state.suspend("auto-docs-spec", "WI-0001", "steer at ship_review")
    item = d.new_item("Docs change", labels=["docs"], risk="low")
    d.advance(item, StationReport(station="triage", verdict="needs_spec"))
    d.advance(item, StationReport(station="spec", verdict="ready_for_review"))
    assert d.next_action(item).type == "human_gate"
    d.policy_state.reinstate("auto-docs-spec", by="johndoe", notes="rule wasn't at fault")
    assert d.next_action(item).type == "auto_gate"
    with pytest.raises(PolicyError, match="not suspended"):
        d.policy_state.reinstate("never-suspended", by="johndoe")


def test_a_suspended_rule_does_not_shadow_a_later_matching_rule(factory_root: Path):
    """Suspension removes ONE rule from consideration; another signed rule that
    also matches must still fire — the overlay filters, it doesn't veto the gate."""
    r1 = {"id": "r1", "gate": "g", "decision": "approved", "when": "all", "approved_by": "a"}
    r2 = {"id": "r2", "gate": "g", "decision": "approved", "when": "all", "approved_by": "a"}
    pol = Policies({"rules": [r1, r2]})
    assert pol.auto_decision("g", _item(), suspended={"r1"}) == r2


def test_briefing_surfaces_suspended_policies(factory_root: Path):
    """A suspension the retro never hears about stays in limbo forever — the
    briefing must list each suspended rule with its why, as retro input."""
    PolicyState(factory_root).suspend("auto-docs-spec", "WI-0002", "steer at ship_review")
    text = briefing(factory_root)
    assert "Suspended gate policies" in text
    assert "auto-docs-spec" in text and "WI-0002" in text


# --- load-time validation: a malformed rule must fail loud, never silently widen ---


def _rule(**over) -> dict:
    base = {"id": "r", "gate": "spec_review", "decision": "approved", "when": {"max_risk": "low"}}
    base.update(over)
    return base


def test_unknown_when_key_is_rejected_at_load():
    """A typo'd condition key (`lables_any`) must be a hard error, not a silent
    match-all. This is the central footgun: `_matches` ignores unknown keys, so an
    unvalidated typo would widen an approved rule to every item at its gate."""
    with pytest.raises(PolicyError, match="unknown condition key"):
        Policies({"rules": [_rule(when={"lables_any": ["docs"]})]})


def test_empty_or_missing_when_is_rejected():
    """An empty/absent `when` matches everything in `_matches`; forbid it so
    'auto-approve every item at this gate' can only ever be a deliberate `when: all`,
    never an accidental omission."""
    with pytest.raises(PolicyError, match="at least one condition"):
        Policies({"rules": [_rule(when={})]})
    with pytest.raises(PolicyError, match="at least one condition"):
        Policies({"rules": [{"id": "r", "gate": "spec_review", "decision": "approved"}]})


def test_missing_id_is_rejected():
    """A rule needs a stable id — it's the handle that appears in the auto_gate log
    actor and the metrics ledger, so an anonymous rule wouldn't be traceable."""
    anon = {"gate": "spec_review", "decision": "approved", "when": {"max_risk": "low"}}
    with pytest.raises(PolicyError, match="missing required 'id'"):
        Policies({"rules": [anon]})


def test_missing_gate_or_decision_is_rejected():
    """`gate` and `decision` are required — without them a matching rule would
    otherwise crash at apply time (KeyError / unroutable verdict) instead of at load."""
    with pytest.raises(PolicyError, match="missing required 'gate'"):
        Policies({"rules": [_rule(gate=None)]})
    with pytest.raises(PolicyError, match="missing required 'decision'"):
        Policies({"rules": [_rule(decision=None)]})


def test_bad_max_risk_value_is_rejected():
    """A `max_risk` outside the known risk ladder is silently coerced by `_matches`;
    reject it at load so the ceiling always means what it says."""
    with pytest.raises(PolicyError, match="max_risk"):
        Policies({"rules": [_rule(when={"max_risk": "lo"})]})


def test_validation_runs_on_dormant_rules_too():
    """A malformed rule is caught even while dormant (no `approved_by`), so the
    error surfaces at the retro-PR stage — before a human ever signs it."""
    with pytest.raises(PolicyError):
        Policies({"rules": [_rule(approved_by=None, when={"nope": 1})]})


def test_when_all_is_a_deliberate_match_everything():
    """`when: all` is the one sanctioned way to match every item at a gate — it
    passes validation and clears the gate for any item, unlike an empty `when`."""
    rule = _rule(when="all", approved_by="johndoe")
    pol = Policies({"rules": [rule]})
    assert pol.auto_decision("spec_review", _item(risk="high")) == rule
    assert pol.auto_decision("spec_review", _item(labels=[], risk="unknown")) == rule


def test_labels_all_requires_every_listed_label():
    """`labels_all` (the newly-documented key) matches only when the item carries
    every listed label — a stricter conjunction than `labels_any`."""
    rule = _rule(when={"labels_all": ["docs", "chore"]}, approved_by="johndoe")
    pol = Policies({"rules": [rule]})
    assert pol.auto_decision("spec_review", _item(labels=["docs", "chore"])) == rule
    assert pol.auto_decision("spec_review", _item(labels=["docs"])) is None
