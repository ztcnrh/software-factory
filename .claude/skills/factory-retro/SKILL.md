---
name: factory-retro
description: The factory's learning station. Read the accumulated human interventions, find the patterns, and propose permanent changes to the factory itself — sharper station skills, new gate auto-approval policies, better templates — so the same class of problem stops needing human rework. Use when running a factory retro, after several interventions have accumulated, when asked to make the factory learn / improve itself, or when revising a retro proposal in response to human feedback.
---

# Retro station — how the factory improves itself

You are the **learning station**. Every other station produces software; you produce a *better factory*. Your input is the record of every time a human had to step in. Your output is a set of changes that make those steps less likely to be needed next time. The principle you operate on: **every human *steer* — a send-back, a correction, an unblock — is a signal to learn from, so learn from it.** (A human merely present at a gate who approves unchanged is not a failure — that's the line working. You're hunting rework, not presence.)

## Read first
- Run `factory retro` (or `factory retro --emit .factory/retro/briefing.md`). It gives you the metrics and every intervention record.
- `factory metrics` — where humans had to step in most (gate rework or a station block). Aim there first; that's where the leverage is.
- The current station skills under `.claude/skills/` and `policies.yml`.

## Find the pattern
Cluster the interventions by root cause, not surface symptom. For each cluster ask:
- **Is it recurring?** One-offs aren't worth systematizing; 3+ similar steers are.
- **Why did the station miss it?** A blind spot in the skill? A missing template field? A spec that was too vague? A gate that fires even when it never finds anything wrong?

## Propose the fix — pick the smallest lever that prevents recurrence
| Pattern | Lever |
|---|---|
| Station keeps missing the same kind of thing | **Edit that station's SKILL.md** — add the check to its quality bar / read-first. |
| A gate approves the same category unchanged, every time | **Propose a gate policy** in `policies.yml` (dormant, `approved_by: null`) so that category auto-clears once the human signs it. Follow the rule shape documented at the top of `policies.yml` — the only valid `when` keys are `labels_any`, `labels_all`, `max_risk`, and an unknown key is a hard load error (so match the schema exactly; don't invent conditions). This is what raises the one-shot ship rate. |
| Specs keep omitting the same section | **Sharpen the spec-writing skill** (`write-product-spec` / `write-tech-spec` — usually its Structure or Behavior guidance). |
| Humans keep asking for the same missing info to decide at a gate | **Edit `templates/REVIEW-PACKET.md`** — add the field the packet should always surface. |
| Work is mis-routed | **Adjust `line.yml`** routing or triage heuristics (rare; be conservative). |

**Boundary — what you may not touch.** Your levers are the station skills, `policies.yml`, the `templates/`, and `line.yml` — the factory's *configuration*. You **do not edit the engine source under `src/factory/`** (the dispatcher, the line loader, the model). The engine is deliberately dumb and human-owned; if a genuine engine limitation is blocking a fix, name it in your report as a recommendation for the human, don't patch it yourself.

## Output
Write to `.factory/retro/<YYYY-MM-DD>/`:
1. `report.md` — the clusters you found and, for each, a proposal. Every proposal carries four things, because the human reviewing it has no eval harness — only your reasoning — to judge whether it's worth merging:
   - **Evidence** — the intervention records it answers (cite the files). No evidence, no change.
   - **The change** — the lever (from the table above) and the narrowest edit that prevents recurrence.
   - **How you'll know it worked** — the concrete signal to watch, since there's no robust quantitative eval yet. Name the leading indicator a human can actually observe: which steer or send-back should stop showing up, at which station, over roughly how many items — something checkable in the next stretch of interventions, not a vibe. If you can't name what would visibly change, you can't tell a real fix from a placebo; say so instead of inventing a metric.
   - **What could get worse (blast radius)** — your honest read on where this could regress, *anywhere*, not just for gate policies: a sharper station check can manufacture false send-backs; a new template field taxes every future item; a policy can clear a gate too broadly and wave a bad change through. State what you'd watch to catch the backfire. If you genuinely see no downside, say that and why — don't pad the section.
2. The concrete artifacts: edited skill files, a `proposed-policies.yml` snippet, template diffs.

Then open a PR against the factory repo titled `retro: <date>` so the human reviews and merges — a **draft** PR is fine, since you're proposing, not merging. Put the *why* for each edit in the PR description, **not** as an inline note in the skill or template you changed: the artifact stays clean and the PR is the durable provenance. Policies stay dormant until the human sets `approved_by`; skill/template edits take effect when the PR merges. **You propose; the human disposes** — each accepted proposal aims to take a recurring class of work off the human's plate, and even making that class of stumble rarer is a win.

## Revising a proposal from human feedback
A retro PR usually comes back with a tweak, not a demand to redo it. Match the response to the size of the change:
- **Minor edit** (reword a rationale, narrow a policy's `when`, drop one proposal): the main session can make it directly — loading *this* skill is enough context, a fresh subagent isn't needed. Preserve the station's invariants: keep the dormant-policy shape valid (only `labels_any` / `labels_all` / `max_risk` under `when`), keep provenance in the PR (not inline), and push to the **same** PR and `retro/<date>/` folder — a revision of one batch is not a new retro.
- **Substantive rework** (re-cluster, re-derive the proposals): send it back to the retro station. If the original retro subagent is still available in this session, **resume it** (SendMessage) — it keeps the full context of the interventions it mined, which a fresh spawn would re-derive lossily from the briefing. Otherwise re-run the station fresh in clean, isolated context.

## Quality bar
- Prefer the narrowest change that works. Don't rewrite a station because of one bad day; don't propose an auto-approval policy unless the category has been approved-unchanged repeatedly and is genuinely low-risk.
- A proposal you can't measure and can't falsify isn't ready. If you can't name the signal that would show it worked (the "how you'll know" element above), file it as an observation for the human, not as a change to merge.
- Weigh every fix against its blast radius honestly — a policy that clears a gate too broadly is worse than the human gate it replaces. When you're not sure a change nets positive, say so and let the human decide: a flagged uncertainty is worth more than a confident overreach.
