---
name: council
description: Convene a council of subagents to investigate one contested question from genuinely different angles in parallel, then synthesize by evidence quality into a single recommendation — with an optional cross-critique second round when the seats diverge. Use for consequential decisions with no single right answer (architecture, UX-affecting design, performance/caching strategy, data/privacy, auth, cost or quality-vs-complexity tradeoffs), for review of high-risk changes, or whenever the user asks for a council, second opinions, red-teaming, or parallel investigation.
---

# Council

Coordinate several subagents investigating the same question — differentiated by **angle** — then synthesize their reports into one recommendation. The point is to simulate a good team in a room: different priorities, different expertise, different failure modes in mind, so the answer doesn't miss what one perspective alone would.

## When to convene

A council is judgment infrastructure, not a safety ritual. Convene one when three things are true at once: the decision is **consequential** (expensive to reverse, or it shapes how later work gets built), it is **genuinely contested** (reasonable, well-informed approaches disagree — not merely unfamiliar to you), and it **can't be settled empirically** (no test, benchmark, or reproduction would answer it faster than deliberation would).

That shape shows up across engineering, not just where something might break. Illustrations, not a checklist:
- The load-bearing structural calls: architecture, API shape, extensibility, where a module boundary goes.
- Designs that lock in UX or product behavior.
- Performance strategy — caching, query shape, "does this optimization earn its complexity."
- Anything touching what you can't cheaply un-touch: schemas and migrations, user data and privacy, money, auth, public contracts.
- Quality-vs-complexity calls between *sound* designs — which one ages better, whether extra robustness earns the complexity it adds. (This is not a venue for ratifying shortcuts: when a path would knowingly incur tech debt, the default is to build it the right way — quality wins. Convene only when "the right way" is itself contested.)
- Review of high-risk diffs, incident root-cause, "is this alternative worth pursuing."

Don't convene when a direct test would settle it (verify, don't deliberate), or when any competent path is fine — routine work gets a decision, not a panel. And budget **one council per decision**: a well-framed council either settles the question or escalates it (round two below, then the human). Reconvening to re-ask the same question buys noise, not confidence.

## Where this runs in the factory

Two call sites, same skill:
- **The main/driver session** — the human asks for a council, or the driver folds one in at a human gate for a high-risk item.
- **Inside the Spec and Code-review stations** — those agents carry the `Agent` tool precisely so they can convene a panel as *nested* subagents when they hit a contested call, without a round-trip through the driver. The synthesis feeds the station's own verdict (e.g. code review emits `pass` or `changes_requested` informed by it) and gets summarized in the station's `--summary`/`--notes` so it reaches the gate packet.

When driven interactively by the human, tell them which seats you plan to launch and what each will investigate before spawning. A station convening mid-line proceeds without asking — the human sees the synthesis at the next gate.

## Workflow

### 1. Frame the question

State the decision the council should answer in one sentence. Identify:
- the competing options or the hypothesis under review;
- the codebase, branch, PR, spec, or artifact to inspect;
- whether seats are read-only or may make code changes;
- the decision criteria: correctness, risk, implementation cost, testability, rollout safety, product behavior.

If the request is ambiguous, ask only the minimum clarification needed; otherwise choose sensible defaults and proceed.

### 2. Choose the seats

The council's value comes from **angle diversity**. Every seat here is a Claude model, so varying the model buys far less than varying the perspective — two seats on the same model with genuinely different angles diverge; two models with the same prompt converge. **The seat's prompt — the angle, the framing, the specific concerns you tell it to chase — is the highest-leverage knob.** Invest your effort there.

Run **every seat on the same model**, so differences between reports reflect the angles, not the substrate. `opus` is the default. Reach for `fable` when the question is the hardest kind on the table — dense with nuance and edge cases, where the strongest reasoning earns its cost (models that burn a lot of tokens should be treated as the exception, not a habit). `sonnet` is acceptable for a lighter council. Never `haiku` — it isn't strong enough for judgment work.

Derive the angles from the question: two or three genuinely non-overlapping seats beat five vague ones, and no seat should be askable as "review the architecture, generally." Useful angles include:
- an architect/correctness seat — does it hold up? broken assumptions, boundary conditions, races, the cases the happy path ignores;
- an implementation/testability seat — feasibility, blast radius, what it takes to build, test, and roll out;
- a specialist seat matched to the stakes — security, performance, product/UX risk, data correctness, migration safety, operational impact;
- a contrarian seat — argue against the obvious solution; surface hidden assumptions and the simpler alternative that was skipped.

### 3. Brief identically, launch in parallel

Give every seat the same shared brief: the repo path or artifact locations, the branch/base context, the exact question, relevant background and known concerns, required files/symbols to inspect if known, constraints (read-only — no commits, no branches, no PRs — unless the task genuinely needs edits, in which case give each seat `isolation: "worktree"` so they can't collide), and the expected report shape. Express each seat's angle in its spawn prompt, and launch independent seats in parallel. If the full brief is long, put the essential question in the spawn prompt and deliver the rest via **SendMessage** right after.

Don't let seats see each other's work in round one — independence is what makes the diversity real.

### 4. Ask for structured reports

Ask every council member to return:
1. exact file paths, symbols, docs, or evidence inspected;
2. the current behavior or implementation;
3. the option being assessed;
4. correctness risks and edge cases;
5. implementation and testing cost;
6. recommendation — keep current approach, pursue the alternative, or hybrid;
7. confidence and unknowns.

A common report shape is what makes the synthesis a comparison instead of a re-derivation.

### 5. Collect, then synthesize

Read each report as it lands — the useful output is the report, not the lifecycle status. If a report is thin on evidence or makes an unsupported claim, send a focused follow-up to that same seat via **SendMessage** rather than spawning a replacement — it retains its context; a fresh seat starts cold.

Then compare reports by **evidence quality, not vote count**: lead with the recommendation; call out consensus and disagreements; explain why the winner wins against the decision criteria; distinguish "do now" from optional future hardening; name confidence and material unknowns. Produce a decision memo, not a transcript summary.

## Final answer template

Use this shape unless the task calls for something different:

```markdown
## Recommendation

[One or two sentences with the decision.]

## Why

- [Key reason 1]
- [Key reason 2]
- [Key reason 3]

## Tradeoffs and risks

- [Risk or caveat]
- [Testing/rollout implication]

## Final call

[Concrete next step: keep current, pursue alternative, hybrid, run tests, etc.]
```

## Round 2 — cross-critique (only when the seats genuinely diverge)

If round one produced genuinely divergent proposals, don't synthesize the split cold. The seats did the investigating, so each now holds deeper context on the question than you do — synthesizing alone makes you the bottleneck, catching only the tradeoffs *you* happen to notice. Do what a good leader does with conflicting advice: put the advisors in a room and let them poke holes in each other's reasoning. Note the economics, too: round one was the expensive part, and the critique round reuses seats that already exist — so when the divergence is real, don't skip it to save tokens; it's the cheapest confidence available at that point.

1. Collect each proposal — the core recommendation and its reasoning, not the full transcript — labeled neutrally (A/B/C) with authorship anonymized where practical, so no seat bandwagons toward whichever proposal sounds most confident.
2. **Resume the same seats via SendMessage** — they critique from deep context; a fresh agent critiques cold. Send each seat the *other* proposals (not its own) and ask for: the **pros and cons of each alternative** (both — an honest critique that credits a rival's strengths beats a reflexive defense), whether they'd **revise their own stance** having seen the alternatives — and why or why not — and a final ranking with confidence. A thin or unsupported critique gets a focused follow-up to that same seat, not discarded.
3. Synthesize the richer set, and add a **"How the critiques shifted things"** section to the memo: where seats converged or changed their minds after seeing the alternatives (round-two convergence is a strong signal), the most incisive objection raised against each option, and whether it's decisive — or why the winner survives it.

Skip round two when round one already converges, or when a direct test would settle it faster. And round two is the *only* reconvene — if the question still isn't settled after it, that's a human call now; escalate, don't re-poll.

## When the council can't settle it

Some splits are *supposed* to reach the human: genuine taste, product priorities, spend-vs-benefit calls. When the synthesis reveals one, don't bury it in the middle of a memo — put the fork and your provisional pick at the **top** of your output so the next station and the human gate see it. Inside a station, if proceeding would bake in an unreviewable guess, pull the escape hatch instead: `factory advance <id> --human-required --human-reason "<the call only a human can make>"`.

## Practical notes

- Keep council seats read-only unless the task explicitly involves edits; edit councils follow the repo's normal version-control rules in isolated worktrees.
- Don't expose internal subagent IDs in user-facing summaries.
- A council about code-review feedback marks findings resolved only after the underlying issue is actually addressed.
