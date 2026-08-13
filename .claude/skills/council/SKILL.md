---
name: council
description: Convene a council of subagents to investigate one contested question from genuinely different angles in parallel, then synthesize by evidence quality into a single recommendation — with an optional cross-critique second round when the seats diverge. It is the most expensive move available, so it is for the rare decision that is consequential, genuinely contested between sound approaches, unsettleable by a direct test, and whose outcome would actually change what gets built — architecture and API shape, irreversible schema/auth/data calls, UX-locking design, quality-vs-complexity tradeoffs, review of high-risk changes. Routine calls, anything a test would answer, and questions that just need facts gathered get a decision or a research subagent, not a panel. Also use whenever the user asks for a council, second opinions, red-teaming, or parallel investigation. In the factory, the spec and code-review stations convene councils on contested calls; the driver may also convene one before presenting a high-risk item at a human gate.
---

# Council

Coordinate several subagents investigating the same question — differentiated by **angle** — then synthesize their reports into one recommendation. The point is to simulate a good team in a room: different priorities, different expertise, different failure modes in mind, so the answer doesn't miss what one perspective alone would.

## When to convene

A council is judgment infrastructure, not a safety ritual — and it is the most expensive move you have, several full investigations plus a synthesis spent on a single question. It has to earn that against everything else the same budget could buy. Convene one only when all four hold at once: the decision is **consequential** (expensive to reverse, or it shapes how later work gets built), it is **genuinely contested** (reasonable, well-informed approaches disagree — not merely unfamiliar to you), it **can't be settled empirically** (no test, benchmark, or reproduction would answer it faster than deliberation would), and — the test that does the most work — **the outcome would actually change what you produce**. If you can already name what you'd recommend and expect the seats to agree, that's ratification, not deliberation; skip it and make the call.

The areas below *often* host such a decision, but none of them qualifies on its own — working in an important area is not the same as facing a contested fork inside it, and most work in every one of them is routine. Match on the four conditions, not on the topic:
- The load-bearing structural calls: architecture, API shape, extensibility, where a module boundary goes.
- Designs that lock in UX or product behavior.
- Performance strategy — caching, query shape, "does this optimization earn its complexity."
- Anything touching what you can't cheaply un-touch: schemas and migrations, user data and privacy, money, auth, public contracts.
- Quality-vs-complexity calls between *sound* designs — which one ages better, whether extra robustness earns the complexity it adds. (This is not a venue for ratifying shortcuts: when a path would knowingly incur tech debt, the default is to build it the right way — quality wins. Convene only when "the right way" is itself contested.)
- Review of high-risk diffs, incident root-cause, "is this alternative worth pursuing."

**Reach for the cheaper move first.** A council is what's left after these don't apply:
- A test, benchmark, or reproduction would settle it → run it. Verify, don't deliberate.
- Any competent path is fine, or one option is plainly stronger → make the call. Routine work gets a decision, not a panel.
- What you're missing is *facts*, not judgment — how something is used, what a subsystem does, what a long thread says → that's one research subagent, not several deliberating seats.
- The fork is genuine taste, product priority, or a spend-vs-benefit call → deliberation can't resolve those; they're a human's. Surface the fork with your provisional pick (see *When the council can't settle it*) instead of convening.
- A human reviews this work shortly anyway → put the fork in front of them there. Spending a council to pre-answer a question its decider is about to answer buys little.

And budget **one council per decision**: a well-framed council either settles the question or escalates it (round two below, then the human). Reconvening to re-ask the same question buys noise, not confidence.

## Who convenes it

Anyone with the `Agent` tool: a human asking directly, a main session mid-task, or a subagent embedded in a larger process (its seats then run as nested subagents). When a human is driving interactively, tell them which seats you plan to launch and what each will investigate before spawning. When running autonomously, proceed without asking — carry the synthesis in your output so it reaches the human at their next review point.

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

Run **every seat in a round on the same model**, so differences between reports reflect the angles, not the substrate. **`sonnet` is the default**, and the paragraph above is why: if the angle is the leverage and the substrate isn't, then buying the strongest model for every seat is paying a premium on the variable that matters least — several times over, for one decision. Never `haiku` — it isn't strong enough for judgment work.

Lift a round to `opus` when the **stakes** justify it, not when the topic sounds weighty. Any one of these is enough:
- **A wrong answer is expensive to undo** — a schema or migration, a public contract, an auth or data-privacy model, anything already live in front of users.
- **The reasoning is deep rather than wide** — the answer turns on interactions a fast read gets *confidently* wrong: concurrency and ordering, security arguments, invariants that must survive every state. (A question that mainly needs ground covered is the opposite case; that's breadth, and sonnet covers ground fine.)
- **A sonnet round came back weak** — seats hedging, thin evidence, or converging on something that doesn't hold up. Escalate the *next* round rather than restarting, and keep that round internally uniform.

When it's a close call, run sonnet and escalate if the reports disappoint: that path pays for one cheap round plus the expensive one only when it was needed, while starting on opus pays the expensive one either way.

Derive the angles from the question. **Two well-differentiated seats is the default**; add a third only when a distinct specialist angle genuinely applies. Each seat is a full investigation, so the count is a cost, not a thoroughness dial — two non-overlapping seats beat five vague ones, and no seat should be askable as "review the architecture, generally." Useful angles include:
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

**A seat that returns nothing is a condition to handle, not a fact to reason around.** If a report is empty, truncated, or never arrives, you have fewer angles than you convened — which is the one thing the council was buying. Re-ask that seat via **SendMessage** first; if it still comes back empty, spawn a replacement for that angle, and if neither works, say plainly what you're missing rather than synthesizing around the hole. Never present a recommendation as a council's when the council didn't report: a synthesis of one silent seat and one live one is a single opinion wearing a panel's authority, and whoever reads it next has no way to tell.

Then compare reports by **evidence quality, not vote count**: lead with the recommendation; call out consensus and disagreements; explain why the winner wins against the decision criteria; distinguish "do now" from optional future hardening; name confidence and material unknowns. Produce a decision memo, not a transcript summary.

**Persist the synthesis; the raw reports are working material.** The memo is the artifact — it's what the caller acts on and what a human reads later. If seats write their reports to disk (long investigations, or a process where a seat's context may not survive), those files are scratch: fold what matters into the memo and don't hand them onward as the deliverable. A stack of dense reports is not a decision, and passing several of them to a human in place of one memo moves the synthesis work onto them, which is exactly the work the council existed to do.

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

Some splits are *supposed* to reach the human: genuine taste, product priorities, spend-vs-benefit calls. When the synthesis reveals one, don't bury it in the middle of a memo — put the fork and your provisional pick at the **top** of your output so whoever reads it next (the caller, the next agent in the process, the human reviewer) can't miss it. And if you're running autonomously and proceeding would bake in an unreviewable guess, don't proceed — use whatever escalation path your process provides to put the decision in front of a human first.

## Practical notes

- Keep council seats read-only unless the task explicitly involves edits; edit councils follow the repo's normal version-control rules in isolated worktrees.
- Don't expose internal subagent IDs in user-facing summaries.
- A council about code-review feedback marks findings resolved only after the underlying issue is actually addressed.
