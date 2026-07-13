---
name: council
description: Convene a council of subagents to investigate one contested question from genuinely different angles in parallel, then synthesize by evidence quality into a single recommendation — with an optional cross-critique second round when the seats diverge. Use for consequential decisions with no single right answer (architecture, UX-affecting design, performance/caching strategy, data/privacy, auth, cost or tech-debt tradeoffs), for review of high-risk changes, or whenever the user asks for a council, second opinions, red-teaming, or parallel investigation.
---

# Council

Coordinate several subagents investigating the same question — differentiated first by **angle**, second by model — then synthesize their reports into one recommendation. The point is to simulate a good team in a room: different priorities, different expertise, different failure modes in mind, so the answer doesn't miss what one perspective alone would.

## When to convene

The trigger is **consequential + contested**: the decision matters, and reasonable approaches genuinely disagree. That's broader than "dangerous." Good fits:
- Architecture or code-structure choices, API shape, extensibility tradeoffs.
- Choices that shape UX or product behavior.
- Performance work — caching strategy, query shape, "is this optimization worth its complexity."
- Anything touching important resources: databases and migrations, user data and privacy, money, public APIs.
- Safety and authentication design.
- Cost tradeoffs — one option is better but more expensive to build or run.
- Tech-debt tradeoffs — robust-but-complex vs. simple-with-a-known-hassle; whether a vulnerability-shaped shortcut is acceptable *now* if logged, or must be fixed *now*.
- Review of high-risk diffs, incident root-cause, "is this alternative worth pursuing."

Skip it when a direct test would settle the question (verify, don't deliberate), and when any competent path is fine — a council burns real tokens, so spend it where the decision doesn't have a right answer, not on routine work.

## Where this runs in the factory

Two call sites, same skill:
- **The main/driver session** — the human asks for a council, or the driver folds one in at a human gate for a high-risk item.
- **Inside the Spec and Code-review stations** — those agents carry the `Agent` tool precisely so they can convene a panel as *nested* subagents when they hit a contested call, without a round-trip through the driver. Convene sparingly, per the trigger list above; the synthesis feeds the station's own verdict (e.g. code review emits `pass` or `changes_requested` informed by it) and gets summarized in the station's `--summary`/`--notes` so it reaches the gate packet.

When driven interactively by the human, tell them which seats you plan to launch and what each will investigate before spawning. A station convening mid-line proceeds without asking — the human sees the synthesis at the next gate.

## Assemble the roster

The council's value comes primarily from **angle diversity**. Every seat here is a Claude model, so running *different* models buys far less than it would across providers — two Claude models given the same prompt tend to converge, while two genuinely different angles given to the same model diverge. **The seat's prompt — the angle, the framing, the specific concerns you tell it to chase — is the highest-leverage knob.** Invest your effort there.

Default to **all seats on `opus`**, differentiated purely by angle. A `sonnet` or `haiku` seat is fine for a cheap mechanical sub-check, but never as a substitute for a distinct angle. Don't spend `fable` on council seats — its budget is reserved for the retro station.

A solid default three-seat roster:
- **Correctness & edge cases** — does it actually hold up? Hunt broken assumptions, boundary conditions, races, the cases the happy path ignores.
- **Pragmatic implementation & cost** — what does it take to build, test, and maintain? Feasibility, blast radius, testing and rollout burden.
- **Contrarian / red-team** — argue against the leading option. Surface hidden assumptions, simpler alternatives that were skipped, and the strongest case for *not* doing the obvious thing.

Swap in specialist seats to fit the question: security, performance, product/UX risk, data correctness, migration safety, operational/on-call impact.

## Brief identically, investigate independently

Launch seats with the **Agent** tool (independent seats in parallel), each with the same shared brief: the repo path or artifact locations, the branch/base context, the exact question, known concerns, constraints (read-only — no commits, no branches, no PRs — unless the task genuinely needs edits, in which case give each seat `isolation: "worktree"` so they can't collide), and the expected report shape. Express each seat's angle in its spawn prompt. If the full brief is long, put the essential question in the spawn prompt and deliver the rest via **SendMessage** right after.

Don't let seats see each other's work in round one — independence is what makes the diversity real.

Ask every seat for a structured report: (1) files/symbols/evidence inspected, (2) current behavior, (3) the option assessed, (4) correctness risks and edge cases, (5) implementation and testing cost, (6) recommendation — keep current, pursue alternative, or hybrid, (7) confidence and unknowns. If a report is thin or makes an unsupported claim, follow up with **SendMessage** to that same seat (it keeps its context) rather than spawning a replacement.

## Synthesize

Compare reports by **evidence quality, not vote count**. Produce a decision memo, not a transcript summary:

```markdown
## Recommendation
[One or two sentences with the decision.]
## Why
- [Evidence-backed reason 1..3]
## Tradeoffs and risks
- [Risk or caveat · testing/rollout implication]
## Final call
[The concrete next action.]
```

Name where the seats agreed and where they split, address the strongest objection head-on, and distinguish "do now" from optional future hardening.

## Round 2 — cross-critique (when the seats genuinely diverge)

If round one produced genuinely divergent proposals, don't synthesize the split cold — you'd be the bottleneck, seeing only the tradeoffs *you* happen to notice. Run a critique round first:
1. Collect each proposal — the core recommendation and reasoning, labeled neutrally (A/B/C), authorship anonymized where practical.
2. **Resume the same seats via SendMessage** — they critique from deep context; a fresh agent critiques cold. Send each seat the *other* proposals and ask for: the **pros and cons of each alternative** (both — an honest critique that credits a rival's strengths beats a reflexive defense), whether they'd **revise their own stance** having seen the alternatives, and a final ranking with confidence.
3. Synthesize the richer set. Convergence in round two is a strong signal; note the most incisive objection raised against each option and why the winner survives it.

Skip round two when round one already converges, or when a direct test would settle it faster.

## When the council can't settle it

Some splits are *supposed* to reach the human: genuine taste, product priorities, spend-vs-benefit calls. When the synthesis reveals one, don't bury it in the middle of a memo — put the fork and your provisional pick at the **top** of your output so the next station and the human gate see it. Inside a station, if proceeding would bake in an unreviewable guess, pull the escape hatch instead: `factory advance <id> --human-required --human-reason "<the call only a human can make>"`.

## Practical notes

- Keep council seats read-only unless the task explicitly involves edits.
- Don't expose internal subagent IDs in user-facing summaries.
- A council about code-review feedback marks findings resolved only after the underlying issue is actually addressed.
