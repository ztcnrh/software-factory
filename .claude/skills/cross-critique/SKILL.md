---
name: cross-critique
description: When several competing proposals exist for one contested decision, circulate them among their authors for structured peer critique, then synthesize the strongest surviving answer. Use after a council or any time there is genuine divergence on an architecture/design/API/root-cause question. Adapted from Warp's common-skills.
---

# Cross-critique

A second round after divergence: instead of you synthesizing competing proposals cold, have each proposal's author critique the others. Authors carry deep context from their investigation; turning that on each other surfaces assumptions and failure modes solo synthesis misses. (Adapted from warpdotdev/common-skills.)

## When to use
Genuine divergence on a question without an objective answer: architecture/design tradeoffs, conflicting review conclusions, competing root-cause theories. Skip it when proposals already converge, or when a direct test would settle it faster — verify, don't deliberate.

## Run it
1. **Assemble the proposals.** Collect each recommendation with its reasoning. Consider neutral labels (A/B/C) and anonymizing authorship to reduce bias.
2. **Circulate for structured critique.** Reuse the original subagents (they keep their context). Ask each for: pros/cons of *each* alternative, whether they'd revise their own stance now, and a final ranking with confidence.
3. **Insist on balance.** An honest critique that credits a rival's strengths is worth more than reflexive self-defense. Reject one-sided takedowns.
4. **Synthesize by rigor, not tally.** Structure the answer around: the recommendation, where critiques converged, the strongest surviving objection, why the choice withstands it, and the remaining unknowns.

## Output
- **Recommendation** · **What survived critique** · **Strongest objection & why it doesn't sink it** · **Remaining unknowns / what would change the call.**

In the factory, use this to resolve a split spec council before sending the spec to the human gate — so the human reviews one well-pressure-tested design, not a debate.
