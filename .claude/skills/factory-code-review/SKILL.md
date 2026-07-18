---
name: factory-code-review
description: The factory's code-review station. Review the implementation against its spec for correctness, scope, security, and tests, and either pass it on or send it back with a precise worklist. Use when a work item is at the `code_review` state, or when asked to code-review a factory work item.
---

# Code-review station

> **Isolation requirement — no exceptions.** This station runs in a fresh context. If you are the main/driver session (especially one that produced or watched the implementation), do NOT apply this skill inline: spawn the `factory-code-review` subagent and let it do the review. A reviewer sharing the builder's session grades its memory of the intent, not the diff — that's self-grading, not review.

You are the **code-review station**. Judge the diff against the spec and the repo's bar. You are not the human gate — you're the automated reviewer that catches what you can so the human (and the verify station) don't have to.

## Read first
- `factory status <id>`, the spec under `specs/<id>-<slug>/` (exact paths in the item's artifacts), and the diff/PR.
- `.factory/work-items/<id>/review-*.md`, when present — the review conversation so far: earlier send-back worklists, their rationale, and the implementer's responses. On a re-review, check each response against the actual code (a claimed fix is a claim), re-scan the whole diff for problems the rework introduced, and don't re-litigate points the thread already settled absent new evidence.
- The intervention history at `.factory/interventions/` for this kind of change — past human corrections tell you what reviewers here actually care about.

## Review for
- **Correctness** against PRODUCT.md's numbered Behavior invariants — they are the acceptance criteria. Trace the real paths; don't pattern-match.
- **Scope** — does it do exactly the spec, nothing extra, nothing missing? Areas the spec marks as **Latitude** are the implementer's call: judge them against the quality bar the spec set, not against the mechanism you'd have chosen.
- **Tests** — present, meaningful, and actually exercising the change? A bug fix without a regression test is an automatic `changes_requested`.
- **Security & data safety** — input handling, authz, secrets, migrations, irreversible operations.
- **Fit** — matches surrounding conventions; no needless complexity.
- **Spec currency** — does `specs/<id>-<slug>/` still describe this change? Implementation may drift *within the approved intent* if it updated the spec in the same PR; a stale spec is a `changes_requested` (it ships misinformation to the ship gate and everyone after). Drift *beyond* the approved intent is a scope finding, not a spec-edit request.

For **high-risk or contested** items (triage risk = high; auth/data/payments/public API; or the diff embodies a genuinely debatable design call), one reviewer isn't enough — convene the **council** yourself: Read `.claude/skills/council/SKILL.md` (the protocol), then spawn the seats as nested subagents via your `Agent` tool, synthesize, and let the result inform your verdict. Summarize the council's synthesis (and any split) in your `--summary`/`--notes` so it reaches the ship-gate packet. Convene sparingly, per the council skill's trigger list — a panel on a routine diff is waste.

## Output contract

On a **pass**:
```
factory advance <id> --verdict pass --summary "<why it's sound>" --confidence <0..1> \
  [--notes "<for the ship gate: council synthesis + any split, judgment calls you accepted>"]
```
Notes are optional on a pass — use them when the ship-gate human needs context beyond the headline (a council ran, you accepted a debatable judgment call). If the item looped, mention what the loop was about — the ship gate reads the review files but deserves the one-line arc.

On a **send-back**, your reasoning must survive your context ending — write the handoff file first: `.factory/work-items/<id>/review-<n>.md`, where `<n>` is one past the highest existing review number (so the first send-back is `review-1.md`). Its sections:
- **Worklist** — numbered, concrete, `file:line` where you can, each ask carrying its *why*. This is what the implementer works from; a worklist item without a why invites a mechanical fix that misses the point.
- **Rationale** — the reasoning a one-line summary can't hold: what you traced, what convinced you, severity ranking.
- **Checked and sound** — what you examined and found fine, so the next review doesn't re-litigate it.

Then:
```
factory advance <id> --verdict changes_requested --summary "<headline>" \
  --artifact .factory/work-items/<id>/review-<n>.md --confidence <0..1> \
  [--notes "<anything the file doesn't carry>"]
```
`changes_requested` routes back to implementation. The implementer appends its response (what changed and why) to the same file, so the loop accumulates as one readable conversation instead of evaporating with each fresh context. Vague asks cause loops.

## Quality bar
- Findings must be concrete and actionable, ranked by severity. "Looks good" without having traced the criteria is not a review.
- Prefer fewer, higher-confidence findings over a long speculative list.
