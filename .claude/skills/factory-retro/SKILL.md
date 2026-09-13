---
name: factory-retro
description: The factory's learning station, run by `factory run retro`. Read the record of recent items (run comments, gate decisions, human reviews, human commits on factory PRs) and propose the smallest skill edits that would stop a recurring class of rework, as a pull request for a human to review. Not for use inside a driver session.
model: opus
allowed-tools: Bash Read Grep Glob Edit Write Agent
---

# Retro station

Every other station produces software; you produce a better factory. Your input is the record of every time a human had to step in. Your output is a small set of durable changes to the station skills that make those steps less likely next time. You propose; the human disposes.

## 1. Collect the record

```
factory metrics --json
gh issue view <n> --json title,body,labels,comments   # per item: run comments and factory · gate comments
gh api repos/<owner/repo>/pulls/<pr>/reviews       # human reviews; factory ones end with <!-- factory:review -->
gh api repos/<owner/repo>/pulls/<pr>/comments      # review threads and replies
gh api repos/<owner/repo>/pulls/<pr>/commits       # a commit whose author is not `factory` is a human fix
```

Start with the metrics: cost per shipped item and where the steers concentrate; each item row carries its `pr` number. For each item in the window, read the gate comments (the `--why` a human gave), human reviews and replies to factory findings, and human commits on factory PRs. Read the finished items' threads too, resolved ones included: an approving comment or a pass with no threads says what to keep, and a retro that only reads failures eventually optimizes away something that worked.

## 2. Score each signal

- `validated` — the human agreed, accepted the suggestion, or merged unchanged
- `corrected` — the human said a station's output was wrong, incomplete, noisy, or the wrong severity
- `refined` — mostly agreed but adjusted the scope, guidance, or pattern
- `ambiguous` — not enough signal

Ignore acknowledgements with no substantive judgment.

## 3. Synthesize durable knowledge

Cluster by root cause, not surface symptom. Worth encoding: a convention a station repeatedly misses, a false-positive class to demote, a severity calibration mistake, a check humans keep adding by hand, guidance about when not to act, a spec section that keeps coming out vague. Reject anything one-off to a single item, already covered by the skill, a product preference unrelated to factory quality, or a change that would break the report schema, the severity tags, or the safety rules in the shared system prompt. Prefer a small number of high-confidence learnings over many weak ones. Three similar steers is a pattern; one is an anecdote.

## 4. Decide

Exactly one outcome:

- `nothing_to_learn` — report and stop. Do not open an empty PR.
- `proposed` — edit the relevant skill files under `.claude/skills/` and open a PR.

For an observation the factory cannot fix by editing a skill (a stale direction, a missing environment, an engine limit), open an issue labeled `factory:retro` describing it, instead of a PR.

## 5. Apply edits carefully

Read the current skill file completely. Make the smallest cohesive edit that captures the learning, as a durable rule or example, never as a diary of this window's items. Keep the structure, the report contract, and the guardrails intact. Every edit needs, in the PR body: the evidence (issue and PR links), the exact learning, why it is durable, and the signal that would show it worked. Nothing of that goes inline into the skill.

## 6. Open the PR

`git checkout -b factory/retro-<YYYY-MM-DD>`, commit only the skill edits, `git push -u origin HEAD`, `gh pr create --title "retro: <date>" --body-file <file>`. Do not merge.

## 7. Report

Your final message is JSON matching the schema you were given. `summary`: the window, items inspected, the decision, and the PR or issue URLs. `notes`: the learnings encoded, one line each, and the candidates you rejected and why.

## Guardrails

- Do not edit product code, tests, or anything outside `.claude/skills/`.
- Do not invent feedback that is not in the record.
- Keep the PR small enough for a human to review in a few minutes.
