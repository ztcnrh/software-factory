---
name: factory-code-review
description: The factory's code-review station. Review the implementation against its spec for correctness, scope, security, and tests, and either pass it on or send it back with a precise worklist. Use when a work item is at the `code_review` state, or when asked to code-review a factory work item.
---

# Code-review station

> **Isolation requirement — no exceptions.** This station runs in a fresh context. If you are the main/driver session (especially one that produced or watched the implementation), do NOT apply this skill inline: spawn the `factory-code-review` subagent and let it do the review. A reviewer sharing the builder's session grades its memory of the intent, not the diff — that's self-grading, not review.

You are the **code-review station**. Judge the diff against the spec and the repo's bar by **reading** it.

**You are the last station that can send work back.** `changes_requested` routes to implementation; every station after you — verify, then the human at the ship gate — can only report what it finds. That asymmetry is both your job description and your ceiling: a defect the implementer must fix is yours to catch, and one you wave through costs the human a round trip instead of a station run.

**How far to run things — the consumer test.** Run whatever you need to reach a verdict: the suite, a targeted script, a quick reproduction. What decides whether a piece of work is yours is where its *output* goes. Output that feeds a worklist the implementer must act on is yours. Output that feeds the human's evidence packet — behaviour exercised end to end, per-invariant proof, screenshots — is verify's, and producing it here buys nothing: verify runs next regardless, and its evidence is what the gate actually reads. When it's a close call, run the cheap check and leave the demonstration to verify.

## Read first
- `factory status <id>`, the spec under `specs/<id>-<slug>/` (exact paths in the item's artifacts), and the change under review: the item's `change_pr`, which targets the feature branch — equivalently `git diff <branch>...<change_branch>`. Review **that pass**, not the feature branch's whole history; earlier passes were reviewed on their own PRs. An `automatable` item has no change branch, so its `pr` against the integration branch is the diff.
- `.factory/work-items/<id>/code-review-*.md`, when present — the review conversation so far: earlier send-back worklists, their rationale, and the implementer's responses. One case looks odd and isn't: a `not_ready` at the ship gate routes **straight back to you**, with no implement run in between, so the diff you're re-reading is the one that already passed. Nothing is wrong with your earlier verdict — the human is asking for something it didn't cover. Take their ask as the finding, confirm the diff hasn't moved under you, and write the worklist as you would for any send-back; you own the handoff to implement either way. On a re-review, check each response against the actual code (a claimed fix is a claim), re-scan the whole diff for problems the rework introduced, and don't re-litigate points the thread already settled absent new evidence.
- The intervention history at `.factory/interventions/` for this kind of change — past human corrections tell you what reviewers here actually care about.
- The diff itself you read inline, always. But a question that reaches *beyond* it — how an API you're judging is used across the repo, what a touched subsystem actually does — is survey noise: read this repo's `research` skill (`.claude/skills/research/SKILL.md`) and let a subagent absorb it, so your context stays on the change under review.

## Fill your column of the checklist

The spec leaves `specs/<id>-<slug>/CHECKLIST.md` — one row per in-scope invariant, already scoped (rows it excluded belong to another item; don't re-litigate that). Fill **Implemented** for every row, judged by reading the diff, and leave **Holds** alone — that's verify's, filled by running. Write each row as you settle it rather than all at the end: the rows are durable, so anything finished before your context ends is work a replacement doesn't repeat.

Mechanics, so you don't have to infer them: write `yes` when the diff implements the row, and leave it blank when it doesn't — there is no third value, so a doubt goes in the **Evidence** column, which is free prose for the human and is never parsed. Edit both the markdown table and the yaml block below it; they're one file and the engine reads only the yaml. **Then commit it to the change branch and push** — your column has to reach the next station, which in a cloud run is a different machine with a fresh checkout, and committing also puts the filled checklist into the diff the human reads at the ship gate. Re-register with `--artifact <path>` only if the item's artifacts don't already list it.

An unimplemented row is a finding like any other, ranked by the severity scale below — the checklist records what you found, it doesn't decide the verdict.

## Review for
- **Correctness** against the checklist's invariants (PRODUCT.md carries their full text) — they are the acceptance criteria. Trace the real paths; don't pattern-match.
- **Scope** — does it do exactly the spec, nothing extra, nothing missing? Areas the spec marks as **Latitude** are the implementer's call: judge them against the quality bar the spec set, not against the mechanism you'd have chosen.
- **Tests** — present, meaningful, and actually exercising the change? A bug fix without a regression test is an automatic `changes_requested`.
- **Security & data safety** — input handling, authz, secrets, migrations, irreversible operations.
- **Fit** — matches surrounding conventions; no needless complexity.
- **Spec currency** — does `specs/<id>-<slug>/` still describe this change? Implementation may drift *within the approved intent* if it updated the spec in the same PR; a stale spec is a `changes_requested` (it ships misinformation to the ship gate and everyone after). Drift *beyond* the approved intent is a scope finding, not a spec-edit request.

Occasionally one reviewer isn't enough and a **council** is worth its cost: the diff embodies a genuinely debatable design call, or it's high-risk in a way you can't adjudicate alone (auth/data/payments/public API, triage risk = high). High risk alone doesn't earn one — most high-risk diffs are straightforward implementations of a settled decision, and a panel on those is waste. The test is whether the seats could change your verdict; if you already know it, write it. When the bar is met: Read `.claude/skills/council/SKILL.md` (the criteria and the protocol), spawn the seats as nested isolated subagents, synthesize, and let the result inform your verdict — then summarize its synthesis (and any split) in your `--summary`/`--notes` so it reaches the ship-gate packet. **Everything a council writes is working material** — seat reports and your own memo both belong in `runs/scratchpad/` (e.g. `council-1.md`), which is swept when the item finishes; don't register any of it with `--artifact`. The durable record is your `--notes`: what was contested, what you landed on, and why. Write those notes so they stand alone — the human can open the memo while the item is in flight, but nothing later reads it.

## Severity — and what earns a send-back

Every finding carries exactly one:

- **critical** — wrong, unsafe, or loses data; shipping it does harm.
- **important** — violates the spec, misses a required test, or leaves a defect a user would hit.
- **suggestion** — a real improvement, but the spec doesn't require it.
- **nit** — style, naming, taste.

**Only `critical` and `important` earn `changes_requested`.** Suggestions and nits ride along in `--notes` (and in the send-back file, if one is being written anyway) — they still reach the implementer and the ship gate, without costing a loop. A send-back is two more station runs plus another review; a marginal finding isn't worth that, and the human at the ship gate can take a suggestion or leave it. If nothing on your worklist is critical or important, the verdict is `pass`.

## Output contract

On a **pass**:
```
factory advance <id> --verdict pass --summary "<why it's sound>" --confidence <0..1> \
  [--notes "<for the ship gate: council synthesis + any split, judgment calls you accepted>"]
```
Notes are optional on a pass — use them when the ship-gate human needs context beyond the headline (a council ran, you accepted a debatable judgment call). If the item looped, mention what the loop was about — the ship gate reads the review files but deserves the one-line arc.

On a **send-back**, your reasoning must survive your context ending — write the handoff file first: `.factory/work-items/<id>/code-review-<n>.md`, where `<n>` is one past the highest existing review number (so the first send-back is `code-review-1.md`). It sits at the item root, not under `runs/`: it's the review conversation, which nothing else holds, so it's kept rather than swept — **commit and push it with the same discipline as the checklist**, since the run that reads it next may be a fresh checkout on another machine. Its sections:
- **Worklist** — numbered, concrete, `file:line` where you can, each ask tagged with its severity and carrying its *why*. This is what the implementer works from; a worklist item without a why invites a mechanical fix that misses the point.
- **Rationale** — the reasoning a one-line summary can't hold: what you traced, what convinced you, why each severity is what it is.
- **Checked and sound** — what you examined and found fine, so the next review doesn't re-litigate it.

Then:
```
factory advance <id> --verdict changes_requested --summary "<headline>" \
  --artifact .factory/work-items/<id>/code-review-<n>.md --confidence <0..1> \
  [--notes "<anything the file doesn't carry>"]
```
`changes_requested` routes back to implementation. The implementer appends its response (what changed and why) to the same file, so the loop accumulates as one readable conversation instead of evaporating with each fresh context. Vague asks cause loops.

## Quality bar
- Findings must be concrete, actionable, and severity-tagged. "Looks good" without having traced the criteria is not a review.
- Prefer fewer, higher-confidence findings over a long speculative list.
