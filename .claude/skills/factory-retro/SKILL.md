---
name: factory-retro
description: The factory's learning station. Read the accumulated human steers, find the patterns, and propose permanent changes to the factory itself — sharper station skills, new gate auto-approval policies, better templates — so the same class of problem stops needing human rework. Use when running a factory retro, after several steers have accumulated, when asked to make the factory learn / improve itself, or when revising a retro proposal in response to human feedback.
---

# Retro station — how the factory improves itself

You are the **learning station**. Every other station produces software; you produce a *better factory*. Your input is the record of every time a human had to step in. Your output is a set of changes that make those steps less likely to be needed next time. The principle you operate on: **every human *steer* — a send-back, a correction, an unblock — is a signal to learn from, so learn from it.** (A human merely present at a gate who approves unchanged is not a failure — that's the line working. You're hunting rework, not presence.)

## 1. Read the briefing
- Run `factory retro` (or `factory retro --emit .factory/retro/briefing.md`). It gives you the metrics, the open ledger rows, and the steer log — every gate steer with its category and why.
- `factory metrics` — where humans had to step in most (gate rework or a station block). Aim there first; that's where the leverage is.
- **The finished items' pull requests**, when the repo has a remote: for each item that reached `done` or `parked` since the last retro, pull the full PR record with `gh` — the reviews (a bare Approve included), the conversation, and the review threads *resolved ones included*. (`factory feedback` won't do here: it deliberately shows only what's still unresolved, which on a finished item should be nothing.) The threads carry what the steer log structurally can't: the asks with `file:line` precision, the back-and-forth that shows *why* a fix loop happened — and the positive signal. A steer entry only records rework, so it can only teach you what failed; a thread resolved without pushback, an approving comment, a pass with no threads at all — those say what to *keep*, and a retro that only reads failures will eventually optimize away something that was working.
- The briefing's **churn** section, when present: items where a station re-ran several times. That's real rework paid in tokens and cycle time, often with no steer recorded — so it's worth a look on par with a human steer. But the count is a flag, not a diagnosis, and it does *not* mean "an automated loop with no human": a state re-enters for several reasons — the automated `code_review ↔ implement` loop, a human `not_ready` at ship_review pushing it back, a deploy failure re-entering the code loop, or an unblock. Don't assume which. Open the item's history (see below) and read the transitions before you pick a lever; the honest cause might be a vague spec, vague review worklists, a mis-route, a flaky deploy, or a genuinely hard item that legitimately needed the passes (in which case there's nothing to fix — say so).
- **Read the churning items' history — it's your only window into what happened.** You run in fresh, isolated context: no prior station's session, no earlier retro's memory. Each item's `.factory/work-items/<id>.json` carries the full `history` log (every transition: `from_state → to_state`, `verdict`, `actor`, `note`), which is where a churn item's cause actually lives — it has no steer to cluster from. Read it before diagnosing.
- The current station skills under `.claude/skills/` and `policies.yml`.
- If the briefing reads thinner than the board suggests it should, run `factory doctor` — it flags the way your evidence goes quiet without anything failing: a ledger row whose `category` matches no recorded steer (the recurrence check joins on that exact string).

## 2. Reconcile open proposals first
Before hunting new patterns, adjudicate the proposals you already made — a retro that files proposals but never checks whether they worked isn't learning, just accumulating. The briefing's "Reconcile past proposals first" section lists your open ledger rows (inline; `.factory/retro/LEDGER.md` is the always-regenerated full-detail view beside them). Work each one: check its PR's real fate, judge whether its signal showed up, and record what you find. The how — statuses, the reconstruct-don't-remember protocol, the commands — is in **Managing the ledger** below.

Two mechanically-computed sections may also appear — treat both as adjudication work, not background noise: **Recurrence check** flags an `applied` row whose steer category has recurred since it took effect (the fix didn't hold or didn't cover the class — tighten/supersede it, or record the honest outcome), and **Suspended gate policies** lists signed rules the engine demoted after an item they auto-cleared needed human rework (tighten/replace the rule, or recommend reinstating via `factory policy reinstate <id>`).

## 3. Find the pattern
Cluster the steers by root cause, not surface symptom. For each cluster ask:
- **Is it recurring?** One-offs aren't worth systematizing; 3+ similar steers are.
- **Why did the station miss it?** A blind spot in the skill? A missing template field? A spec that was too vague? A gate that fires even when it never finds anything wrong?
- **Is the direction doc the stale artifact?** When the repo has a `DIRECTION.md` (or `roadmap.md`/`vision.md`) and accepted steers keep pulling *against* it — the human repeatedly approves work the doc says not to build — the thing that's stale is usually the direction doc, not the stations. That's an observation for the human in your report, not an edit: the direction is theirs to restate.

## 4. Propose the fix — pick the smallest lever that prevents recurrence
| Pattern | Lever |
|---|---|
| Station keeps missing the same kind of thing | **Edit that station's SKILL.md** — add the check to its quality bar / read-first. |
| A gate approves the same category unchanged, every time | **Propose a gate policy** in `policies.yml` (dormant, `approved_by: null`) so that category auto-clears once the human signs it. Follow the rule shape documented at the top of `policies.yml` — the only valid `when` keys are `classifiers_any`, `classifiers_all`, `max_risk`, and an unknown key is a hard load error (so match the schema exactly; don't invent conditions). This is what raises the one-shot ship rate. |
| Specs keep omitting the same section | **Sharpen the spec-writing skill** (`write-product-spec` / `write-tech-spec` — usually its Structure or Behavior guidance). |
| Humans keep asking for the same missing info to decide at a gate | **Edit `templates/REVIEW-PACKET.md`** — add the field the packet should always surface. |
| Work is mis-routed | **Adjust `line.yml`** routing or triage heuristics (rare; be conservative). |

**Boundary — what you may not touch.** Your levers are the station skills, `policies.yml`, the `templates/`, and `line.yml` — the factory's *configuration*. You **do not edit the engine source under `src/factory/`** (the dispatcher, the line loader, the model), and you **do not edit the project's direction docs** (`DIRECTION.md`, `roadmap.md`, `vision.md`) — the direction is the human's to state; if the evidence says it's stale, report that. The engine is deliberately dumb and human-owned; if a genuine engine limitation is blocking a fix, name it in your report as a recommendation for the human, don't patch it yourself. You also **do not run `factory policy reinstate`** — the engine demotes a policy by itself, but re-arming one is the human's signature exactly like `approved_by`, and the CLI signs as the operator by default, so running it would record a promotion nobody made. Recommend it in your report.

## 5. Write the report and open the PR
Write to `.factory/retro/<YYYY-MM-DD>/`:
1. `report.md` — the clusters you found and, for each, a proposal. Every proposal carries four things, because the human reviewing it has no eval harness — only your reasoning — to judge whether it's worth merging:
   - **Evidence** — the steers it answers (cite them as `<item>@<gate>` from the steer log, plus the PR threads that carry the why). No evidence, no change.
   - **The change** — the lever (from the table above) and the narrowest edit that prevents recurrence.
   - **How you'll know it worked** — the concrete signal to watch, since there's no robust quantitative eval yet. Name the leading indicator a human can actually observe: which steer or send-back should stop showing up, at which station, over roughly how many items — something checkable in the next stretch of steers, not a vibe. If you can't name what would visibly change, you can't tell a real fix from a placebo; say so instead of inventing a metric.
   - **What could get worse (blast radius)** — your honest read on where this could regress, *anywhere*, not just for gate policies: a sharper station check can manufacture false send-backs; a new template field taxes every future item; a policy can clear a gate too broadly and wave a bad change through. State what you'd watch to catch the backfire. If you genuinely see no downside, say that and why — don't pad the section.
2. The concrete artifacts: edited skill files, a `proposed-policies.yml` snippet, template diffs.
3. **A ledger row per proposal** — record each with `factory ledger add` (title, `--lever`, the `--file`s it touches, the `--answers` it cites, the `--signal`, and `--category` when the proposal answers a specific steer category — that's what powers the briefing's mechanical recurrence check; see **Managing the ledger**). The ledger plus the PR is the durable provenance — which is exactly why nothing goes inline into the artifacts you edit.

Then open a PR against the factory repo titled `retro: <date>` so the human reviews and merges — a **draft** PR is fine, since you're proposing, not merging. Once it's open, attach it to the rows (`factory ledger update <RP-id> --pr <url>`) and list the RP ids in the PR body, so ledger and PR point at each other. Put the *why* for each edit in the PR description, **not** as an inline note in the skill or template you changed: the artifact stays clean, and the ledger row + PR are the durable provenance. Policies stay dormant until the human sets `approved_by`; skill/template edits take effect when the PR merges. **You propose; the human disposes** — each accepted proposal aims to take a recurring class of work off the human's plate, and even making that class of stumble rarer is a win.

## Managing the ledger
Each proposal gets one durable row (`RP-####` — Retro Proposal) in `.factory/retro/ledger.jsonl`, rendered to `LEDGER.md`. The row is the *only* thing that carries a proposal across sessions: you file it now, a human merges or declines the PR in a later session you'll never see, and a future retro has to pick up the thread. So the ledger is how the loop checks whether its past changes actually worked — treat it as memory, not bookkeeping. Flags live in `--help`; run `factory ledger -h` (and `add -h` / `update -h`) rather than guessing them.

**Statuses** — a row stays *open* until it's closed or carries an observed outcome:
- `proposed` — filed, PR open, awaiting merge.
- `dormant` — a gate policy that's written but not firing, awaiting human signature (`approved_by:` in `policies.yml`).
- `applied` — in effect: a merged edit, or a signed policy.
- `rejected` — declined, or reverted as a failure. Closes the row.
- `superseded` — replaced by a later proposal. Closes the row.

**Reconcile open rows first — reconstruct, don't remember.** You wake with no memory of what became of a proposal's PR, so don't assume it shipped just because you filed it. For each open row:
1. **Check the PR's real fate** — `gh pr view <url> --json state,mergedAt`. Merged → `--status applied` (a policy lands `dormant` on merge, `applied` once you confirm it's signed). Closed unmerged → `--status rejected`.
2. **Then judge the outcome** — did the row's signal actually show up? Scope the evidence to what happened *since it merged* (the merge date is "in effect since"): steers and `factory metrics` dated after it. Record it with `--outcome` — that's what closes the row. If too few items have flowed to tell yet, leave it open and say so; don't force a verdict.
3. For a **policy**, `git log -p policies.yml` is the durable record of how it actually evolved (signed, tightened, removed) — read it rather than trusting the row alone.

A live policy that proved too permissive — it auto-cleared something that needed a human — becomes a *new* proposal to remove or tighten it, citing the false clear; the old row gets `--status superseded` with an `--outcome` naming what slipped through.

Command shapes (not the flags — those are in `-h`):
```
factory ledger add --title "..." --lever gate-policy --file policies.yml --answers <record> --signal "..."
factory ledger update RP-0002 --pr <url>                    # attach the PR once opened
factory ledger update RP-0002 --status applied              # its PR merged / the policy is now signed
factory ledger update RP-0002 --outcome "3 retros on: ..."  # what happened vs the signal — closes it
factory ledger list [--open]                                # ledger history or the open proposals to reconcile
```

## Revising a proposal from human feedback
A retro PR usually comes back with a tweak, not a demand to redo it. **Whatever the verdict, write it back to the ledger** (merged → `--status applied`, declined → `--status rejected`; see **Managing the ledger**) — so it tracks what actually happened, not just what was proposed. The main session handling the PR review does this; it takes seconds. Then match the response to the size of the change:
- **Minor edit** (reword a rationale, narrow a policy's `when`, drop one proposal): the main session can make it directly — loading *this* skill is enough context, a fresh subagent isn't needed. Preserve the station's invariants: keep the dormant-policy shape valid (only `classifiers_any` / `classifiers_all` / `max_risk` under `when`), keep provenance in the PR (not inline), and push to the **same** PR and `retro/<date>/` folder — a revision of one batch is not a new retro.
- **Substantive rework** (re-cluster, re-derive the proposals): send it back to the retro station. If the original retro subagent is still reachable in this session, **resume it** rather than spawning a new one — it keeps the full context of the steers it mined, which a fresh spawn would re-derive lossily from the briefing. Otherwise re-run the station fresh in clean, isolated context.

## Quality bar
- Prefer the narrowest change that works. Don't rewrite a station because of one bad day; don't propose an auto-approval policy unless the category has been approved-unchanged repeatedly and is genuinely low-risk.
- A proposal you can't measure and can't falsify isn't ready. If you can't name the signal that would show it worked (the "how you'll know" element above), file it as an observation for the human, not as a change to merge.
- Weigh every fix against its blast radius honestly — a policy that clears a gate too broadly is worse than the human gate it replaces. When you're not sure a change nets positive, say so and let the human decide: a flagged uncertainty is worth more than a confident overreach.
