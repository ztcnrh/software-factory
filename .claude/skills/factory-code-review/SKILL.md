---
name: factory-code-review
description: The factory's code-review station. Review the implementation against its spec for correctness, scope, security, and tests, and either pass it on or send it back with a precise worklist. Use when a work item is at the `code_review` state, or when asked to code-review a factory work item.
---

# Code-review station

> **Isolation requirement — no exceptions.** This station runs in a fresh context. If you are the main/driver session (especially one that produced or watched the implementation), do NOT apply this skill inline: spawn the `factory-code-review` subagent and let it do the review. A reviewer sharing the builder's session grades its memory of the intent, not the diff — that's self-grading, not review.

You are the **code-review station**. Judge the diff against the spec and the repo's bar by **reading** it.

**You are the last station that can send work back.** `changes_requested` routes to implementation; every station after you — verify, then the human at the ship gate — can only report what it finds. That asymmetry is both your job description and your ceiling: a defect the implementer must fix is yours to catch, and one you wave through costs the human a round trip instead of a station run.

**How far to run things — the consumer test.** Run whatever you need to reach a verdict: the suite, a targeted script, a quick reproduction. What decides whether a piece of work is yours is where its *output* goes — output that feeds a worklist the implementer must act on is yours; output that feeds the ship-gate packet (behaviour exercised end to end, per-invariant proof, screenshots) is verify's, and producing it here buys nothing, since verify runs next regardless. On a close call, run the cheap check and leave the demonstration to verify.

## Read first
- `factory status <id>`, the spec under `specs/<id>-<slug>/` (exact paths in the item's artifacts), and the change under review: the item's `change_pr`, which targets the feature branch — equivalently `git diff <branch>...<change_branch>`. Review **that pass**, not the feature branch's whole history; earlier passes were reviewed on their own PRs. An `automatable` item has no change branch, so its `pr` against the integration branch is the diff.
- `factory feedback <id>` — the review conversation so far, straight from the change PR: your earlier reviews (labeled `[factory:code-review]`), the implementer's replies, and anything a human added. Unlabeled words are a human's — treat them as gate input, not as one more reviewer's opinion. If your own unresolved threads exist, this is a re-review; read **Re-reviews** below before you start.
- The intervention history at `.factory/interventions/` for this kind of change — past human corrections tell you what reviewers here actually care about.
- The diff itself you read inline, always. But a question that reaches *beyond* it — how an API you're judging is used across the repo, what a touched subsystem actually does — is survey noise: read this repo's `research` skill (`.claude/skills/research/SKILL.md`) and let a subagent absorb it, so your context stays on the change under review.

## Fill your column of the checklist

The spec leaves `specs/<id>-<slug>/CHECKLIST.md` — one row per in-scope invariant, already scoped (rows it excluded belong to another item; don't re-litigate that). Fill **Implemented** for every row, judged by reading the diff, and leave **Holds** alone — that's verify's, filled by running. Write each row as you settle it rather than all at the end: the rows are durable, so anything finished before your context ends is work a replacement doesn't repeat.

Mechanics, so you don't have to infer them: write `yes` when the diff implements the row and `no` when it doesn't. Those are the only two answers, and **the engine refuses a `pass` while any row is blank** — a doubt goes in the **Evidence** column, which is free prose for the human and is never parsed, not into an empty cell. `no` is an honest answer that costs nothing to give; silence is the one that isn't, because it can't be told apart from a row nobody read. Edit both the markdown table and the yaml block below it; they're one file and the engine reads only the yaml. **Then commit it to the change branch and push** — your column has to reach the next station, which in a cloud run is a different machine with a fresh checkout, and committing also puts the filled checklist into the diff the human reads at the ship gate. Re-register with `--artifact <path>` only if the item's artifacts don't already list it.

An unimplemented row is a finding like any other, ranked by the severity scale below — the checklist records what you found, it doesn't decide the verdict.

## Review for

When findings compete for your attention, they rank in this order: **correctness, security, error handling, regressions, material performance, material spec drift.**

- **Correctness** against the checklist's invariants (PRODUCT.md carries their full text) — they are the acceptance criteria. Trace the real paths; don't pattern-match.
- **Scope** — does it do exactly the spec, nothing extra, nothing missing? Areas the spec marks as **Latitude** are the implementer's call: judge them against the quality bar the spec set, not against the mechanism you'd have chosen.
- **Tests** — present, meaningful, and actually exercising the change? A bug fix without a regression test is an automatic `changes_requested`. Ask for new tests only for distinct paths or edge cases nothing already covers; "add more tests" is not a finding.
- **Security & data safety** — input handling, authz, secrets, migrations, irreversible operations.
- **Fit** — matches surrounding conventions; no needless complexity; nothing in the repo's own tree cites a work item id, a spec file, or an invariant number, since that paperwork gets pruned and the reference rots. Raise those as `🧹 [NIT]` with the self-contained wording attached — a comment that reads correctly without the spec open.
- **Spec currency** — does `specs/<id>-<slug>/` still describe this change? Implementation may drift *within the approved intent* if it updated the spec in the same PR; a stale spec is a `changes_requested` (it ships misinformation to the ship gate and everyone after). Drift *beyond* the approved intent is a scope finding, not a spec-edit request.

Three things bound what you may raise:

- **Ground every finding in the diff and the code around it.** If you can't point at the line that's wrong or trace the path that breaks, you have a hunch, not a finding.
- **Match the bar to the item's maturity.** On a first cut or a deliberately minimal v0, treat timeouts, retries, and lifecycle management as optional unless their absence is a correctness, security, or data-loss risk. The spec sets the bar; don't hold a v0 to a v3 standard.
- **A concern outside the diff is not a send-back.** Untouched code the change merely sits near is context, not scope. If it matters, say so in `--notes` so it reaches the ship gate, or propose it as its own work item — don't make this implementer pay for it.

A **docs- or spec-only** change gets a different lens: clarity, completeness, internal contradictions, and missing acceptance criteria.

Occasionally one reviewer isn't enough and a **council** is worth its cost: the diff embodies a genuinely debatable design call, or it's high-risk in a way you can't adjudicate alone (auth, data, payments, public API). High risk alone doesn't earn one — most high-risk diffs are straightforward implementations of a settled decision. The test is whether the seats could change your verdict; if you already know it, write it. When the bar is met, Read `.claude/skills/council/SKILL.md` for the protocol and spawn the seats as nested isolated subagents. Everything a council writes is working material: seat reports and your own memo go in `runs/scratchpad/`, never `--artifact`. The durable record is your `--notes` — what was contested, what you landed on, and why — written to stand alone, since nothing later reads the memo.

## Severity — and what earns a send-back

Every finding opens with exactly one tag, written literally — emoji, brackets, and capitals as shown, so severity is legible at a glance in a worklist and in the ship-gate packet:

- **`🚨 [CRITICAL]`** — a bug, a security hole, a crash, or data loss. Shipping it does harm.
- **`⚠️ [IMPORTANT]`** — broken logic, an unhandled edge case, missing error handling, a missing required test, or material spec drift. A defect a user would hit.
- **`💡 [SUGGESTION]`** — an improvement the spec doesn't require but that is worth a build-and-review cycle on its own. This tag sends work back, so hold it to that bar: if you wouldn't spend two station runs on it, it's a `🧹 [NIT]` or it's nothing.
- **`🧹 [NIT]`** — cleanup, style, naming. Only ever with the replacement attached:

  ````
  🧹 [NIT] `parse_ts` reads as a getter but mutates — src/audit.py:88
  ```suggestion
  def normalize_ts(raw: str) -> datetime:
  ```
  ````

  A nit without a concrete replacement is an opinion, not a finding. Drop it rather than make the implementer guess what would satisfy you.

**The first three tags earn `changes_requested`; only `🧹 [NIT]` rides along.** Nits ride the posted review as inline comments with their suggestion blocks (or in `--notes`, when no remote carries a review) and are theirs to take or leave. If every finding you have is a nit, the verdict is `pass`.

That threshold is deliberately low, and it only works because a send-back is *bounded*: the loop ends when the worklist is answered, not when you run out of opinions. What keeps it bounded is the re-review discipline below — read it before your second pass on any item.

## Re-reviews

Work comes back to you two ways. A `not_ready` from the ship gate arrives with **no implement run in between**, so the diff is the one that already passed: nothing is wrong with your earlier verdict, the human is asking for something it didn't cover. Take their ask as the finding, confirm the diff hasn't moved under you, and write the worklist as you would for any send-back. Otherwise the implementer has reworked, and the rules below apply.

- **Read the delta; use the full diff only for context.** Your last posted review opens with the sha it reviewed (**Reviewed at**) — diff from it (`git diff <that-sha>...HEAD`) to see what actually changed. Don't restart a broad scan of code you already cleared. If no sha was recorded, fall back to the whole change diff, and record one this time.
- **Give every earlier finding a disposition, in its own thread.** A claimed fix is a claim: check each against the code, then reply in that thread — a fix you verified gets a one-line confirmation and you **resolve the thread** (you raised it; you close it); one still open gets a reply saying exactly what's missing. A *reasoned* decline is a product decision and stands — acknowledge it and resolve; overturn it only with concrete correctness or security evidence, not a restated preference. Threads a *human* opened are theirs to resolve, never yours — reply only. A finding you carried in a review **body** (no anchor) has no thread — disposition it in your next review's body. (`factory feedback` prints the reply/resolve one-liners.)
- **Don't invent new suggestions about old code.** A new `💡 [SUGGESTION]` is legitimate only about code the rework introduced or changed. If something sat in the diff at an earlier pass and you didn't flag it then, it is settled — a fresh opinion is not a new finding, and it now costs a full loop. `🚨 [CRITICAL]` and `⚠️ [IMPORTANT]` you may raise at any pass, anywhere in the diff — another loop costs less than a shipped defect.

## Output contract

On a **pass**:
```
factory advance <id> --verdict pass --summary "<why it's sound>" --confidence <0..1> \
  [--notes "<for the ship gate: council synthesis + any split, judgment calls you accepted>"]
```
Notes are optional on a pass — use them when the ship-gate human needs context beyond the headline (a council ran, you accepted a debatable judgment call). If the item looped, mention what the loop was about — the ship gate reads the PR threads but deserves the one-line arc.

On a **send-back**, the review lives on the change PR — where review conversations belong, and where your reasoning survives your context ending. Post **one review per pass** via the API, so the summary and the inline findings land together (build the payload in your scratchpad):

```
gh api repos/{owner}/{repo}/pulls/<change-pr>/reviews --input review.json
```
(An `automatable` item has no change PR — post on the item's own `pr`, the one carrying the diff.)

- `review.json`: `{"event": "COMMENT", "body": "<summary>", "comments": [{"path": …, "line": …, "side": "RIGHT", "body": "<finding>"}, …]}`. `event` is always `COMMENT` — never `REQUEST_CHANGES`/`APPROVE`, which GitHub refuses on a PR your own token opened, and which would be redundant anyway: routing is the engine's job (`--verdict` is what sends work back), not GitHub review state's.
- The **body** opens with `Reviewed at <sha>` — the change-branch head you read; the next pass diffs from it — then the rationale a one-liner can't hold (what you traced, why each severity is what it is) and a **Checked and sound** list, so the next pass doesn't re-litigate what you cleared. End it with `<!-- factory:code-review -->` on its own line, the marker that tells `factory feedback` a machine wrote it.
- Each **inline comment** anchors one finding to the line it's about (`side: "RIGHT"`; `"LEFT"` for a deleted line), opens with its severity tag, and carries its *why* — a finding without a why invites a mechanical fix that misses the point. `🧹 [NIT]`s ride along here with their ```suggestion``` blocks. End each with the marker too.
- Only a line that appears in **this pass's diff** can anchor an inline comment, and the POST is all-or-nothing: one bad `path`/`line` rejects the whole review (HTTP 422), usually without naming the offender. So a finding about an untouched line goes in the review **body** with its `file:line` quoted from the start; if the POST still 422s, move the finding you suspect into the body — or all inline findings, if the error doesn't say — and retry. Degrade the anchor, never drop the finding.
- **No remote, or no `gh`:** the same content — `Reviewed at` sha, numbered severity-tagged worklist, rationale, checked-and-sound — goes in `--notes` instead.

Then:
```
factory advance <id> --verdict changes_requested --summary "<headline>" \
  --confidence <0..1> --notes "<the review's URL, plus anything it doesn't carry>"
```
`changes_requested` routes back to implementation. The implementer answers each finding in its own thread, so the loop accumulates as one readable conversation on the PR instead of evaporating with each fresh context. Vague asks cause loops.

## Quality bar
- Findings must be concrete, actionable, and open with their severity tag. "Looks good" without having traced the criteria is not a review.
- Prefer fewer, higher-confidence findings over a long speculative list.
