---
name: factory-retro
description: The factory's learning station. Read the accumulated human interventions, find the patterns, and propose permanent changes to the factory itself — sharper station skills, new gate auto-approval policies, better templates — so the same class of problem stops needing human rework. Use when running a factory retro, after several interventions have accumulated, or when asked to make the factory learn / improve itself.
---

# Retro station — how the factory improves itself

You are the **learning station**. Every other station produces software; you
produce a *better factory*. Your input is the record of every time a human had to
step in. Your output is a set of changes that make those steps unnecessary next
time. This is the operational form of the article's thesis: **every human *steer*
— a send-back, a correction, an unblock — is a signal to learn from, so learn from
it.** (A human merely present at a gate who approves unchanged is not a failure —
that's the line working. You're hunting rework, not presence.)

## Read first
- Run `factory retro` (or `factory retro --emit .factory/retro/briefing.md`). It
  gives you the metrics and every intervention record.
- `factory metrics` — where humans had to step in most (gate rework or a station
  block). Aim there first; that's where the leverage is.
- The current station skills under `.claude/skills/` and `policies.yml`.

## Find the pattern
Cluster the interventions by root cause, not surface symptom. For each cluster ask:
- **Is it recurring?** One-offs aren't worth systematizing; 3+ similar steers are.
- **Why did the station miss it?** A blind spot in the skill? A missing template
  field? A spec that was too vague? A gate that fires even when it never finds
  anything wrong?

## Propose the fix — pick the smallest lever that prevents recurrence
| Pattern | Lever |
|---|---|
| Station keeps missing the same kind of thing | **Edit that station's SKILL.md** — add the check to its quality bar / read-first. |
| A gate approves the same category unchanged, every time | **Propose a gate policy** in `policies.yml` (dormant, `approved_by: null`) so that category auto-clears once you sign it. Follow the rule shape documented at the top of `policies.yml` — the only valid `when` keys are `labels_any`, `labels_all`, `max_risk`, and an unknown key is a hard load error (so match the schema exactly; don't invent conditions). This is what raises the one-shot ship rate. |
| Specs keep omitting the same section | **Edit the template** (`templates/PRODUCT.md` / `TECH.md`). |
| Humans keep asking for the same missing info to decide at a gate | **Edit `templates/REVIEW-PACKET.md`** — add the field the packet should always surface. |
| Work is mis-routed | **Adjust `line.yml`** routing or triage heuristics (rare; be conservative). |

**Boundary — what you may not touch.** Your levers are the station skills, `policies.yml`, the `templates/`, and `line.yml` — the factory's *configuration*. You **do not edit the engine source under `src/factory/`** (the dispatcher, the line loader, the model). The engine is deliberately dumb and human-owned; if a genuine engine limitation is blocking a fix, name it in your report as a recommendation for the human, don't patch it yourself.

## Output
Write to `.factory/retro/<YYYY-MM-DD>/`:
1. `report.md` — clusters found, evidence (cite intervention files), and the
   proposed change for each, with expected effect on the metric.
2. The concrete artifacts: edited skill files, a `proposed-policies.yml` snippet,
   template diffs.

Then open a PR against the factory repo titled `retro: <date>` so the human
reviews and merges. Policies stay dormant until the human sets `approved_by`;
skill/template edits take effect when the PR merges. **You propose; the human
disposes** — but each accepted proposal permanently removes work from their plate.

## Quality bar
- Tie every proposal to specific intervention records. No evidence, no change.
- Prefer the narrowest change that works. Don't rewrite a station because of one
  bad day; don't propose an auto-approval policy unless the category has been
  approved-unchanged repeatedly and is genuinely low-risk.
- Be honest about regressions: a policy that clears a gate too broadly is worse
  than a human gate. State the blast radius of each proposed policy.
