# Principles

What this factory is and where it's going. Check a *proposal* against this: when a change is defensible under the working rules but still wrong for the factory, the disagreement lives here. A *Gap today* marks a principle we don't hold yet — an anchor, not an apology.

---

## 1. Dumb conveyor, smart stations

The engine decides *what happens next*; stations decide *what the work should be*. That split is what makes routing unit-testable and intelligence swappable, and it's why the factory survives a model upgrade without a rewrite.

The line's shape is data, not code. State names were de-hardcoded from the dispatcher three separate times, and each time the fix was to move the fact into `line.yml` rather than teach the code another name.

## 2. Evidence gates correctness; humans gate taste and consequence

Whatever the engine can check itself, it checks; whatever it can't, it records as a claim and labels it one. Not distrust — a station shouldn't have to decide whether three failing tests are "pre-existing", and a count of shipped items should mean something without re-reading every diff.

People sit where judgment can't be priced: what to build, and whether to ship. Not at verification, not at retries, not at routine review — those have better arbiters. Human attention is the scarce input, and spending it on something an exit code could settle is the most expensive mistake the line can make. The goal is never zero humans; it's zero human *rework*, and a gate that's a rubber stamp is the line working rather than the human being redundant.

*Gap today:* every station verdict is a claim, and the engine observes neither the diff nor an exit code.

## 3. Autonomy is earned by outcomes, revoked automatically, granted only by a human

Demotion is already automatic: a rule that waved through work needing rework suspends itself. Earning is the missing half — a rule should be able to run *shadowed*, evaluated and logged but never applied, long enough to show what it would have done, then promote against observed outcomes.

What the human signs is a conditional delegation, once. Not each instance, and not a blanket exemption.

## 4. Nothing important lives only in a session

Everything the factory takes in lands somewhere durable, and anything it can't use is refused at the boundary rather than swallowed. The direction is that this stops being vigilance and becomes structure: a field with no reader should fail the suite, not wait for someone to notice.

The same holds for what a station was fed — a file on disk, regenerable from durable state. Sessions end and artifacts don't, so every handoff a later run depends on has to land before the context that produced it disappears. It's also the only path to ever *evaluating* the prompt layer: a packet you can reproduce is a packet you can replay against a changed skill. Prompt engineering becomes engineering at the point the input stops being improvised.

## 5. Loops converge and terminate

Every path back into a station carries the reason it came back. A bounded loop without feedback doesn't converge — it just fails faster.

Termination is the other half, and the failure should be a receipt rather than another question. An item that spun without progress, blew its budget, or hit an unrecoverable check already has a durable answer; sending it to a human gate asks them to supply one that exists.

*Gap today:* every loop dead-ends at `blocked`, and the only brake is a run counter — nothing notices "same change, same failure".

## 6. The item is the unit of isolation, ownership, and parallelism

One worktree, one branch, one lease per item. Never fan out inside a station: parallel work on one branch collides, and the item boundary is the only line that already has a clean state model behind it.

Sequential single-player is a ceiling, not a design. A factory that moves one thing at a time limits throughput to one person's attention span.

*Gap today:* no worktrees, no leases, one item at a time.

## 7. The factory travels with the project; the control room spans them

Taste accumulates *in* the repo — station skills, the conventions a project builds up — versioned and reviewed like code, because that context is what makes a station understand this codebase rather than software in general. It's the asset the flywheel compounds, and it can't live in a central database.

The board, the queue, the metrics, and the integration seams — tracker, CI, sandboxes, cloud agents — belong outside any one repo. Adoption is a contract in both directions: what ships in, and what reaches back out.

---

## How we build

**Delete before you add.** Question the requirement first and attach a name to it; then remove; only then simplify, speed up, and automate. That order matters: automating a wrong process just runs it faster. If we don't want roughly a tenth of a deletion back later, we didn't cut enough.

**A mechanism that exists to guard another mechanism is a smell.** Prefer removing the thing that needs guarding.
