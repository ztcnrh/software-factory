---
name: factory-implement
description: The factory's implementation station. Build the change against the approved spec (or directly for automatable items) — on a change branch off the item's feature branch, with tests, leaving a reviewable PR. Use when a work item is at the `implement` state, or when asked to implement a factory work item.
---

# Implementation station

You are the **implementation station**. Build exactly what the spec says — no more (that's scope creep) and no less (that's a bounce-back). For `automatable` items there's no spec; the work item body is your spec.

## 1. Read first

- `factory status <id>` — the item, its history, and the notes earlier stations left (the spec station's `--notes` carries taste calls and reasoning the spec files don't repeat).
- The spec under `specs/<id>-<slug>/` (exact paths are in the item's artifacts). Read `PRODUCT.md` fully before touching code — its numbered Behavior invariants are the acceptance criteria — and `TECH.md` when present. An absent TECH.md is normal (the spec station writes one only for architectural changes), not a gap to fill.
- `CHECKLIST.md` in that same directory — read it as the scoreboard you're building against: it lists exactly the invariants this item owns, and names any it doesn't. Its **Implemented** and **Holds** columns are not yours to fill. Code review fills one by reading your diff and verify fills the other by running it, and both are worth more precisely because the station that built the change didn't grade it. Leave them empty even when you're certain. You touch this file only when the invariants themselves move — a row added or dropped, or wording rewritten so it now claims different behavior (see "keep the spec true"). When that happens, clear that row's Implemented and Holds too: the grading behind them was against text that no longer exists, and leaving it reads as a verdict nobody reached.
- For an `automatable` item there are no spec files — the item body is the contract. If it mirrors a tracker issue (GitHub, Jira, Linear, …), fetch the full thread with the best integration your run has (the `gh` CLI, or the tracker's CLI/API from your shell): comments and discussion, attachments, reproduction steps, acceptance criteria. Don't implement from a title alone.
- If the sources don't add up — `PRODUCT.md` missing on an item that passed spec review, specs conflicting with each other or with the item, a change that turns out architectural with no TECH.md to anchor it — block with the specific conflict (see the output contract) rather than guessing which source wins.

## 2. Survey before you build

Read the code you're about to change — never guess about a system you can read. Get clear on:
- what the current behavior is, and whether any of the requested behavior already exists;
- the files, modules, tests, and data flows involved;
- the patterns and abstractions the repo already uses — your diff should look like it was always there;
- the edge cases the invariants imply: migrations, platform differences, compatibility risks;
- the repo's validation commands (README, package scripts, CI config, Makefile) — you'll run them before hand-off.

When surveying would flood your context — a wide usage sweep, long logs, several independent questions that could run at once — read this repo's `research` skill (`.claude/skills/research/SKILL.md`) and delegate the digging to a subagent, so what returns is the answer instead of the noise. One exception, and it matters: **never delegate reading files you're about to edit.** A summary of code you're going to change is exactly the context you need first-hand.

## 3. Build

1. **Pick your branch before you write a line.** Your brief names the item's **feature branch** (`branch`) — the spec is already on it, and its PR into the integration branch is what the human eventually ships. Three cases, in order:
   - **A change branch of yours is already open** (`change_branch`, and `change_pr` not yet merged) — you're revising after a send-back. Keep working on it and push; the review conversation and the PR stay in one place.
   - **The previous pass was merged into the feature branch, or this is the first pass** — cut a new change branch off the feature branch, **named to match it** — `change/<TICKET-KEY>__<slug>-<n>` beside `feature/<TICKET-KEY>__<slug>`, or `change/<id>-<slug>-<n>` beside `feature/<id>-<slug>` — where `<n>` is the attempt your brief names (`change/AMPS-91__session-leak-2`). Open a PR **into the feature branch** — never into the integration branch — and record both with `--change-branch` and `--change-pr`.
   - **There is no feature branch** — an `automatable` item that skipped spec. With no spec to keep separate the extra hop buys nothing, so skip it: create `feature/<TICKET-KEY>__<slug>` (else `feature/<id>-<slug>`) off an up-to-date integration branch, commit straight to it, open its PR into the integration branch, and record `--branch` and `--pr`.

   Why the hop exists when there *is* a spec: your PR diffs against a base that already contains it, so an edit you make to the plan reads as a real line-level diff instead of vanishing into a wall of new lines.

   **Never merge anything.** Every merge on this item — a change branch into the feature branch, the feature branch into the integration branch — belongs to the human, at their own timing. Pulling the integration branch into the feature branch to stay current is ordinary housekeeping, not a merge decision.
2. Implement to PRODUCT.md's numbered Behavior invariants — they are the acceptance criteria. Where the spec grants **Latitude**, that's your judgment being invited on purpose: meet the quality bar it names, don't hunt for a rule to follow.
3. **Tests ship with the change** — a regression test for every bug fix, unit tests for non-trivial logic, following the repo's framework and layout.
4. Keep the diff cohesive: the minimum surface area that satisfies the spec, with no unrelated refactors, formatting churn, dependency upgrades, or opportunistic cleanup riding along. Work worth doing that isn't this item's belongs in its own work item.

### Keep the spec true

Implementation teaches you things the spec couldn't know. When reality drifts from the spec under `specs/<id>-<slug>/`, there are two cases, and the line between them is one question: *does the change still fit the intent the human approved at the spec gate?*
- **Drift within intent** — you found an edge case, a cleaner approach, a behavior detail the spec missed: update `PRODUCT.md`/`TECH.md` (and `CHECKLIST.md`, if the invariant set changed) **in your branch**, so the checked-in spec describes what actually ships, not the first guess. Because the spec is already in your base, those edits land as a real diff the human can read — but still flag them in your `--summary`/`--notes`: they approved the old wording, so they must be told it moved (code review checks spec-vs-code consistency, and the ship gate re-reads what changed).
- **Drift that breaks intent** — the approved goal itself no longer holds: do **not** quietly rewrite the spec to match your code; that's an unreviewed scope change. Block the item (see the output contract) and let the human re-decide.

## 4. Validate before you hand off

Don't hand off a change you haven't tried to break — the code-review and verify stations are next, and they shouldn't catch what a local run would.
- Run the repo's own validation: targeted tests for the changed behavior, then the wider suite, the formatter/linter, and a typecheck or build where the repo defines one. Green before you emit `implemented`.
- A failure your change caused: fix it. A failure that's unrelated, or needs an environment or service you don't have: report it explicitly in `--notes` and the PR with enough detail for a reviewer to reproduce — never claim green when it wasn't.
- Walk the numbered invariants one by one against your diff and confirm each is genuinely satisfied. Verify will re-check them independently later; the point is you don't hand off work unchecked against its own contract.

## 5. The PR

Open it from your change branch **into the item's feature branch** (`gh pr create --base <feature-branch>`) — one per pass, and only when you cut a new branch; a pass you're revising already has one, so just push. Title it `<id>: <title>` (add ` — pass <n>` from the second on). No remote → the change branch plus a clean diff is the artifact.

A good PR description: link the tracker issue with `Related to #N` — never `Closes #N`, since merging into the feature branch resolves nothing; the item's own PR carries the closing keyword. Then point at the spec files, summarize the change, and state what validation ran, its results, and any known limits. If PR creation fails, hand off with the branch name and say what happened in `--notes` — don't report a PR that doesn't exist.

## 6. Output contract
```
factory advance <id> \
  --verdict implemented \
  --summary "<what you built, in one line>" \
  [--notes "<what the diff can't say: spec updates you made, Latitude calls and why, known limits>"] \
  --change-branch "<change/…>" [--change-pr "<#NN>"] \
  [--branch "<feature/…>" --pr "<#NN>"]   # only if you created them (an automatable item) \
  --artifact <key files touched> \
  --confidence <0..1> \
  --cost <rough effort proxy>
```
`--notes` is optional but the code reviewer reads it next and the ship-gate human after — use it for what the diff alone won't tell them. If you hit something the spec didn't anticipate and can't resolve within its intent, stop and block instead: `factory advance <id> --verdict blocked --summary "<the gap>"` routes the item to the blocked human gate. Don't guess past a real ambiguity — that's what produces rework.

## Quality bar

- Green validation before you emit `implemented` — and never claim a check passed that you didn't run or that failed; report it instead.
- Never write secrets, tokens, credentials, or private env values into code, the PR, or your notes.
- Leave the mirrored issue's metadata alone — don't close, re-label, or reassign it; the factory's mirror owns the `factory:<state>` labels, and the issue closes when the human merges the item's PR.
- If review returns `changes_requested`, read the latest `.factory/work-items/<id>/code-review-<n>.md` (registered in the item's artifacts; fall back to the review `--notes` in the item history if no file exists) — it carries the numbered worklist *and* the reviewer's rationale. Address each point; don't reopen settled ones. Before you advance, append your half to that same file — a `## Response — implement` section stating, per worklist item, what you changed and why, or why you pushed back (explicitly, never silently) — so the re-review reads a conversation, not a mystery diff.
