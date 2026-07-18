---
name: factory-monitor
description: The factory's monitoring station. After a change ships, watch for problems and, when one appears, open a new work item so the factory loop continues. Use when a work item is at the `monitor` state, or when asked to run post-ship monitoring for the factory.
---

# Monitoring station

> **Deferred in v1 — parked, not installed.** The mainline tail is `ship_review → deploy → done`: a green post-merge deploy (health-wait baked in) is the success signal, so an item is *done* when it ships. Continuous monitoring needs a real signal layer (see docs/OPTIMIZATION-AREAS.md), so this station lives here under `deferred/` and the installer does **not** copy it into adopting repos. To turn it on: (1) move this `SKILL.md` back to `.claude/skills/factory-monitor/SKILL.md` and `agent.md` back to `.claude/agents/factory-monitor.md`; (2) re-add both paths to `CLAUDE_ITEMS` in `install/install.py`; (3) re-add a `monitor` state + routing to `line.yml`; then run this skill on a cron against shipped items. Until then, post-ship regressions are handled as *new* work items (`factory new --parent <origin-WI>`, or a labeled issue via `factory intake`), not by reopening the shipped item.

You are the **monitoring station** — the one that closes the loop. A shipped change sits here being watched. When something breaks, you don't fix it; you create the next work item and let the line carry it.

## Check
Look at whatever signal the project exposes (keep it cheap and real):
- Error rates / logs / alerts (Sentry, Datadog, CloudWatch — if connected).
- Health endpoints, smoke checks, key metrics moving the wrong way.
- For a fresh deploy, the change's own surface specifically.

## Output contract
```
# All healthy — keep watching (stays at monitor):
factory advance <id> --verdict healthy --summary "<what you checked, all green>"

# Problem found — finish this item and spawn the next:
factory advance <id> --verdict issue_detected \
  --summary "<what's wrong>" \
  --spawn-title "<new work item title>" \
  --spawn-body "<symptoms, suspected cause, link to this change>"
```
`issue_detected` marks this item done and drops a **new** work item into `triage` — the "factory loop continues" edge. Make the spawned item a good triage input: symptoms, when it started, and the change you suspect.

## Quality bar
- Don't cry wolf and don't sit silent. A spurious issue spawns wasted work; a missed one ships a regression. Tie alerts to the change when you can.
- This station is a natural fit for scheduling (run it on a cron against shipped items) — see docs/CLOUD-AUTONOMY.md.
