---
name: factory-monitor
description: The factory's monitoring station. After a change ships, watch for problems and, when one appears, open a new work item so the factory loop continues. Use when a work item is at the `monitor` state, or when asked to run post-ship monitoring for the factory.
---

# Monitoring station

> **Deferred in v1 — not wired into the line.** The mainline tail is
> `ship_review → deploy → done`: a green post-merge deploy (health-wait baked in)
> is the success signal, so an item is *done* when it ships. Continuous
> monitoring needs a real signal layer (see docs/OPTIMIZATION-AREAS.md), so this
> station is kept as an **optional, schedulable** capability, not a state in
> `line.yml`. To turn it on, re-add a `monitor` state + routing to `line.yml` and
> run this skill on a cron against shipped items. Post-ship regressions are
> otherwise handled as *new* work items (ideally via the issues-watcher), not by
> reopening the shipped item.

You are the **monitoring station** — the one that closes the loop. A shipped
change sits here being watched. When something breaks, you don't fix it; you
create the next work item and let the line carry it.

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
`issue_detected` marks this item done and drops a **new** work item into `triage`
— the "factory loop continues" edge. Make the spawned item a good triage input:
symptoms, when it started, and the change you suspect.

## Quality bar
- Don't cry wolf and don't sit silent. A spurious issue spawns wasted work; a
  missed one ships a regression. Tie alerts to the change when you can.
- This station is a natural fit for scheduling (run it on a cron against shipped
  items) — see docs/CLOUD-AUTONOMY.md.
