"""``factory`` — the command-line driver the /factory skill calls into.

Mental model: the dispatcher is the brain, Claude is the hands.

  factory new "<title>"      -> create a work item, show the first action
  factory next <id>          -> what to do next (auto-clears any policy gates)
  factory advance <id> ...   -> record a station's verdict, route the item
  factory gate <id> ...      -> record a human's decision at a gate
  factory status [<id>]      -> the board, or one item's full history
  factory metrics            -> the North Star ledger
  factory retro [--emit f]   -> briefing for the learning station

``factory next`` always prints a ``NEXT:`` line with compact JSON so the calling
agent can parse the directive unambiguously.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

from .dispatch import Action, Dispatcher
from .line import Line
from .model import GateDecision, StationReport
from .retro import briefing

# Keyed by Action.type. The `blocked` gate is not an action type — it surfaces as
# a `human_gate` — so its ⛔ glyph is applied by gate name in _print_action, not here.
_ICONS = {
    "run_station": "▶",
    "run_external": "⚙",
    "human_gate": "✋",
    "auto_gate": "⚡",
    "done": "✓",
    "parked": "⏸",
}

_STAGE_ORDER = [
    "triage",
    "spec",
    "spec_review",
    "implement",
    "code_review",
    "verify",
    "ship_review",
    "deploy",
    "needs_human",
    "blocked",
    "parked",
    "done",
]


def _root(args: argparse.Namespace) -> Path:
    return Path(args.root).resolve()


def _disp(args: argparse.Namespace) -> Dispatcher:
    return Dispatcher(_root(args))


def _resolve_actor(args: argparse.Namespace) -> str:
    """Who is deciding at this gate — a real, trackable signature, not a generic
    'human'. Explicit --by wins; then $FACTORY_USER, the repo's git identity, the
    OS login. 'unknown' only if every source comes up empty. This is what keeps
    every gate decision attributable, so who approved what is analyzable later."""
    if getattr(args, "by", None):
        return args.by.strip()
    env = os.environ.get("FACTORY_USER", "").strip()
    if env:
        return env
    try:
        r = subprocess.run(
            ["git", "config", "user.name"],
            cwd=_root(args),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 — getuser can raise if no login name resolves
        return "unknown"


def _resolve_next(d: Dispatcher, item_id: str) -> Action:
    """Walk forward through any policy-cleared gates, return the next real action."""
    item = d.store.load(item_id)
    while True:
        action = d.next_action(item)
        if action.type != "auto_gate":
            return action
        rule = d.policies.auto_decision(action.gate, item)
        d.apply_auto_gate(item, action.gate, rule)


def _print_action(action: Action, line: Line) -> None:
    # Distinct glyph for the blocked gate: it means a station hit the human_required
    # escape hatch (something went wrong), not a routine checkpoint like ship_review.
    icon = "⛔" if action.gate == "blocked" else _ICONS.get(action.type, "•")
    print(f"\n{icon} {action.item_id} @ {action.state}")
    if action.message:
        print(f"  {action.message}")
    if action.type == "run_station":
        print(f"  → run skill `{action.skill}` (subagent `{action.agent}`)")
        verdicts = " | ".join(line.valid_verdicts(action.state))
        print(f"  → then: factory advance {action.item_id} --verdict <{verdicts}>")
    elif action.type == "run_external":
        print(f"  → run CI/deploy, then: factory advance {action.item_id} --verdict <verdict>")
    elif action.type == "human_gate":
        verdicts = " | ".join(line.valid_verdicts(action.state))
        print(f"  → HUMAN NEEDED. Decide: factory gate {action.item_id} --decision <{verdicts}>")
    print(f"NEXT: {json.dumps(action.to_dict())}")


def cmd_init(args: argparse.Namespace) -> int:
    root = _root(args)
    for sub in ("work-items", "interventions", "metrics"):
        (root / ".factory" / sub).mkdir(parents=True, exist_ok=True)
    missing = [f for f in ("line.yml", "policies.yml") if not (root / f).exists()]
    if missing:
        print(f"⚠ missing config in {root}: {', '.join(missing)}")
        print("  Adopt the factory here with install/install.py first.")
        return 1
    Dispatcher(root)  # validates line.yml + policies.yml
    print(f"✓ factory initialized at {root}")
    print('  Create your first work item:  factory new "<title>"')
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    d = _disp(args)
    body = args.body or ""
    if args.body_file:
        body = Path(args.body_file).read_text()
    item = d.new_item(args.title, body=body, labels=args.label or [], risk=args.risk)
    print(f"✓ created {item.id}: {item.title}")
    _print_action(_resolve_next(d, item.id), d.line)
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    d = _disp(args)
    _print_action(_resolve_next(d, args.id), d.line)
    return 0


def cmd_advance(args: argparse.Namespace) -> int:
    d = _disp(args)
    item = d.store.load(args.id)
    if args.report:
        report = StationReport(**json.loads(Path(args.report).read_text()))
    else:
        if not args.verdict:
            print("✗ --verdict is required (or pass --report FILE)", file=sys.stderr)
            return 1
        spawn = []
        if args.spawn_title:
            spawn.append({"title": args.spawn_title, "body": args.spawn_body or ""})
        report = StationReport(
            station=item.state,
            verdict=args.verdict,
            summary=args.summary or "",
            artifacts=args.artifact or [],
            confidence=args.confidence or 0.0,
            cost=args.cost or 0.0,
            risk=args.risk,
            pr=args.pr,
            human_required=args.human_required,
            human_reason=args.human_reason or "",
            notes=args.note or "",
            spawn=spawn,
        )
    new_state = d.advance(item, report)
    print(f"✓ {item.id}: {report.station} → {new_state}  (verdict: {report.verdict})")
    _print_action(_resolve_next(d, item.id), d.line)
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    d = _disp(args)
    item = d.store.load(args.id)
    gate = d.line.gate_name(item.state) or item.state
    produced = ""
    if args.produced_file:
        produced = Path(args.produced_file).read_text()
    elif args.produced:
        produced = args.produced
    decision = GateDecision(
        gate=gate,
        decision=args.decision,
        by=_resolve_actor(args),
        changed=args.changed,
        notes=args.notes or "",
        expected=args.expected or "",
        category=args.category or "",
    )
    new_state = d.gate(item, decision, produced=produced)
    print(f"✓ {item.id}: gate {gate} → {new_state}  (decision: {args.decision})")
    _print_action(_resolve_next(d, item.id), d.line)
    return 0


def _render_board(d: Dispatcher) -> None:
    items = d.store.list_items()
    headline = d.line.north_star.splitlines()[0] if d.line.north_star else ""
    print(f"\n🏭 Factory board — {len(items)} work item(s)")
    if headline:
        print(f"   North Star: {headline}")
    by_state: dict[str, list] = {}
    for it in items:
        by_state.setdefault(it.state, []).append(it)
    for st in _STAGE_ORDER:
        group = by_state.get(st, [])
        if not group:
            continue
        kind = d.line.kind(st)
        tag = "✋" if kind == "human_gate" else ("✓" if kind == "terminal" else "▸")
        print(f"\n  {tag} {st} ({len(group)})")
        for it in group:
            meta = f"risk:{it.risk} steers:{it.steers} touches:{it.human_touches}"
            print(f"      {it.id}  {it.title}   [{meta}]")
    print()


def _render_item(d: Dispatcher, item_id: str) -> None:
    item = d.store.load(item_id)
    print(f"\n● {item.id}: {item.title}")
    print(
        f"  state: {item.state}   risk: {item.risk}   steers: {item.steers}   "
        f"human touches: {item.human_touches}   cost: {item.cost}"
    )
    if item.labels:
        print(f"  labels: {', '.join(item.labels)}")
    if item.artifacts:
        print(f"  artifacts: {', '.join(item.artifacts)}")
    if item.pr:
        print(f"  pr: {item.pr}")
    print("  history:")
    for ev in item.history:
        move = f"{ev.from_state}→{ev.to_state}" if ev.to_state else ev.kind
        print(f"    {ev.ts}  [{ev.actor}] {move} {ev.verdict or ''} {ev.note or ''}".rstrip())
    print()


def cmd_status(args: argparse.Namespace) -> int:
    d = _disp(args)
    if args.id:
        _render_item(d, args.id)
    else:
        _render_board(d)
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    s = _disp(args).metrics.summary()
    print("\n📈 Factory metrics — North Star: one-shot ship rate\n")
    print(
        f"  one-shot ship rate: {s['one_shot_ship_rate']:.0%}  "
        f"({s['one_shot_shipped']}/{s['shipped']} shipped with no rework)"
    )
    print(f"  human gate stops:   {s['human_gate_stops']}  (human present (expected))")
    print(f"  human steers:       {s['human_steers']}  (send-backs, corrections, unblocks)")
    print(f"  fully hands-off:    {s['hands_off_shipped']}/{s['shipped']}  (no human present)")
    print(f"  total cost:         {s['total_cost']}")
    print(f"  cost per shipped:   {s['cost_per_shipped']}")
    if s["steers_by_stage"]:
        print("\n  where humans had to step in (aim the learning here):")
        for stage, n in s["steers_by_stage"].items():
            print(f"    {stage}: {n}")
    print()
    return 0


def cmd_retro(args: argparse.Namespace) -> int:
    text = briefing(_root(args))
    if args.emit:
        Path(args.emit).write_text(text)
        print(f"✓ retro briefing written to {args.emit}")
    else:
        print(text)
    return 0


def cmd_labels(args: argparse.Namespace) -> int:
    import shutil
    import subprocess

    import yaml

    path = _root(args) / "labels.yml"
    if not path.exists():
        print(f"✗ no labels.yml at {path.parent}", file=sys.stderr)
        return 1
    labels = (yaml.safe_load(path.read_text()) or {}).get("labels", [])
    if not args.github:
        for lab in labels:
            print(f"  {lab['name']:<22} #{lab['color']}  {lab['description']}")
        print(f"\n{len(labels)} labels. Re-run with --github to create them in a repo via gh.")
        return 0
    if not shutil.which("gh"):
        print("✗ gh not found; install it or create the labels manually", file=sys.stderr)
        return 1
    for lab in labels:
        cmd = [
            "gh",
            "label",
            "create",
            lab["name"],
            "--color",
            lab["color"],
            "--description",
            lab["description"],
            "--force",
        ]
        if args.repo:
            cmd += ["--repo", args.repo]
        r = subprocess.run(cmd, capture_output=True, text=True)
        ok = r.returncode == 0
        print(f"{'✓' if ok else '✗'} {lab['name']}" + ("" if ok else f": {r.stderr.strip()}"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="factory", description="Personal software factory dispatcher.")
    p.add_argument("--root", default=".", help="factory root (holds line.yml and .factory/)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create .factory/ runtime dirs and validate config")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("new", help="create a work item")
    s.add_argument("title")
    s.add_argument("--body", default="")
    s.add_argument("--body-file")
    s.add_argument("--label", action="append")
    s.add_argument("--risk", default="unknown", choices=["low", "medium", "high", "unknown"])
    s.set_defaults(func=cmd_new)

    s = sub.add_parser("next", help="show the next action for a work item")
    s.add_argument("id")
    s.set_defaults(func=cmd_next)

    s = sub.add_parser("advance", help="record a station report and route the item")
    s.add_argument("id")
    s.add_argument("--verdict")
    s.add_argument("--summary")
    s.add_argument("--artifact", action="append")
    s.add_argument("--confidence", type=float)
    s.add_argument("--cost", type=float)
    s.add_argument("--risk")
    s.add_argument("--pr")
    s.add_argument("--note")
    s.add_argument("--human-required", action="store_true")
    s.add_argument("--human-reason")
    s.add_argument("--spawn-title")
    s.add_argument("--spawn-body")
    s.add_argument("--report", help="JSON file with a full StationReport")
    s.set_defaults(func=cmd_advance)

    s = sub.add_parser("gate", help="record a human decision at a gate")
    s.add_argument("id")
    s.add_argument("--decision", required=True)
    s.add_argument(
        "--by",
        help="who is deciding; defaults to $FACTORY_USER or your git identity",
    )
    s.add_argument("--changed", action="store_true", help="the human steered/edited something")
    s.add_argument("--notes")
    s.add_argument("--expected", help="what the human wanted the station to produce")
    s.add_argument("--category", help="intervention category, e.g. missing-edge-case")
    s.add_argument("--produced")
    s.add_argument("--produced-file")
    s.set_defaults(func=cmd_gate)

    s = sub.add_parser("status", help="show the board, or one item's history")
    s.add_argument("id", nargs="?")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("metrics", help="show the North Star ledger")
    s.set_defaults(func=cmd_metrics)

    s = sub.add_parser("retro", help="assemble a briefing for the learning station")
    s.add_argument("--emit", help="write the briefing to this file instead of stdout")
    s.set_defaults(func=cmd_retro)

    s = sub.add_parser("labels", help="list the factory labels, or create them in a repo (gh)")
    s.add_argument("--github", action="store_true", help="create the labels via the gh CLI")
    s.add_argument("--repo", help="target repo (owner/name) for --github")
    s.set_defaults(func=cmd_labels)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except Exception as e:  # noqa: BLE001 — CLI boundary: present errors, don't traceback
        print(f"✗ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
