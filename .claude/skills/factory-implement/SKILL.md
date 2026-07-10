---
name: factory-implement
description: The factory's implementation station. Build the change against the approved spec (or directly for automatable items) — on a branch, with tests, leaving a reviewable diff/PR. Use when a work item is at the `implement` state, or when asked to implement a factory work item.
---

# Implementation station

You are the **implementation station**. Build exactly what the spec says — no
more (that's scope creep) and no less (that's a bounce-back). For `automatable`
items there's no spec; the work item body is your spec.

## Read first
- `factory status <id>` and `specs/<id>/PRODUCT.md` + `TECH.md` if present.
- The codebase conventions. Match the surrounding code's style, naming, and test
  patterns — your diff should look like it was always there.

## Build
1. **Branch first.** `git checkout -b factory/<id>__<slug>` (never commit to the
   integration branch). If the repo follows a ticket convention, honor it.
2. Implement to the acceptance criteria. Touch the minimum surface area.
3. **Tests ship with the change** — a regression test for every bug fix, unit
   tests for non-trivial logic, following the repo's framework and layout.
4. Run the repo's formatter/linter/tests locally; get them green before handing off.
5. Stage a reviewable change. Open a PR if a remote exists (`gh pr create`),
   otherwise leave the branch + a clear diff. Do **not** merge.

## Output contract
```
factory advance <id> \
  --verdict implemented \
  --summary "<what you built, in one line>" \
  --pr "<#NN or branch name>" \
  --artifact <key files touched> \
  --confidence <0..1> \
  --cost <rough effort proxy>
```
If you hit something the spec didn't anticipate and can't resolve within its
intent, stop and pull the escape hatch: `--human-required --human-reason
"<the gap>"` (no verdict needed). Don't guess past a real ambiguity — that's
what produces rework.

## Quality bar
- Green formatter, linter, and tests before you emit `implemented`. The code-review
  and verify stations are next; don't make them catch what a local run would.
- If review returns `changes_requested`, the review notes are your worklist.
  Address each point; don't reopen settled ones.
