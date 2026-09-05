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
import difflib
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

from . import brief as brief_mod
from . import sweep as sweep_mod
from .checklist import Checklist, ChecklistError
from .dispatch import Action, Dispatcher, GateDriftError, unreadable_tips
from .ledger import CLOSED, STATUSES, Ledger
from .line import Line
from .model import GateDecision, StationReport, WorkItem
from .policies import PolicyError
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


# --- shared plumbing --------------------------------------------------------
# Root/dispatcher resolution, actor identity, the auto-gate walker, and the
# NEXT: printer that every mutating command ends with.


def _root(args: argparse.Namespace) -> Path:
    return Path(args.root).resolve()


def _disp(args: argparse.Namespace) -> Dispatcher:
    return Dispatcher(_root(args))


def _resolve_actor(args: argparse.Namespace) -> str:
    """Who signs this mutation (gate / revive / correct) — a real, trackable
    identity, not a generic 'human'. Explicit --by wins; then $FACTORY_USER, the
    repo's git identity, the OS login. 'unknown' only if every source comes up
    empty. Every fallback names the human at the keyboard — which is why an agent
    acting for itself must pass --by explicitly, or it signs as the human."""
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
        rule = d.active_auto_rule(action.gate, item)
        d.apply_auto_gate(item, action.gate, rule)


def _mirror_issue_state(d: Dispatcher, item_id: str, prev_state: str | None) -> None:
    """Best-effort projection of the item's state onto its source issue's
    ``factory:<state>`` label. No-ops for local items and unchanged state (a fully
    local factory never touches ``gh``); a failed sync warns, never blocks the
    transition. ``prev_state`` is the label to replace — None for a new item."""
    item = d.store.load(item_id)
    if item.source != "github" or not item.source_ref or item.state == prev_state:
        return
    from .adapters import github

    if not github.available():
        return
    rc, msg = github.sync_label(item.source_ref, new_state=item.state, old_state=prev_state)
    if rc != 0:
        print(f"  ⚠ issue #{item.source_ref} label sync failed: {msg}", file=sys.stderr)


def _warn_unrecognized(d: Dispatcher, item: WorkItem) -> None:
    """Say so the moment a classifier lands outside the vocabulary. It is still
    recorded — we never drop input — but it satisfies no gate policy until a human
    promotes it, and whoever just coined it is best placed to judge that."""
    unknown = d.classifiers.unrecognized(item.classifiers)
    if not unknown:
        return
    print(
        f"ⓘ classifier(s) outside the vocabulary: {', '.join(unknown)} — recorded, but they "
        f"match no gate policy. Known: {', '.join(d.classifiers.names)}. Promote one by adding "
        "it to classifiers.yml.",
        file=sys.stderr,
    )


def _print_action(action: Action, line: Line) -> None:
    # Distinct glyph for the blocked gate: it means a station blocked itself (via its
    # routed `blocked` verdict or the human_required escape hatch — something only a
    # human can resolve), not a routine checkpoint like ship_review.
    icon = "⛔" if action.gate == "blocked" else _ICONS.get(action.type, "•")
    print(f"\n{icon} {action.item_id} @ {action.state}")
    if action.message:
        print(f"  {action.message}")
    if action.type == "run_station":
        print(f"  → run skill `{action.skill}` (subagent `{action.agent}`)")
        if action.checking:
            print("  → checking station: fresh context, no chat steering (see the brief)")
        if action.attempt and action.attempt > 1:
            rerun = f"  ↻ attempt {action.attempt}"
            if action.last_return:
                rerun += f" — routed back by: {action.last_return}"
            print(rerun)
        print(f"  → brief it: factory brief {action.item_id}")
        verdicts = " | ".join(line.valid_verdicts(action.state))
        print(f"  → then: factory advance {action.item_id} --verdict <{verdicts}>")
    elif action.type == "run_external":
        print(f"  → run CI/deploy, then: factory advance {action.item_id} --verdict <verdict>")
    elif action.type == "human_gate":
        verdicts = " | ".join(line.valid_verdicts(action.state))
        print(f"  → HUMAN NEEDED. Decide: factory gate {action.item_id} --decision <{verdicts}>")
    print(f"NEXT: {json.dumps(action.to_dict())}")


# --- init -------------------------------------------------------------------


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


# --- new: intake ------------------------------------------------------------


def _infer_source(source_ref: str | None) -> str | None:
    """The source a bare --source-ref implies: none means local, and only a numeric
    ref safely means GitHub. Anything else is a tracker key the engine won't guess
    at — None tells the caller to demand an explicit --source."""
    if not source_ref:
        return "local"
    return "github" if source_ref.lstrip("#").isdigit() else None


def cmd_new(args: argparse.Namespace) -> int:
    d = _disp(args)
    body = args.body or ""
    if args.body_file:
        body = Path(args.body_file).read_text()
    if args.parent and not d.store.exists(args.parent):
        # Reject a dangling lineage pointer at the boundary — a typo'd parent
        # would silently break the origin thread the retro later mines.
        print(f"✗ parent {args.parent!r} is not a known work item", file=sys.stderr)
        return 1
    source = args.source or _infer_source(args.source_ref)
    if source is None:
        # A Jira/Linear-shaped key recorded as a github mirror would silently
        # mislabel the item and fire doomed label syncs — name the tracker instead.
        print(
            f"✗ --source-ref {args.source_ref!r} is not a GitHub issue number — "
            "say which tracker it names (e.g. --source jira)",
            file=sys.stderr,
        )
        return 1
    item = d.new_item(
        args.title,
        body=body,
        classifiers=args.classifier or [],
        # Intake classifiers are the human's call: a station can't retract one,
        # only the human at a gate can.
        classifiers_by=f"human:{_resolve_actor(args)}",
        risk=args.risk,
        parent=args.parent,
        source=source,
        source_ref=args.source_ref,
    )
    print(f"✓ created {item.id}: {item.title}")
    _warn_unrecognized(d, item)
    if item.metadata.get("risk_floor"):
        matched = ", ".join(item.metadata.get("risk_floor_matches", []))
        print(
            f"  ⚠ risk floored to {item.risk} — touches {matched} "
            "(pass --risk explicitly to override at creation)"
        )
    action = _resolve_next(d, item.id)
    _mirror_issue_state(d, item.id, None)
    _print_action(action, d.line)
    return 0


# --- next -------------------------------------------------------------------


def cmd_next(args: argparse.Namespace) -> int:
    d = _disp(args)
    prev = d.store.load(args.id).state
    action = _resolve_next(d, args.id)
    _mirror_issue_state(d, args.id, prev)
    _print_action(action, d.line)
    return 0


# --- brief: the deterministic half of a station run's context ----------------


def cmd_brief(args: argparse.Namespace) -> int:
    d = _disp(args)
    action = _resolve_next(d, args.id)
    if action.type != "run_station":
        hint = (
            " At a human gate, present the review packet instead "
            "(templates/REVIEW-PACKET.md) and bind it with `factory gate --bind`."
            if action.type == "human_gate"
            else ""
        )
        print(
            f"✗ {args.id} is at {action.state!r} ({action.type}) — a brief is for a station "
            f"run.{hint}",
            file=sys.stderr,
        )
        return 1
    item = d.store.load(args.id)
    path = brief_mod.brief_path(d.root, item.id, action.state)
    existing = path.read_text() if path.exists() else ""
    marker = brief_mod.run_marker(action.attempt or 1)
    if marker in existing and not args.force:
        # Reuse, never clobber: the driver may already have appended session
        # context, and that half of the packet is not regenerable.
        print(existing, end="")
        print(f"→ existing brief reused: {path} (--force regenerates)", file=sys.stderr)
        return 0
    text = brief_mod.compose(d.root, d.line, item, action, classifiers=d.classifiers)
    if marker in existing:
        # --force regenerates *this* run's section and keeps the ones before it:
        # earlier attempts are the trace of what those workers were actually fed.
        head = existing.split(marker)[0].rstrip()
        text = (head + "\n\n---\n\n" + text) if head else text
        how = "regenerated"
    elif existing:
        text = existing.rstrip() + "\n\n---\n\n" + text
        how = f"appended (attempt {action.attempt})"
    else:
        how = "written"
    path.parent.mkdir(parents=True, exist_ok=True)
    brief_mod.scratchpad_dir(d.root, item.id).mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print(text, end="")
    print(f"→ brief {how}: {path}", file=sys.stderr)
    return 0


# --- feedback: what people said on the item's PRs ----------------------------


def cmd_feedback(args: argparse.Namespace) -> int:
    from . import feedback
    from .adapters import github

    d = _disp(args)
    item = d.store.load(args.id)
    numbers, bad_refs = feedback.pr_numbers(item)
    if not numbers and not bad_refs:
        print(f"{item.id} has no pull requests recorded — nothing to fetch.")
        return 0
    # A recorded ref that parses as nothing is a failure to report, never an
    # absence — otherwise a mangled ref reads as "no feedback".
    failures = [(ref, "recorded PR reference didn't parse") for ref in bad_refs]
    prs = []
    if numbers:
        if not github.available():
            print("✗ gh not found — reading PR feedback needs the GitHub CLI", file=sys.stderr)
            return 1
        rc, slug = feedback.repo_slug()
        if rc != 0 or "/" not in slug:
            print(f"✗ couldn't resolve this repo on GitHub: {slug}", file=sys.stderr)
            return 1
        for n in numbers:
            data, why = feedback.fetch_pr(slug, n)
            if data is None:
                failures.append((n, why))
            else:
                prs.append(data)
    print(feedback.render(item.id, prs, failures))
    if prs or not failures:
        return 0
    # Nothing could be read at all: that's an error, not an empty answer — a
    # station must not mistake "couldn't look" for "no feedback".
    print("✗ no PR could be fetched — feedback is unknown, not absent", file=sys.stderr)
    return 1


# --- advance: a station finished --------------------------------------------


def _confidence(value: str) -> float:
    """argparse type for --confidence: a float that must land in [0, 1]."""
    f = float(value)
    if not 0.0 <= f <= 1.0:
        raise argparse.ArgumentTypeError(f"must be between 0.0 and 1.0, got {value}")
    return f


def _inline_report_flags(args: argparse.Namespace) -> list[str]:
    """The inline advance flags the caller actually passed. Used to reject the
    --report + inline-flags combination instead of silently dropping the flags."""
    given = {
        "--verdict": args.verdict,
        "--summary": args.summary,
        "--artifact": args.artifact,
        "--confidence": args.confidence,
        "--cost": args.cost,
        "--risk": args.risk,
        "--branch": args.branch,
        "--pr": args.pr,
        "--change-branch": args.change_branch,
        "--change-pr": args.change_pr,
        "--classifier": args.classifier or None,
        "--retract": args.retract or None,
        "--notes": args.notes,
        "--human-required": args.human_required or None,
        "--human-reason": args.human_reason,
        "--spawn-title": args.spawn_title,
        "--spawn-body": args.spawn_body,
        "--ran": args.ran,
    }
    return [flag for flag, value in given.items() if value is not None]


def _paired_retractions(args: argparse.Namespace) -> list[tuple[str, str]] | None:
    """Zip --retract with --retract-reason, or print why they don't zip. Mispairing
    is easy on a repeatable flag and would otherwise attach a reason to the wrong
    classifier — so the counts must match exactly, and the check happens before any
    state is touched."""
    names = args.retract or []
    reasons = args.retract_reason or []
    if not names and not reasons:
        return []
    if len(names) != len(reasons):
        print(
            f"✗ --retract and --retract-reason must pair up: got {len(names)} name(s) and "
            f"{len(reasons)} reason(s). Repeat them together, one reason per name.",
            file=sys.stderr,
        )
        return None
    return list(zip(names, reasons, strict=True))


def cmd_advance(args: argparse.Namespace) -> int:
    d = _disp(args)
    item = d.store.load(args.id)
    prev = item.state
    if args.report:
        clashing = _inline_report_flags(args)
        if clashing:
            print(
                f"✗ --report replaces the inline flags; drop {', '.join(clashing)}",
                file=sys.stderr,
            )
            return 1
        data = json.loads(Path(args.report).read_text())
        station = data.setdefault("station", item.state)
        if station != item.state:
            print(
                f"✗ report claims station {station!r} but {item.id} is at {item.state!r}"
                " — stale report file?",
                file=sys.stderr,
            )
            return 1
        report = StationReport(**data)
    else:
        # Reject silently-dropped flag combinations before touching any state.
        if not args.verdict and not args.human_required:
            print(
                "✗ --verdict is required (or --human-required to escalate, or --report FILE)",
                file=sys.stderr,
            )
            return 1
        if args.human_reason and not args.human_required:
            print("✗ --human-reason only means something with --human-required", file=sys.stderr)
            return 1
        if args.spawn_body and not args.spawn_title:
            print("✗ --spawn-body needs --spawn-title to spawn anything", file=sys.stderr)
            return 1
        retractions = _paired_retractions(args)
        if retractions is None:
            return 1
        spawn = []
        if args.spawn_title:
            spawn.append({"title": args.spawn_title, "body": args.spawn_body or ""})
        report = StationReport(
            station=item.state,
            # The escape hatch bypasses routing, so no verdict is needed there;
            # dispatch logs the move as "blocked" regardless of what we put here.
            verdict=args.verdict or "blocked",
            summary=args.summary or "",
            artifacts=args.artifact or [],
            confidence=args.confidence or 0.0,
            cost=args.cost or 0.0,
            risk=args.risk,
            branch=args.branch,
            pr=args.pr,
            change_branch=args.change_branch,
            change_pr=args.change_pr,
            classifiers=args.classifier or [],
            retractions=retractions,
            human_required=args.human_required,
            human_reason=args.human_reason or "",
            notes=args.notes or "",
            spawn=spawn,
            ran=args.ran or "",
        )
    new_state = d.advance(item, report)
    print(f"✓ {item.id}: {report.station} → {new_state}  (verdict: {report.verdict})")
    for name, reason in report.retractions:
        print(f"  ↩ classifier {name!r} retracted: {reason}")
    _warn_unrecognized(d, item)
    action = _resolve_next(d, item.id)
    _mirror_issue_state(d, item.id, prev)
    _print_action(action, d.line)
    return 0


# --- gate: a human decided ---------------------------------------------------


def cmd_gate(args: argparse.Namespace) -> int:
    d = _disp(args)
    item = d.store.load(args.id)
    prev = item.state
    gate = d.line.gate_name(item.state) or item.state
    if args.bind:
        # --bind only binds; every decision-only flag is meaningless here — reject
        # rather than silently drop (the caller thought it did something).
        clashing = [
            flag
            for flag, value in (
                ("--decision", args.decision),
                ("--changed", args.changed or None),
                ("--notes", args.notes),
                ("--expected", args.expected),
                ("--category", args.category),
                ("--produced", args.produced),
                ("--produced-file", args.produced_file),
                ("--accept-drift", args.accept_drift or None),
                ("--retract", args.retract or None),
            )
            if value
        ]
        if clashing:
            print(
                f"✗ --bind only records what is being reviewed; {', '.join(clashing)} belong "
                "to the follow-up --decision call",
                file=sys.stderr,
            )
            return 1
        snap = d.bind_gate(item, by=_resolve_actor(args))
        print(
            f"✓ {item.id}: {snap['gate']} still waits on the human — the decision is now bound "
            f"to what is under review ({len(snap['artifacts'])} artifact(s), the item's PRs, "
            "and its branch tips)"
        )
        sys.stdout.flush()  # so the warnings below land after the ✓, not before it
        for gap in unreadable_tips(snap):
            print(
                f"⚠ couldn't read {gap} — the binding can't tell you if that branch moves",
                file=sys.stderr,
            )
        print(f"  decide with: factory gate {item.id} --decision <verdict> ...")
        return 0
    if not args.decision:
        print(
            "✗ --decision is required (or --bind to bind the review before deciding)",
            file=sys.stderr,
        )
        return 1
    retractions = _paired_retractions(args)
    if retractions is None:
        return 1
    decision = GateDecision(
        gate=gate,
        decision=args.decision,
        by=_resolve_actor(args),
        changed=args.changed,
        notes=args.notes or "",
        expected=args.expected or "",
        category=args.category or "",
    )
    if decision.is_steer and not decision.notes.strip():
        # Never block a human at a gate, but don't let the learning signal vanish
        # silently either: an intervention record without a why teaches the retro nothing.
        print(
            "⚠ steering with no --notes — the intervention record will carry no 'why', "
            "so the retro can't learn from it. Consider --notes / --expected / --category.",
            file=sys.stderr,
        )
    produced = ""
    if args.produced_file:
        produced = Path(args.produced_file).read_text()
    elif args.produced:
        produced = args.produced
    if not decision.is_steer and (decision.expected or decision.category or produced):
        # These fields only land in an intervention record, and a non-steer
        # decision doesn't write one — say so instead of dropping them silently.
        print(
            f"⚠ --expected/--category/--produced go into an intervention record, and a plain "
            f"{decision.decision!r} doesn't write one — add --changed if you steered the work.",
            file=sys.stderr,
        )
    # Read the vocabulary in use BEFORE the decision writes its own record, but
    # only report it after the gate actually took — a failed call shouldn't teach
    # anyone anything.
    known_categories: set[str] = set()
    if decision.is_steer and decision.category:
        known_categories = {
            c
            for r in d.interventions.records()
            if (c := r.get("category")) and c != "uncategorized"
        }
    # Filled in by gate(): things worth showing the human that must not block the
    # decision (a branch tip the binding couldn't read). Printed after the ✓.
    notices: list[str] = []
    try:
        new_state = d.gate(
            item,
            decision,
            produced=produced,
            accept_drift=args.accept_drift,
            retractions=retractions,
            notices=notices,
        )
    except GateDriftError as e:
        print(f"✗ {e}", file=sys.stderr)
        print(
            "  Re-review the changed content and re-bind (factory gate --bind ...), or pass "
            "--accept-drift to record the decision anyway (the drift is logged).",
            file=sys.stderr,
        )
        return 1
    print(f"✓ {item.id}: gate {gate} → {new_state}  (decision: {args.decision})")
    sys.stdout.flush()
    for notice in notices:
        print(f"⚠ {notice}", file=sys.stderr)
    for name, reason in retractions:
        print(f"  ↩ classifier {name!r} retracted: {reason}")
    if decision.category and decision.category not in known_categories:
        # The retro's recurrence check joins ledger rows to interventions on an
        # exact string, so a near-miss spelling breaks it silently. The vocabulary
        # is free-form on purpose — nothing to validate against — so surface what
        # is already in use at the one moment someone is choosing a word.
        print(
            f"ⓘ new category {decision.category!r} — already in use: "
            f"{', '.join(sorted(known_categories)) or '(none yet)'}",
            file=sys.stderr,
        )
    action = _resolve_next(d, item.id)
    _mirror_issue_state(d, item.id, prev)
    _print_action(action, d.line)
    return 0


# --- sweep: reclaim a finished item's scratch --------------------------------


def cmd_sweep(args: argparse.Namespace) -> int:
    d = _disp(args)
    if bool(args.id) == bool(args.all):
        print("✗ name one work item, or pass --all (not both, not neither)", file=sys.stderr)
        return 1
    ids = [args.id] if args.id else d.store.list_ids()
    swept = 0
    for iid in ids:
        item = d.store.load(iid)
        if not d.line.is_terminal(item.state):
            if args.id:  # explicit target: say why nothing happened
                print(
                    f"✗ {iid} is at {item.state!r}, not a terminal state — its scratch is "
                    "still in use. Sweep it once it's done or parked.",
                    file=sys.stderr,
                )
                return 1
            continue
        lines = sweep_mod.run(d.root, item, dry_run=args.dry_run)
        if lines:
            swept += 1
            print(f"\n{iid} ({item.state}):")
            for line in lines:
                print(f"  {line}")
    verb = "would reclaim" if args.dry_run else "reclaimed"
    print(f"\n{verb} scratch from {swept} item(s)." if swept else "\nNothing to sweep.")
    return 0


# --- intake: pull labeled GitHub issues onto the line -------------------------


def cmd_intake(args: argparse.Namespace) -> int:
    from .adapters import github

    d = _disp(args)
    if not github.available():
        print("✗ gh not found; the intake sensor needs the GitHub CLI", file=sys.stderr)
        return 1
    rc, issues, err = github.list_issues(args.label, repo=args.repo, limit=args.limit)
    if rc != 0:
        print(f"✗ gh issue list failed: {err}", file=sys.stderr)
        return 1
    where = f" in {args.repo}" if args.repo else ""
    if not issues:
        print(f"No open issues labeled {args.label!r}{where}.")
        return 0
    # Dedupe against the store, not issue labels: the mirror link (source_ref) is
    # the durable record of what's already on the line.
    known = {i.source_ref for i in d.store.list_items() if i.source == "github" and i.source_ref}
    new = [i for i in issues if str(i["number"]) not in known]
    skipped = len(issues) - len(new)
    if args.dry_run:
        for iss in new:
            print(f"would ingest: #{iss['number']} {iss['title']}")
        print(f"{len(new)} to ingest, {skipped} already on the line. Rerun without --dry-run.")
        return 0
    for iss in new:
        body = (iss.get("body") or "").strip()
        if iss.get("url"):
            # The mirror link in the body is what lets stations fetch the full
            # issue thread later (comments, attachments, discussion).
            body = (body + "\n\n" if body else "") + f"Mirrors: {iss['url']}"
        item = d.new_item(
            iss["title"],
            body=body,
            source="github",
            source_ref=str(iss["number"]),
        )
        line = f"✓ ingested #{iss['number']} → {item.id}: {item.title}"
        lrc, msg = github.sync_label(str(iss["number"]), new_state=item.state, repo=args.repo)
        if lrc != 0:
            # Best-effort mirror: the work item exists regardless; only the
            # issue-side breadcrumb failed, and silence would hide that.
            line += f"  (⚠ issue label sync failed: {msg})"
        print(line)
    print(f"\n{len(new)} ingested, {skipped} already on the line. Drive them with /factory.")
    return 0


# --- revive: bring a parked item back ----------------------------------------


def cmd_revive(args: argparse.Namespace) -> int:
    d = _disp(args)
    item = d.store.load(args.id)
    prev = item.state
    new_state = d.revive(
        item, by=_resolve_actor(args), resume=args.resume, notes=args.notes or ""
    )
    how = "resumed at" if args.resume else "re-entered at"
    print(f"✓ {item.id}: revived — {how} {new_state}")
    action = _resolve_next(d, item.id)
    _mirror_issue_state(d, item.id, prev)
    _print_action(action, d.line)
    return 0


# --- correct: admin fix for a mis-targeted advance/gate -----------------------


def cmd_correct(args: argparse.Namespace) -> int:
    d = _disp(args)
    item = d.store.load(args.id)
    old = item.state
    new_state = d.correct(item, args.state, by=_resolve_actor(args), reason=args.reason)
    print(f"✓ {item.id}: corrected {old} → {new_state}  (audited; the mistaken event stays)")
    action = _resolve_next(d, item.id)
    _mirror_issue_state(d, item.id, old)
    _print_action(action, d.line)
    return 0


# --- status / metrics / retro / labels: read-outs and setup ------------------


def _render_board(d: Dispatcher) -> None:
    items: list[WorkItem] = d.store.list_items()
    headline = d.line.north_star.splitlines()[0] if d.line.north_star else ""
    print(f"\n🏭 Factory board — {len(items)} work item(s)")
    if headline:
        print(f"   North Star: {headline}")
    by_state: dict[str, list[WorkItem]] = {}
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
            meta = f"risk:{it.risk} steers:{it.steers} human touches:{it.human_touches}"
            print(f"      {it.id}  {it.title}   [{meta}]")
    print()


def _render_item(d: Dispatcher, item_id: str) -> None:
    item = d.store.load(item_id)
    print(f"\n● {item.id}: {item.title}")
    print(
        f"  state: {item.state}   risk: {item.risk}   steers: {item.steers}   "
        f"human touches: {item.human_touches}   cost: {item.cost}"
    )
    runs = sum(item.attempts.values())
    if runs:
        per_state = ", ".join(f"{st} ×{n}" for st, n in item.attempts.items())
        print(f"  station runs: {runs}  ({per_state})")
    if item.classifiers:
        print(f"  classifiers: {d.classifiers.mark(item.classifiers)}")
    # Provenance and retractions: who classified this item, and what a station or
    # the human took back off — the record that decides who may correct what.
    retracted = [e for e in item.classifier_log if e.action == "retract"]
    if item.classifier_log:
        print("  classifier log:")
        for name in item.classifiers:
            print(f"    + {name}  (by {item.provenance(name)})")
        for e in retracted:
            print(f"    − {e.name}  (retracted by {e.by}: {e.reason})")
    if item.parent:
        print(f"  parent: {item.parent}")
    if item.source_ref:
        print(f"  source: {item.source} {item.source_ref}")
    if item.artifacts:
        print(f"  artifacts: {', '.join(item.artifacts)}")
    # The line the ship-gate packet leads with. An unparseable checklist says so
    # rather than reading as an item that has none.
    chk = Checklist.find(d.root, item.artifacts)
    if chk:
        try:
            print(f"  checklist: {Checklist.load(chk).headline()}")
        except ChecklistError as e:
            print(f"  checklist: ⚠ unreadable — {e}")
    if item.branch:
        print(f"  branch: {item.branch}" + (f"  →  pr: {item.pr}" if item.pr else ""))
    if item.change_branch:
        print(
            f"  change branch: {item.change_branch}"
            + (f"  →  pr: {item.change_pr}" if item.change_pr else "")
            + (f"  (pass {len(item.change_passes)})" if len(item.change_passes) > 1 else "")
        )
        # Superseded passes stay on the record: their PRs are where the review of
        # each earlier attempt happened, and a merged one is history you can't
        # reconstruct from the branch that's live now.
        for n, p in enumerate(item.change_passes[:-1], start=1):
            print(f"    pass {n}: {p.branch or '(no branch)'}" + (f"  →  {p.pr}" if p.pr else ""))
    # What each run was fed. Briefs are scratch and vanish when the item finishes.
    home = d.store.dir / item.id
    traces = sorted(home.glob("runs/*-brief.md"))
    if traces:
        print("  run traces:")
        for t in traces:
            print(f"    {t.relative_to(d.store.root)}")
    print("  history:")
    for ev in item.history:
        move = f"{ev.from_state}→{ev.to_state}" if ev.to_state else ev.kind
        ran = f" [{ev.ran}]" if ev.ran else ""
        print(f"    {ev.ts}  [{ev.actor}]{ran} {move} {ev.verdict or ''} {ev.note or ''}".rstrip())
    print()


def cmd_status(args: argparse.Namespace) -> int:
    d = _disp(args)
    if args.id:
        _render_item(d, args.id)
    else:
        _render_board(d)
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    m = _disp(args).metrics
    s = m.summary()
    for w in m.warnings:
        print(f"⚠ metrics ledger: {w}", file=sys.stderr)
    print("\n📈 Factory metrics — North Star: one-shot ship rate\n")
    print(
        f"  one-shot ship rate: {s['one_shot_ship_rate']:.0%}  "
        f"({s['one_shot_shipped']}/{s['shipped']} shipped with no rework)"
    )
    t = s["trend"]
    if t["prior_ships"]:
        # Only meaningful once there's a prior window to compare against; before
        # that, the cumulative rate above is the whole story.
        print(
            f"  trend:              last {t['recent_ships']} ships "
            f"{t['recent_one_shot_rate']:.0%} one-shot vs prior {t['prior_ships']} "
            f"{t['prior_one_shot_rate']:.0%}"
        )
    print(f"  human gate stops:   {s['human_gate_stops']}  (human present (expected))")
    print(f"  human steers:       {s['human_steers']}  (send-backs, corrections, unblocks)")
    print(f"  fully hands-off:    {s['hands_off_shipped']}/{s['shipped']}  (no human present)")
    print(f"  station runs:       {s['station_runs']}  (cost proxy — one run, one agent)")
    print(f"  runs per shipped:   {s['runs_per_shipped']}  (the line's minimum path is 6)")
    print(f"  total cost:         {s['total_cost']}  (self-reported by stations via --cost)")
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


def _print_ledger_entry(e: dict) -> None:
    open_marker = "" if (e["status"] in CLOSED or e.get("outcome")) else " open"
    print(f"  {e['id']}  [{e['status']}{open_marker}]  {e['title']}")
    print(f"        lever: {e['lever']}   date: {e['date']}")
    if e.get("pr"):
        print(f"        pr: {e['pr']}")
    if e.get("outcome"):
        print(f"        outcome: {e['outcome']}")


def cmd_ledger(args: argparse.Namespace) -> int:
    led = Ledger(_root(args))
    if args.ledger_cmd == "add":
        e = led.add(
            title=args.title,
            lever=args.lever,
            signal=args.signal,
            files=args.file or [],
            answers=args.answers or [],
            pr=args.pr or "",
            status=args.status,
            category=args.category or "",
        )
        print(f"✓ recorded {e['id']}: {e['title']}")
        print(f"  rendered: {led.view}")
        return 0
    if args.ledger_cmd == "update":
        e = led.update(args.id, status=args.status, outcome=args.outcome, pr=args.pr)
        print(f"✓ {e['id']} → status: {e['status']}" + (", outcome noted" if args.outcome else ""))
        print(f"  rendered: {led.view}")
        return 0
    # list
    entries = led.open_entries() if args.open else led.entries()
    if args.status_filter:
        entries = [e for e in entries if e["status"] == args.status_filter]
    if not entries:
        print("(no ledger rows match)")
    for e in entries:
        _print_ledger_entry(e)
    for w in led.warnings:
        print(f"⚠ {w}", file=sys.stderr)
    return 0


def cmd_policy(args: argparse.Namespace) -> int:
    d = _disp(args)
    if args.policy_cmd == "list":
        suspended = d.policy_state.suspended()
        if not d.policies.rules and not suspended:
            print("(no gate policies defined — policies.yml has no rules)")
            return 0
        for rule in d.policies.rules:
            rid = rule["id"]
            if rid in suspended:
                s = suspended[rid]
                status = f"SUSPENDED since {s['ts']} — {s['item']}: {s['why']}"
            elif rule.get("approved_by"):
                status = f"active (signed by {rule['approved_by']})"
            else:
                status = "dormant (unsigned)"
            print(f"  {rid}  [{status}]")
            print(f"        gate: {rule['gate']}  decision: {rule['decision']}")
        # A suspension whose rule vanished from policies.yml would otherwise be
        # invisible — surface it rather than let the overlay rot silently.
        for rid in suspended:
            if not any(r.get("id") == rid for r in d.policies.rules):
                print(f"  {rid}  [SUSPENDED, but no longer in policies.yml — stale overlay "
                      f"entry; reinstate to clear it]")
        return 0
    # reinstate
    try:
        d.policy_state.reinstate(args.rule_id, by=_resolve_actor(args), notes=args.notes or "")
    except PolicyError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    print(f"✓ policy {args.rule_id!r} reinstated — it may auto-clear its gate again")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Cross-check the factory's stores against each other and the config —
    'is my factory consistent?' as one command. Read-only."""
    from .classifiers import Classifiers
    from .interventions import Interventions
    from .metrics import Metrics
    from .policies import Policies, PolicyState
    from .store import Store

    root = _root(args)
    errors: list[str] = []
    warns: list[str] = []

    # The broad excepts below buy continuation, not survival — main() already
    # catches at the boundary. One broken store must not hide the other checks.
    line = None
    try:
        line = Line.load(root / "line.yml")
        print("✓ line.yml loads and validates")
    except Exception as e:  # noqa: BLE001
        errors.append(f"line.yml: {e}")
    policies = None
    try:
        policies = Policies.load(root / "policies.yml")
        print(f"✓ policies.yml loads and validates ({len(policies.rules)} rule(s))")
    except Exception as e:  # noqa: BLE001
        errors.append(f"policies.yml: {e}")

    store = Store(root)
    # Lineage resolves against what's on disk, not what parsed — an unreadable
    # item is one error, not also a "broken lineage" warning on every child.
    known_ids = set(store.list_ids())
    items = {}
    for iid in known_ids:
        try:
            items[iid] = store.load(iid)
        except Exception as e:  # noqa: BLE001
            errors.append(f"work item {iid}: unreadable ({e})")
    print(f"✓ {len(items)} work item(s) parse")
    # Staging files are named `.<item>.json.<unique>.tmp`, so the dot-prefixed
    # glob is the one that matches; the bare one still catches pre-0.6.2 leftovers.
    leftovers = (
        sorted({*store.dir.glob("*.tmp"), *store.dir.glob(".*.tmp")}) if store.dir.exists() else []
    )
    for leftover in leftovers:
        warns.append(f"leftover temp file in the store: {leftover.name} (crashed save?)")
    for iid, item in sorted(items.items()):
        if item.id != iid:
            # Every save would write to a different file than the one it read.
            errors.append(f"{iid}: file holds id {item.id!r} — filename and id disagree")
        if line and item.state not in line.states:
            errors.append(f"{iid}: state {item.state!r} is not on the line")
        if item.parent and item.parent not in known_ids:
            warns.append(f"{iid}: parent {item.parent!r} does not exist (broken lineage)")
        if item.metadata.get("gate_binding") and line and not line.is_gate(item.state):
            warns.append(
                f"{iid}: has a gate binding but sits at {item.state!r} (not a gate) — "
                "stale; the next gate decision at that gate would clear it"
            )
        for art in item.artifacts:
            # Nothing else catches this: _hash_file maps a missing file to the
            # string "missing", which then matches itself between bind and decide.
            if not (root / art).is_file():
                warns.append(
                    f"{iid}: artifact {art!r} does not exist (state {item.state}) — "
                    "a station told to read it gets nothing, and a gate binding "
                    "over it detects no drift"
                )

    if policies:
        suspended = PolicyState(root).suspended()
        for rid in suspended:
            if not any(r.get("id") == rid for r in policies.rules):
                warns.append(
                    f"policy overlay: suspended rule {rid!r} no longer exists in policies.yml"
                )
        # A rule keyed on a classifier outside the vocabulary is well-formed and
        # can never fire — the one failure this pair has that nothing else reports.
        for rid, name in policies.unrecognized_conditions():
            near = difflib.get_close_matches(name, policies.classifiers.names, n=1)
            warns.append(
                f"policy {rid!r} matches on {name!r}, which is not in classifiers.yml — "
                "the rule can never fire"
                + (f" (did you mean {near[0]!r}?)" if near else "")
            )

    # Classifiers in use that the vocabulary doesn't know: recorded on purpose,
    # inert for policy, and this is where near-duplicate drift becomes visible.
    vocab = Classifiers.load(root / "classifiers.yml")
    where = "classifiers.yml" if vocab.path and vocab.path.exists() else "the built-in seed"
    print(f"✓ {len(vocab.names)} classifier(s) loaded from {where}")
    in_use: dict[str, list[str]] = {}
    for iid, item in sorted(items.items()):
        for name in vocab.unrecognized(item.classifiers):
            in_use.setdefault(name, []).append(iid)
    for name, ids in sorted(in_use.items()):
        warns.append(
            f"classifier {name!r} is on {', '.join(ids)} but not in classifiers.yml — "
            "recorded, and it satisfies no gate policy until someone promotes it"
        )

    metrics = Metrics(root)
    metrics.events()
    warns += [f"metrics ledger: {w}" for w in metrics.warnings]
    led = Ledger(root)
    entries = led.entries()
    warns += [f"retro ledger: {w}" for w in led.warnings]
    interventions = Interventions(root)
    records = interventions.records()
    n_iv = len(records)
    # `factory gate` nudges when a steer coins a new category; nothing nudges the
    # ledger side, so a near-miss spelling only ever surfaces here.
    in_use = {c for r in records if (c := r.get("category")) and c != "uncategorized"}
    for e in entries:
        cat = e.get("category")
        if cat and cat not in in_use:
            near = difflib.get_close_matches(cat, sorted(in_use), n=1)
            warns.append(
                f"retro ledger: {e['id']} category {cat!r} matches no intervention record"
                + (f" — did you mean {near[0]!r}?" if near else "")
                + " (the recurrence check joins on this exact string)"
            )
    lost = [r for r in records if r.get("malformed")]
    for r in lost:
        warns.append(
            f"intervention {r['path'].name}: no readable machine block — it still "
            "counts as a steer, but drops out of every category join"
        )
    print(f"✓ metrics/ledger read; {n_iv} intervention record(s)")

    import shutil as _shutil

    print(f"· gh CLI: {'found' if _shutil.which('gh') else 'not found (intake needs it)'}")

    for w in warns:
        print(f"⚠ {w}")
    for e in errors:
        print(f"✗ {e}", file=sys.stderr)
    print(f"\n{len(errors)} error(s), {len(warns)} warning(s)")
    return 1 if errors else 0


def cmd_github_labels(args: argparse.Namespace) -> int:
    import shutil
    import subprocess

    import yaml

    # Reject a silently-dropped flag before doing any work: --repo only ever
    # reaches `gh label create`, which never runs without --github.
    if args.repo and not args.github:
        print("✗ --repo only means something with --github", file=sys.stderr)
        return 1

    path = _root(args) / "github-labels.yml"
    if not path.exists():
        print(f"✗ no github-labels.yml at {path.parent}", file=sys.stderr)
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


# --- the grammar --------------------------------------------------------------
# Help text here is the CLI's source-of-truth documentation: it's the one surface
# both the human and the driving agent can query at runtime (factory <cmd> -h),
# and it can't drift from the actual grammar the way markdown can. The .claude/
# recipes stay thin pointers; the flags document themselves.


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="factory", description="Software factory dispatcher.")
    p.add_argument("--root", default=".", help="Factory root (holds line.yml and .factory/)")
    sub = p.add_subparsers(dest="cmd", required=True)

    # -- init --
    s = sub.add_parser("init", help="Create .factory/ runtime dirs and validate config")
    s.set_defaults(func=cmd_init)

    # -- new --
    s = sub.add_parser(
        "new",
        help="Create a work item (enters the line at triage)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  factory new "Add rate limiting to the quotes API"\n'
            '  factory new "Fix flaky auth test" --body "Fails ~1 in 5 runs on CI." \\\n'
            "      --classifier bug --classifier test --risk low\n"
            '  factory new "Migrate DB to Postgres 17" --body-file request.md --risk high\n'
            '  factory new "Fix regression in CSV export" --parent WI-0007 --classifier bug\n'
            "\n"
            "Keep the thread: when new work traces back to an earlier item (a regression from a\n"
            "shipped change, a follow-on), --parent records the lineage — that link is how a\n"
            "retro can connect a shipped item to the bug it later caused."
        ),
    )
    s.add_argument("title", help="One-line summary; becomes the item's title on the board")
    body_src = s.add_mutually_exclusive_group()
    body_src.add_argument(
        "--body", default="", help="Longer description (context, acceptance criteria)"
    )
    body_src.add_argument(
        "--body-file", metavar="FILE", help="Read the description from FILE instead of --body"
    )
    s.add_argument(
        "--classifier",
        action="append",
        metavar="NAME",
        help="Classify the item; repeat the flag for more (--classifier bug --classifier "
        "security). Not comma-separated. These are what gate policies match on — the "
        "vocabulary is classifiers.yml; GitHub's own labels are a separate thing.",
    )
    s.add_argument(
        "--risk",
        default="unknown",
        choices=["low", "medium", "high", "unknown"],
        help="Initial estimated risk level; triage may revise it (default: %(default)s)",
    )
    s.add_argument(
        "--parent",
        metavar="WI-ID",
        help="The earlier work item this one traces back to (a regression's origin, a "
        "follow-on's feature) — keeps the lineage the retro station mines",
    )
    s.add_argument(
        "--source-ref",
        metavar="REF",
        help="Tracker reference this item mirrors — a bare issue number implies "
        "--source github; any other key (e.g. a Jira AMPS-94) needs an explicit --source",
    )
    s.add_argument(
        "--source",
        help="Tracker the item came from: local (default), github, jira, … — free-form; "
        "only 'github' has an adapter today (issue label sync)",
    )
    s.set_defaults(func=cmd_new)

    # -- next --
    s = sub.add_parser("next", help="Show the next action for a work item")
    s.add_argument("id", help="Work item id (WI-####)")
    s.set_defaults(func=cmd_next)

    # -- advance --
    s = sub.add_parser(
        "advance",
        help="Record a station's report and route the item on its verdict",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  factory advance WI-0007 --verdict ready_for_review --summary "spec written" \\\n'
            "      --artifact specs/WI-0007-csv-export/PRODUCT.md \\\n"
            "      --branch feature/WI-0007-csv-export --pr 41 --confidence 0.85\n"
            '  factory advance WI-0007 --verdict implemented --summary "built it" \\\n'
            "      --change-branch change/WI-0007-csv-export-1 --change-pr 42\n"
            "  factory advance WI-0007 --verdict automatable --risk low --classifier chore\n"
            "  factory advance WI-0007 --verdict ready_for_review \\\n"
            '      --retract bug --retract-reason "reproduced as a config error, not a defect"\n'
            '  factory advance WI-0007 --human-required --human-reason "touches auth tables"\n'
            "  factory advance WI-0007 --report /tmp/report.json\n"
            "\n"
            "Valid verdicts depend on the item's current state — `factory next <id>` prints\n"
            "them. --branch/--pr name the item\'s own branch and its PR into the integration\n"
            "branch (set once, by the station that opens them); --change-branch/--change-pr\n"
            "name the implementation pass in flight and turn over with each new pass."
        ),
    )
    s.add_argument("id", help="Work item id (WI-####)")
    s.add_argument(
        "--verdict",
        help="Routing verdict, as specified by the station skill's output contract; "
        "`factory next <id>` lists the valid set for the current state",
    )
    s.add_argument("--summary", help="One line on what the station did (lands in item history)")
    s.add_argument(
        "--artifact",
        action="append",
        metavar="PATH",
        help="A file the station produced; repeat the flag for more. Not comma-separated.",
    )
    s.add_argument(
        "--confidence",
        type=_confidence,
        metavar="0..1",
        help="Station's self-assessed confidence in its verdict, 0.0-1.0",
    )
    s.add_argument("--cost", type=float, help="Cost of this station run (adds to the item total)")
    s.add_argument(
        "--risk",
        choices=["low", "medium", "high", "unknown"],
        help="Revised risk, if the station learned something (policies match on this)",
    )
    s.add_argument(
        "--pr",
        help="PR URL or number for the item's own pull request — the feature branch's PR into "
        "the integration branch, opened once and reviewed at the ship gate",
    )
    s.add_argument(
        "--branch",
        help="The item's feature branch — feature/<TICKET-KEY>__<slug> when it mirrors a tracker "
        "issue (feature/AMPS-91__session-leak), else feature/<id>-<slug>. Everything the "
        "item produces lands here. Set once, by the station that creates it",
    )
    s.add_argument(
        "--change-branch",
        help="The branch this implementation pass is on, cut from --branch, same naming with a "
        "pass number (change/AMPS-91__session-leak-2). Turns over on each new pass",
    )
    s.add_argument(
        "--change-pr",
        help="PR for this implementation pass — the change branch's PR into the feature "
        "branch. Turns over with --change-branch",
    )
    s.add_argument(
        "--classifier",
        action="append",
        metavar="NAME",
        help="Classify the item; repeat for more (--classifier refactor --classifier docs). "
        "Idempotent. Gate policies match on these (`classifiers_any` / `classifiers_all`), and "
        "only names in classifiers.yml satisfy one — anything else is still recorded, just "
        "marked and inert until a human promotes it.",
    )
    s.add_argument(
        "--retract",
        action="append",
        metavar="NAME",
        help="Retract a classification this station disproved; pair each with a "
        "--retract-reason and repeat for more. A station may only retract what a station "
        "applied — a human's classification is refused, and the refusal takes the whole "
        "advance with it. Nothing is erased: the log keeps the original application and the "
        "retraction side by side.",
    )
    s.add_argument(
        "--retract-reason",
        action="append",
        metavar="TEXT",
        help="Why that classification was wrong — required, one per --retract, in order",
    )
    s.add_argument(
        "--notes",
        help="Free-form station notes for whoever reads the item next (kept in its history)",
    )
    s.add_argument(
        "--human-required",
        action="store_true",
        help="Pull the escape hatch: send the item straight to `blocked` for a human, "
        "bypassing routing (--verdict is then optional). Stations whose routing has a "
        "`blocked` verdict (spec, implement) should prefer `--verdict blocked` instead; "
        "both count as a human step-in",
    )
    s.add_argument("--human-reason", help="Why a human is needed (requires --human-required)")
    s.add_argument("--spawn-title", help="File a follow-up work item; it enters the line at triage")
    s.add_argument("--spawn-body", help="Body for the spawned item (requires --spawn-title)")
    s.add_argument(
        "--ran",
        choices=["inline", "subagent", "resumed", "cloud"],
        help="How this station run executed (trace metadata on the history event): a fresh "
        "subagent, inline in the driver session, a resumed subagent, or a cloud run",
    )
    s.add_argument(
        "--report",
        metavar="FILE",
        help="JSON file with a full StationReport; replaces ALL inline flags above",
    )
    s.set_defaults(func=cmd_advance)

    # -- brief --
    s = sub.add_parser(
        "brief",
        help="Write + print the deterministic context brief for an item's next station run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  factory brief WI-0007\n"
            "  factory brief WI-0007 --force\n"
            "\n"
            "Writes .factory/work-items/<id>/runs/<state>-brief.md — the engine-owned half of\n"
            "the station's context packet (identity, risk, lineage, the request, artifact\n"
            "pointers, what routed it here) — and prints it to stdout. The driver appends\n"
            "session-only context under the marked section, then passes the file's content to\n"
            "the station verbatim.\n"
            "\n"
            "One file per station state, not per attempt: a retry appends its own section, so\n"
            "the state's whole run history reads as one document and a retrying station sees\n"
            "what its predecessor was told. This run's brief is reused if it already exists\n"
            "(--force regenerates just this run's section, keeping the earlier ones). It also\n"
            "creates runs/scratchpad/ — the station's working area, swept when the item ends."
        ),
    )
    s.add_argument("id", help="Work item id (WI-####)")
    s.add_argument(
        "--force",
        action="store_true",
        help="Regenerate this run's section even if it exists (discards any driver-added "
        "context in it; earlier attempts' sections are kept)",
    )
    s.set_defaults(func=cmd_brief)

    # -- feedback --
    s = sub.add_parser(
        "feedback",
        help="Print an item's PR feedback: unresolved review threads, review summaries, and "
        "conversation comments, verbatim (machine posts labeled)",
    )
    s.add_argument("id", help="Work item id (WI-####)")
    s.set_defaults(func=cmd_feedback)

    # -- sweep --
    s = sub.add_parser(
        "sweep",
        help="Reclaim a finished item's scratch (briefs, scratchpad, undecided gate renders)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  factory sweep WI-0007 --dry-run\n"
            "  factory sweep WI-0007\n"
            "  factory sweep --all\n"
            "\n"
            "The factory writes two kinds of file. Memory is what nothing else holds: the\n"
            "specs, the checklist, the records of what you decided.\n"
            "Scratch is what the engine can rebuild: the per-run briefs (regenerate with\n"
            "`factory brief`) and a station's scratchpad. This removes the second kind.\n"
            "\n"
            "It runs automatically when an item reaches a terminal state, so you mostly won't\n"
            "type it — it's here for items that predate it and for a manual pass. Two rules\n"
            "make it safe: a file survives because the item REGISTERED it as an artifact (not\n"
            "because of where it sits or what it's called), and a path that resolves outside\n"
            "the item's own directory is refused. --all sweeps every terminal item; an item\n"
            "still on the line is skipped, since its scratch is still in use."
        ),
    )
    s.add_argument("id", nargs="?", help="Work item id; omit with --all")
    s.add_argument(
        "--all", action="store_true", help="Sweep every item at a terminal state (done, parked)"
    )
    s.add_argument(
        "--dry-run", action="store_true", help="List what would be removed; remove nothing"
    )
    s.set_defaults(func=cmd_sweep)

    # -- gate --
    s = sub.add_parser(
        "gate",
        help="Record a human decision at a gate (a steer also writes an intervention record)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  factory gate WI-0007 --bind\n"
            "  factory gate WI-0007 --decision approved\n"
            "  factory gate WI-0007 --decision needs_revision --category missing-edge-case \\\n"
            '      --notes "public write endpoints must always specify input validation" \\\n'
            '      --expected "a validation + rejection-behavior section in the spec"\n'
            '  factory gate WI-0007 --decision approved --changed --notes "tightened rollout"\n'
            "  factory gate WI-0007 --decision approved \\\n"
            '      --retract bug --retract-reason "it was a feature request all along"\n'
            '  factory gate WI-0007 --decision recheck --notes "granted staging access"\n'
            "\n"
            "Valid decisions depend on the gate — `factory next <id>` prints them.\n"
            "Binding and deciding are two separate calls, in that order. --bind records what\n"
            "is being reviewed — the item's artifact files and its PR pointers, content-hashed\n"
            "— and changes nothing about the gate: it still waits on the human. Their answer\n"
            "comes back as a second call, --decision. If any bound content changed in between,\n"
            "that decision is refused with a list of what moved; re-review and re-bind, or\n"
            "--accept-drift to record anyway (logged, and the human's call to make). A decision\n"
            "with no prior --bind still works — it just isn't drift-checked.\n"
            "A steering decision (needs_revision / not_ready / recheck / park) or --changed\n"
            "writes an intervention record: give it a generalizable --notes — that's what the\n"
            "retro station learns from."
        ),
    )
    s.add_argument("id", help="Work item id (WI-####)")
    s.add_argument(
        "--bind",
        action="store_true",
        help="Record what is being reviewed (content-hash the item's artifacts and PR "
        "pointers) instead of deciding now — the follow-up --decision is then refused if "
        "any of it moved in between",
    )
    s.add_argument(
        "--decision",
        help="The gate verdict; `factory next <id>` lists the valid set for this gate",
    )
    s.add_argument(
        "--accept-drift",
        action="store_true",
        help="Record the decision even though bound content changed since --bind "
        "(the drift is logged in the item history)",
    )
    s.add_argument(
        "--by",
        help="Who is deciding; defaults to $FACTORY_USER or your git identity",
    )
    s.add_argument(
        "--changed",
        action="store_true",
        help="The human changed the work at the gate — by hand or by directing their agent — "
        "instead of sending it back (records an intervention even on approval)",
    )
    s.add_argument(
        "--notes",
        help="The generalizable WHY behind the decision — the learning loop's highest-value input",
    )
    s.add_argument("--expected", help="What the human wanted the station to produce")
    s.add_argument("--category", help="Intervention category, e.g. missing-edge-case, wrong-scope")
    s.add_argument(
        "--retract",
        action="append",
        metavar="NAME",
        help="Retract a classifier as part of this decision; pair each with a "
        "--retract-reason and repeat for more. Unlike a station's, this retraction is "
        "unrestricted — it takes off a classifier whoever applied it. The log keeps both "
        "entries.",
    )
    s.add_argument(
        "--retract-reason",
        action="append",
        metavar="TEXT",
        help="Why that classification was wrong — required, one per --retract, in order",
    )
    produced_src = s.add_mutually_exclusive_group()
    produced_src.add_argument(
        "--produced", help="What the station produced (inline text), embedded in the record"
    )
    produced_src.add_argument(
        "--produced-file",
        metavar="FILE",
        help="Read the produced artifact from FILE instead of --produced",
    )
    s.set_defaults(func=cmd_gate)

    # -- intake --
    s = sub.add_parser(
        "intake",
        help="Ingest open GitHub issues labeled for the factory as new work items (needs gh)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  factory intake --dry-run\n"
            "  factory intake\n"
            "  factory intake --label factory-inbox --repo owner/name\n"
            "\n"
            "The intake sensor: GitHub issues become the factory's inbox. Label an issue\n"
            "`intake` (created by `factory github-labels --github`), run this, and each\n"
            "labeled issue becomes a work item at the top of the line — title and body\n"
            "carried over, the mirror link recorded (source_ref), and the issue marked with\n"
            "the factory:<state>\n"
            "conveyor label (best-effort). Idempotent: issues already on the line (matched by\n"
            "source_ref) are skipped, so it's safe on a schedule — e.g. /loop or cron locally,\n"
            "or an `issues: opened` workflow calling it in cloud mode. It touches nothing on\n"
            "the line itself; items enter at the start state like any `factory new`."
        ),
    )
    s.add_argument(
        "--label",
        default="intake",
        help="GitHub label that marks an issue as factory inbox (default: %(default)s)",
    )
    s.add_argument("--repo", help="Target repo (owner/name); defaults to the current dir's repo")
    s.add_argument("--limit", type=int, default=50, help="Max issues to fetch (default: 50)")
    s.add_argument(
        "--dry-run", action="store_true", help="List what would be ingested; create nothing"
    )
    s.set_defaults(func=cmd_intake)

    # -- revive --
    s = sub.add_parser(
        "revive",
        help="Bring a parked item back onto the line (default: re-enter at the top, triage)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  factory revive WI-0007\n"
            '  factory revive WI-0007 --resume --notes "spec still holds; priorities flipped"\n'
            "\n"
            "Default re-entry is triage — the safe path, since the codebase and priorities may\n"
            "have moved while the item sat parked. --resume re-enters at the state it was parked\n"
            "from (recorded at park time) — use it when you know the shelved context is still\n"
            "fresh. If no pre-park state was recorded, --resume fails loudly; rerun without it."
        ),
    )
    s.add_argument("id", help="Work item id (WI-####)")
    s.add_argument(
        "--resume",
        action="store_true",
        help="Re-enter at the recorded pre-park state instead of triage (context still fresh)",
    )
    s.add_argument("--notes", help="Why it's coming back (lands in the item history)")
    s.add_argument(
        "--by",
        help="Who is reviving; defaults to $FACTORY_USER or your git identity. An agent "
        "acting for itself signs with its own name (e.g. driver:claude)",
    )
    s.set_defaults(func=cmd_revive)

    # -- correct --
    s = sub.add_parser(
        "correct",
        help="Admin: set an item's state after a mis-targeted advance/gate (audited, not an undo)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  factory correct WI-0007 --state implement \\\n"
            '      --reason "advanced WI-0007 instead of WI-0008"\n'
            "\n"
            "Use when a verdict landed on the wrong item and happened to be valid from its state,\n"
            "so it routed. This sets the state back in one recorded move and logs a `correction`\n"
            "event under your identity. It is not an undo: the mistaken event stays in history\n"
            "(append-only is the audit trail), and it does not count as a steer — it fixes the\n"
            "operator's slip, not the station's work.\n"
            "\n"
            "The operator may be the driving agent fixing a slip it just made — it signs\n"
            "--by with its own name (e.g. driver:claude); omitted, --by resolves to the\n"
            "human. A correction can target any state (a slip can point either way), but\n"
            "it only restores: a swallowed real decision (a gate or deploy outcome) gets\n"
            "the item put back at that state, then re-recorded via factory gate/advance."
        ),
    )
    s.add_argument("id", help="Work item id (WI-####)")
    s.add_argument("--state", required=True, help="The state the item should be at")
    s.add_argument(
        "--reason",
        required=True,
        help="Why the correction is needed — recorded in the item history and metrics ledger",
    )
    s.add_argument(
        "--by",
        help="Who is correcting; defaults to $FACTORY_USER or your git identity. An agent "
        "fixing its own slip signs with its own name (e.g. driver:claude)",
    )
    s.set_defaults(func=cmd_correct)

    # -- status / metrics / retro / labels --
    s = sub.add_parser("status", help="Show the board, or one item's history")
    s.add_argument("id", nargs="?", help="Work item id; omit for the whole board")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("metrics", help="Show the North Star ledger")
    s.set_defaults(func=cmd_metrics)

    s = sub.add_parser("retro", help="Assemble a briefing for the learning station")
    s.add_argument("--emit", help="Write the briefing to this file instead of stdout")
    s.set_defaults(func=cmd_retro)

    # -- ledger --
    s = sub.add_parser(
        "ledger",
        help="The retro ledger: one row per learning-loop proposal and what became of it",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "The durable memory of the learning loop (.factory/retro/ledger.jsonl, append-only;\n"
            "LEDGER.md is the regenerated human view). The retro station records every proposal\n"
            "here and opens each run by reconciling the open rows; the human audits from the\n"
            "rendered file. See `factory ledger <cmd> -h` for each verb."
        ),
    )
    lsub = s.add_subparsers(dest="ledger_cmd", required=True)
    a = lsub.add_parser(
        "add",
        help="Record a proposal (the retro station runs this for each one)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            '  factory ledger add --title "spec skill: require validation section" \\\n'
            "      --lever skill-edit --file .claude/skills/write-product-spec/SKILL.md \\\n"
            "      --answers WI-0001-spec_review-2026-06-27.md \\\n"
            '      --signal "no more missing-validation send-backs at spec_review"'
        ),
    )
    a.add_argument("--title", required=True, help="One line: what the proposal changes")
    a.add_argument(
        "--lever",
        required=True,
        help="The kind of change, e.g. skill-edit | gate-policy | template | line (free-form)",
    )
    a.add_argument(
        "--signal",
        required=True,
        help="How you'll know it worked — the observable signal to reconcile against later",
    )
    a.add_argument(
        "--file",
        action="append",
        metavar="PATH",
        help="A file the proposal touches; repeat for more. Not comma-separated.",
    )
    a.add_argument(
        "--answers",
        action="append",
        metavar="REF",
        help="An intervention record (or churn item) this answers; repeat for more",
    )
    a.add_argument("--pr", help="The retro PR carrying the change, once opened")
    a.add_argument(
        "--status",
        default="proposed",
        choices=sorted(STATUSES),
        help="Initial status (default: %(default)s)",
    )
    a.add_argument(
        "--category",
        help="The intervention category this proposal answers (e.g. missing-edge-case). "
        "Once the row is `applied`, the retro briefing mechanically flags any later "
        "intervention of the same category as a recurrence — the fix didn't hold",
    )
    a.set_defaults(func=cmd_ledger)
    u = lsub.add_parser(
        "update",
        help="Record what became of a proposal (status, observed outcome, PR)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  factory ledger update RP-0001 --status applied --pr https://github.com/o/r/pull/7\n"
            '  factory ledger update RP-0001 --outcome "3 retros later: the send-back stopped"\n'
            "\n"
            "Status is mutable state; the jsonl stays append-only (an update is a new event).\n"
            "applied = in effect (a merged edit, or a signed policy); dormant = a policy\n"
            "written but awaiting your signature; rejected / superseded close the row. An\n"
            "--outcome records what was actually observed against the row's signal — that's\n"
            "what closes the learning loop."
        ),
    )
    u.add_argument("id", help="Ledger row id (RP-####)")
    u.add_argument("--status", choices=sorted(STATUSES), help="New status for the row")
    u.add_argument("--outcome", help="What was observed against the row's signal")
    u.add_argument("--pr", help="The PR carrying the change")
    u.set_defaults(func=cmd_ledger)
    ll = lsub.add_parser("list", help="List ledger rows (compact; LEDGER.md is the full view)")
    ll.add_argument(
        "--open",
        action="store_true",
        help="Only rows awaiting adjudication (not closed, no outcome recorded)",
    )
    ll.add_argument(
        "--status",
        dest="status_filter",
        choices=sorted(STATUSES),
        help="Only rows currently at this status",
    )
    ll.set_defaults(func=cmd_ledger)

    # -- policy --
    s = sub.add_parser(
        "policy",
        help="Inspect gate policies (incl. suspensions) or reinstate a suspended rule",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  factory policy list\n"
            '  factory policy reinstate low-risk-docs --notes "rule was fine; the steer was\n'
            '      about wording, not the gate"\n'
            "\n"
            "Autonomy is an asymmetric ratchet. Promotion is human: a rule fires only once\n"
            "someone signs approved_by in policies.yml. Demotion is automatic: when an item a\n"
            "rule auto-cleared later needs human rework (a gate steer or a block), the rule is\n"
            "suspended — its gate goes back to the human — until a human reviews what happened\n"
            "and reinstates it here. Suspensions live in .factory/policy-state.json (engine-\n"
            "owned overlay); policies.yml stays yours alone to edit."
        ),
    )
    psub = s.add_subparsers(dest="policy_cmd", required=True)
    pl = psub.add_parser("list", help="Every rule with its live status (active/dormant/suspended)")
    pl.set_defaults(func=cmd_policy)
    pr = psub.add_parser("reinstate", help="Re-arm a suspended rule after reviewing its failure")
    pr.add_argument("rule_id", help="The rule id from policies.yml")
    pr.add_argument("--notes", help="Why it's safe to re-arm (kept in the overlay's history)")
    pr.add_argument(
        "--by",
        help="Who is reinstating; defaults to $FACTORY_USER or your git identity",
    )
    pr.set_defaults(func=cmd_policy)

    # -- doctor --
    s = sub.add_parser(
        "doctor",
        help="Cross-check config and stores for consistency (read-only; exit 1 on errors)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Checks: line.yml and policies.yml validate; every work item parses, sits on a\n"
            "known state, and matches its filename; every artifact path still exists; lineage\n"
            "(parent) pointers resolve; no stale gate bindings, crashed-save leftovers, or\n"
            "orphaned policy suspensions; metrics/ledger files are readable (torn lines\n"
            "counted); every ledger category matches an intervention record, and every\n"
            "intervention still has a readable machine block — the two halves of the retro's\n"
            "recurrence join, which fails silently when either drifts.\n"
            "\n"
            "Warnings inform; errors exit 1. Run it when something feels off, after a crash,\n"
            "or before trusting a factory you've just moved or upgraded."
        ),
    )
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser(
        "github-labels",
        help="List the GitHub conveyor labels, or create them in a repo (gh)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "These are the `factory:<state>` labels that mirror an item's position onto its\n"
            "GitHub issue (and trigger the cloud workflows) — presentation, defined in\n"
            "github-labels.yml. They are NOT the classifiers stations label work items with:\n"
            "those live in classifiers.yml, gate policies match on them, and they never touch\n"
            "GitHub. Two different things, two different files."
        ),
    )
    s.add_argument("--github", action="store_true", help="Create the labels via the gh CLI")
    s.add_argument("--repo", help="Target repo (owner/name) for --github")
    s.set_defaults(func=cmd_github_labels)
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
