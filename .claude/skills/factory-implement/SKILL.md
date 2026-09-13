---
name: factory-implement
description: The factory's implementation station, run headlessly by `factory run` on an issue labeled factory:implement. Build the change on the item's branch with tests and leave a pull request ready for review, or answer a review's send-back. Not for use inside a driver session.
model: sonnet
allowed-tools: Bash Read Grep Glob Edit Write Agent Skill WebFetch WebSearch
---

# Implementation station

Implement the issue named in the prompt and leave a pull request ready for review. Build exactly what the spec says: no more (scope creep) and no less (a send-back).

## 1. Read first

```
gh issue view <n> --json title,body,labels,comments
```

Then, in order of authority:

- `specs/<n>-*/PRODUCT.md` and `TECH.md` on the branch, when they exist. Read them completely before touching code; the numbered Behavior invariants are the acceptance criteria. Newer issue comments and gate comments can supersede them. An absent `TECH.md` is normal.
- For an `automatable` item there are no specs; the issue thread is the contract.
- `factory threads <n>` when the prompt names a PR. Unresolved threads mean a loop-back after a review's send-back: that list is your worklist. Every `🚨 [CRITICAL]`, `⚠️ [IMPORTANT]`, and `💡 [SUGGESTION]` needs an answer; `🧹 [NIT]` items are yours to take or leave. A draft PR with no threads is the spec station's hand-off: a first pass.

If the sources conflict, or the change turns out much larger or more ambiguous than the specs assume, report `blocked` with the specific conflict instead of guessing which source wins.

## 2. Survey before you build

Read the code you are about to change: current behavior, the files, tests, and data flows involved, the patterns the repo already uses, the edge cases the invariants imply, and the repo's validation commands (README, package scripts, CI config, Makefile). Never delegate reading a file you are about to edit.

## 3. Build

- **Branch.** The prompt says whether `feature/<n>-<slug>` exists. Exists: the checkout is on it; commit there. None yet: `git checkout -b feature/<n>-<slug>` from the current HEAD.
- Make the smallest cohesive change that satisfies the invariants. Where the spec grants **Latitude**, meet the quality bar it names with your own judgment.
- **Tests ship with the change**: a regression test for every bug fix, unit tests for non-trivial logic, in the repo's framework and layout.
- Follow existing style and architecture. No unrelated refactors, formatting churn, dependency upgrades, or opportunistic cleanup.
- Comments document current state only. Nothing you write into the repo's tree (code, comments, docstrings, test names) cites a spec file or an invariant number; state the reason inline or leave it out. Provenance belongs in the commit message and PR body.
- **Keep the spec true.** When implementation teaches you something the spec missed and the change still fits the approved intent, update `PRODUCT.md`/`TECH.md` on the branch and say so in `notes`. When the approved intent itself no longer holds, report `blocked`; a quiet rewrite of the spec is an unreviewed scope change.

## 4. Validate

Run the repo's own checks: targeted tests for the changed behavior, then the wider suite, linter, and typecheck or build where defined. Green before you report. A failure your change caused, fix; a failure that is unrelated or needs an environment you lack, report explicitly in the PR and `notes` with enough detail to reproduce. Never claim green when it was not.

When specs exist, walk every numbered invariant against your diff and confirm each is satisfied or explicitly out of scope. Fix mismatches you caused; report stale spec text rather than claiming alignment.

## 5. Commit, push, PR

Commit with a clear message and `git push -u origin HEAD`. Unpushed work does not exist to the reviewer.

- **No PR yet:** `gh pr create --base <default branch> --title "#<n>: <title>" --body-file <file>`.
- **Draft PR from the spec station:** `gh pr ready <pr>` and `gh pr edit <pr> --body-file <file>`.
- **Loop-back:** push, then reply in every thread you answered, in that thread (`factory threads <n>` prints the reply command), with what you changed (name the commit) or why you declined. Declining is legitimate but explicit; a silent skip earns another send-back. Never resolve a thread: whoever raised it closes it.

The PR body links the issue with `Closes #<n>`, points at the spec files when they exist, summarizes the change, and states the validation commands run and their results, plus any known limits. Verify `gh pr view` returns a real URL before reporting.

## 6. Report

Your final message is JSON matching the schema you were given.

- `implemented`: `summary` is what you built and what validated it, in one or two sentences, plus the PR URL. `notes`: what the diff cannot say, such as spec updates you made, Latitude calls, known limits.
- `blocked`: `summary` is the specific gap or conflict and the decision needed.

## Guardrails

- Never merge, never close the PR, never force-push.
- Post no comments on the issue; the runner records your report.
- Do not implement from the title alone.
