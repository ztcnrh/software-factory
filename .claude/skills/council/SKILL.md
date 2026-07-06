---
name: council
description: Convene a model-diverse council of subagents to investigate one question from multiple angles in parallel, then synthesize by evidence quality into a single recommendation. Use for high-stakes calls inside the factory — risky spec/architecture decisions or code review of high-risk changes — or whenever the user asks for a council, multiple opinions, or parallel investigation. Adapted from Warp's common-skills.
---

# Council

Multiple independent investigators, deliberately different, beat one — especially
on architecture decisions and high-risk reviews. Use this when a single
perspective isn't enough confidence. (Pattern adapted from warpdotdev/common-skills.)

## When to convene
Risky or contested calls: spec/architecture tradeoffs, review of high-risk diffs
(auth, data, money, public API), incident root-cause. Skip it for routine work —
a council on a typo is waste.

## Run it
1. **Frame** the question in one sentence: the decision, the options, the
   artifacts to examine, and what "good" looks like.
2. **Assemble a roster** — prioritize *model diversity* over angle-only variety.
   Spawn subagents (Task/Agent tool) on different models where possible, each with
   a distinct mandate:
   - strongest reasoning model → architecture / correctness
   - a different frontier/GPT-family model → implementation / feasibility
   - a contrarian seat → red-team, find the failure mode
3. **Brief identically, investigate independently.** Give each the same context
   and constraints (read-only vs editable). Don't let them cross-pollinate yet.
4. **Require a structured report** from each: files inspected, current behavior,
   the option assessed, risks, cost, recommendation, confidence.
5. **Synthesize by evidence quality, not vote count.** Lead with the
   recommendation; name where they agreed and where they split; address the
   strongest objection; give the concrete next action.

## Output
- **Recommendation** (1–2 sentences) · **Why** (2–3 evidence-backed reasons) ·
  **Tradeoffs/risks** · **Final call** (the next action).

In the factory, a council verdict feeds the station that called it — e.g. the
code-review station emits `pass` or `changes_requested` based on the synthesis.
