from pathlib import Path

import yaml

from factory.dispatch import Dispatcher
from factory.model import StationReport, WorkItem
from factory.policies import Policies


def _item(**kw) -> WorkItem:
    return WorkItem(id="WI-0001", title="t", **kw)


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
    the mechanism that raises the auto-ship metric over time."""
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
