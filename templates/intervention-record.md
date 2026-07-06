# Intervention — <WI-id> @ <gate>

> The factory writes this automatically whenever you steer at a gate (a revision,
> a not-ready, a park, or an approve-with-changes). It is the raw material the
> **retro station** mines to make the same problem stop reaching you. This file
> documents the shape; `src/factory/interventions.py` generates the real ones.

- **When:** <timestamp>
- **Work item:** <WI-id> — <title>
- **Gate:** <spec_review | ship_review | needs_human | blocked>
- **Decision:** <the verdict you chose>
- **By:** <you>
- **Category:** <missing-edge-case | wrong-scope | style | security | …>

## What the station produced
What the agent handed you.

## What the human wanted instead
What you actually wanted — the gap.

## Why — the steering signal
The reasoning. This is the part the retro station learns from, so make it the
*generalizable* reason ("public endpoints always need rate limiting"), not just
the one-off fix.

---
```yaml
# machine-readable block the retro station parses
item: <WI-id>
gate: <gate>
decision: <verdict>
category: "<category>"
changed: true
state_before: <state>
```
