# Principles

What this factory is and where it's going. `CLAUDE.md` holds the working rules for changing this repo; `FACTORY-MANUAL.md` explains operating it; `docs/ARCHITECTURE.md` explains how the current build works. This doc is the one to check a *proposal* against — when a change is defensible under the rules but wrong for the factory, the disagreement lives here.

Where a principle already has an operative rule, this points at it instead of restating it. A gap is noted where we don't hold the principle yet — those are anchors, not apologies.

---

## 1. Dumb conveyor, smart stations

The engine decides *what happens next*; stations decide *what the work should be*. The split is what makes routing unit-testable and intelligence swappable — and it's why the factory survives a model upgrade without a rewrite.

"Dumb" prohibits **natural-language interpretation**, not side effects. Deterministic work — managing worktrees, running the project's declared commands, hashing a diff — belongs in the engine precisely because it must not depend on a model's reading of anything. A mechanism is engine-appropriate when its output is the same for every caller.

## 2. The line's shape and the project's facts are data

`line.yml` already earned this: state names were de-hardcoded from the dispatcher three separate times, and each time the fix was to move the fact into the file rather than teach the code another name.

Project facts deserve the same treatment. Today a station rediscovers "how do I test this repo" on every run — that isn't flexibility, it's *non-deterministic* hard-coding, and a stale inference propagates from the spec through the diff into the review. Declared once, the engine can run it and the brief can render it.

*Gap today:* no project profile exists.

## 3. A claim is not evidence

Whatever the engine can check itself, it checks. Whatever it can't, it records as a claim and labels it one. The point isn't distrust — it's that a station shouldn't have to decide whether three failing tests are "pre-existing." Taking that judgment off the agent's plate makes its job smaller, and makes a count of completed items mean something without re-reading every diff.

*Gap today:* every station verdict is a claim, and the engine observes neither the diff nor an exit code.

## 4. Nothing the factory accepts disappears

The operative rules are in `CLAUDE.md`. The direction is that this stops being vigilance and becomes structure: a field with no reader should fail the suite, not wait for someone to notice. We have shipped three write-only fields; the fourth should be impossible rather than unlucky.

## 5. Context is an artifact, not a memory

What a station was fed is a file on disk, regenerable from durable state. Sessions end, artifacts don't — so every handoff a later run depends on must have landed somewhere before the context that produced it disappeared.

This is also the only path to ever *evaluating* the prompt layer: a packet you can reproduce is a packet you can replay against a changed skill. Prompt engineering becomes engineering at exactly the point the input stops being improvised.

## 6. Loops converge and terminate

Every path back into a station carries the reason it came back. A bounded loop without feedback doesn't converge — it just fails faster.

Termination is the other half, and the failure should be a receipt, not always a question. An item that spun without progress, blew its budget, or hit an unrecoverable check has a durable answer already; routing it to a human gate asks them to supply one that exists.

*Gap today:* every loop dead-ends at `blocked`, and the only brake is a run counter — nothing notices "same change, same failure."

## 7. Humans gate taste and consequence; evidence gates correctness

People sit where judgment can't be priced: what to build, and whether to ship. Not at verification, not at retries, not at routine review — those have better arbiters. Human attention is the scarce input, and spending it on something an exit code could settle is the most expensive mistake the line can make.

The goal is never zero humans. It's zero human *rework* — a gate that's a rubber stamp is the line working, not the human being redundant.

## 8. Autonomy is earned by outcomes, revoked automatically, granted only by a human

Demotion is already automatic: a rule that waved through work needing rework suspends itself. Earning is the missing half — a rule should be able to run *shadowed* (evaluated and logged, never applied) long enough to show what it would have done, then promote against observed outcomes.

What the human signs is a conditional delegation, once — not each instance, and not a blanket exemption.

## 9. The item is the unit of isolation, ownership, and parallelism

One worktree, one branch, one lease per item. Never fan out inside a station — parallel work on one branch collides, and the item boundary is the only line that already has a clean state model behind it.

Sequential single-player is a ceiling, not a design. A factory that can only move one thing at a time limits throughput to one person's attention span.

*Gap today:* no worktrees, no leases, one item at a time.

## 10. The factory travels with the project; the control room spans them

Taste accumulates *in* the repo — station skills, conventions, `CLAUDE.md` — versioned and reviewed like code, because that context is what makes a station understand this codebase rather than software in general. That's the asset the whole flywheel is compounding, and it can't live in a central database.

The board, the queue, the metrics, and the integration seams (tracker, CI, sandboxes, cloud agents) belong outside any one repo. Adoption is a contract in both directions: what ships in, and what reaches back out.

---

## How we build

**Delete before you add.** Question the requirement first and attach a name to it; then remove; only then simplify, speed up, and automate. Optimizing something that shouldn't exist is the expensive mistake, and automating a wrong process just runs it faster. If we don't want roughly a tenth of a deletion back later, we didn't cut enough.

**A mechanism that exists to guard another mechanism is a smell.** Prefer removing the thing that needs guarding.

**Two consistent copies of a rule are worse than one home and a pointer** — they're only consistent until the next edit.
