# Architecture

The factory is built from four layers, each independently understandable and replaceable. From the bottom up: a deterministic **engine**, a set of **stations**, the **triggers** that move work between them, and the **learning loop** that improves the whole thing. This document covers the first three; the fourth has its own doc ([LEARNING-LOOP.md](LEARNING-LOOP.md)).

## The core idea: a dumb engine + smart stations

The single most important design decision: **the orchestration is deterministic and testable; the intelligence is isolated in skills.** The Python engine never "thinks" — it's a state machine that knows the shape of the line and records what happened. Every judgment call (is this automatable? is this spec good? does this code match it?) lives in a Claude Code skill run by a subagent. This keeps the moving parts verifiable (the routing has unit tests) and the intelligent parts swappable (edit a skill, or point a station at a different model, without touching the engine).

So: **the dispatcher is the brain, Claude is the hands.** The dispatcher says "run the spec station next"; Claude runs it and reports a verdict; the dispatcher routes on that verdict and says what's next. Repeat until a human gate or a terminal state.

## Layer 1 — the engine (`src/factory`)

A small, dependency-light Python package (the `factory` CLI). The pieces:

- **`line.py`** loads `line.yml` and answers every question about the line's shape: is this state a station, a human gate, a terminal? what skill runs it? given a verdict, where does the item go? `line.yml` is the *single source of truth* for the conveyor — reshape the factory by editing it.
- **`model.py`** defines the three records that flow through the system: a **WorkItem** (a unit of work, mirrors a GitHub issue), a **StationReport** (what a station emits — its `verdict` drives routing), and a **GateDecision** (a human's call, with the structured "why" the learning loop needs).
- **`dispatch.py`** is the motor. `next_action()` is pure — it just reports what should happen for an item's current state. `advance()` records a station's report and routes the item. `gate()` records a human decision (and captures an intervention if you steered). `apply_auto_gate()` clears a gate via an approved policy. This file *is* the factory's control flow, and it's the most heavily tested. One deliberate exception to the routing table: a station report with `human_required` set sends the item straight to `blocked` — an escape hatch any station can pull when it hits something only a human can resolve, regardless of what routes exist from that state. (The station skills invoke it as `factory advance … --human-required`.)
- **`store.py`** persists work items as JSON under `.factory/work-items/`. Local is the source of truth.
- **`policies.py`** evaluates gate policies (Layer 4). **`metrics.py`** is the North Star ledger. **`interventions.py`** writes the learning records. **`retro.py`** assembles them into a briefing.
- **`cli.py`** is the thin command surface the `/factory` command and the GitHub Actions call into.
- **`adapters/github.py`** is an *optional* mirror: it keeps a GitHub issue's `factory:<state>` label in sync so the conveyor is visible in GitHub and the cloud workflows can trigger. Nothing depends on it.

The state machine is a faithful encoding of the factory diagram. The routing table in `line.yml` maps `(state, verdict) → next state`; `tests/test_line.py` pins every critical hop so a careless edit can't silently re-wire the line, and `tests/test_dispatch.py` drives full passes, loop-backs, the spawn-a-follow-up mechanism, and the parking case.

### States and routing (the diagram, in data)

Stations: `triage → spec → implement → code_review → verify → deploy`. Human gates: `spec_review`, `ship_review`, `needs_human`, `blocked`. Terminals: `done`, `parked`. The interesting routes:
- triage fans out four ways (spec / implement / needs_human / parked), exactly the diamond in the diagram.
- `spec_review --needs_revision--> spec` and `ship_review --not_ready--> code_review` are the backward loops — the motion the learning loop tries to eliminate. Every human gate can also `park → parked` (a recorded, revivable halt).
- `ship_review --approved--> deploy` — approval *is* merging the PR, which triggers the project's post-merge CI/CD. `deploy` is a single **external** station (no agent) that watches that workflow: `deploy --succeeded--> done` is the ship point, and `deploy --failed--> code_review` re-enters the code loop. The `shipped` metric is emitted here, keyed declaratively off the `deploy` state's `ships_on: succeeded` marker (see `line.ships_on`) rather than a hardcoded state name.
- The `monitor` station (continuous watch + auto-spawn a follow-up item) is **deferred** in v1 — a green deploy is the success signal, so the item is *done* when it ships. New post-ship work enters as fresh items (via a planned issues-watcher). The `spawn` mechanism that would feed it still exists on every station report. See [OPTIMIZATION-AREAS.md](OPTIMIZATION-AREAS.md).

## Layer 2 — the stations (`.claude/skills`, `.claude/agents`)

Each station is a **skill** (the "how" — a focused `SKILL.md`) paired with a **subagent** (the "who" — an isolated runner with the right tools and a cost-appropriate model). The split matters: skills are portable knowledge you can read and edit; subagents give each station its own context window so a long line doesn't pollute one conversation, and so cloud runs are isolated.

| Station | Emits (verdicts) | Model | Notes |
|---|---|---|---|
| **triage** | needs_spec · automatable · needs_human_clarification · park | sonnet | minutes, not investigation; assigns risk |
| **spec** | ready_for_review · blocked | opus | writes `specs/<id>/PRODUCT.md` (+`TECH.md`); planning leverage justifies the tier |
| **implement** | implemented · blocked | sonnet | branch + tests; opens a PR; never merges |
| **code_review** | pass · changes_requested | opus | correctness/security backstop before the ship gate; escalates high-risk to the `council` skill |
| **verify** | verified · failed | sonnet | exercises *behavior* (incl. browser), captures evidence |
| **retro** | (proposes; opens a PR) | fable | the learning station, top-tier model — runs rarely, see LEARNING-LOOP.md |

`deploy` is an **external** station (no agent) — it represents the post-merge CI/CD workflow, so the factory observes its outcome rather than running it. `monitor` (haiku; watches a shipped change and spawns a follow-up) is **deferred** in v1 — its skill/agent are parked under `deferred/` (the installer doesn't copy them) and it isn't a state on the line. See [OPTIMIZATION-AREAS.md](OPTIMIZATION-AREAS.md).

Two more skills, adapted from `warpdotdev/common-skills`, sharpen the high-stakes moments: **council** (a model-diverse panel investigates in parallel, you synthesize) and **cross-critique** (competing proposals critique each other). The Spec and Code-review stations reach for these on risky or contested calls.

A station's contract is simple: read the work item (`factory status <id>`), do the work, and finish by emitting a verdict via `factory advance`. That single call hands the item to the next station.

**Stations are stateless; continuity rides on durable state, not a live session.** Each station run is a fresh context (a subagent locally, a `claude -p` invocation in cloud), so there is no long-lived agent and no in-memory carry-over between runs — even across an inner loop like `code_review ↔ implement`. What the next run sees is whatever landed in durable state: the work item's `history` log (each transition's `summary` note), its `artifacts` (file paths), the PR/diff, and the `specs/<id>/` files. This buys determinism, cloud-resumability, and no context-window rot down a long line — at the cost of a **lossy handoff**: only what a station *writes down* survives, so a re-run reviewer or implementer works from summaries, not the prior run's full reasoning. The mitigation is that station skills are told to write a precise, actionable worklist. The sharper, structured version of this handoff is tracked in [OPTIMIZATION-AREAS.md](OPTIMIZATION-AREAS.md).

## Layer 3 — the triggers (how work moves)

There are two ways to move the conveyor, and they share the same engine and `line.yml`:

**Local / interactive — the `/factory` command.** This is the default. It resolves a target item, then loops: `factory next` → read the directive → run the station (apply its skill, or spawn its subagent) → `factory advance` → repeat, until a gate or a terminal. It's a deterministic loop around an intelligent core. The `SessionStart` hook injects the board so every session is factory-aware; the `UserPromptSubmit` hook quietly captures steering you type while an item waits at a gate.

**Cloud / unattended — GitHub Actions.** Opt-in (`workflows/`, shipped disabled). GitHub becomes the conveyor: a `factory:<state>` label on an issue triggers the matching station to run headlessly via `claude -p`, which advances the item and re-labels the issue — triggering the next run. Human-gate labels deliberately don't auto-run; they wait and comment the review packet. This is the "runs while you sleep" layer; see [CLOUD-AUTONOMY.md](CLOUD-AUTONOMY.md). The two layers are independent — local works with no cloud at all, and you can disable cloud anytime without losing anything.

## Why these substrates

- **Local JSON is the source of truth, GitHub is a mirror.** This keeps the core usable with zero accounts and makes the factory's memory (interventions, metrics) live in your repo, version-controlled, where the learning loop can reach it across time. GitHub issues/labels/PRs are the *visible* conveyor when you want them and the trigger for cloud mode.
- **Skills + subagents over a bespoke agent framework.** The factory is optimized for the Claude Code ecosystem on purpose — skills are portable and inspectable, subagents give isolation and per-station model control for free, and hooks/commands wire it into your normal session without a separate runtime.
- **A declarative line.** Because the topology is data (`line.yml`), the same definition drives the local driver, the cloud workflows, and the tests — and you can add a station or move a gate without touching code.
