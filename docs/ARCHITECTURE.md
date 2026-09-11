# Architecture

Four layers, each independently understandable and replaceable: a deterministic **engine**, the **stations**, the **triggers** that move work between them, and the **learning loop**. This doc covers the first three; the fourth is [LEARNING-LOOP.md](LEARNING-LOOP.md).

## The core idea: a dumb engine + smart stations

**The orchestration is deterministic and testable; the intelligence is isolated in skills.** The Python engine never "thinks" — it's a state machine that knows the shape of the line and records what happened. Every judgment call (is this automatable? is this spec good? does this code match it?) lives in a skill run by a subagent. That keeps the moving parts verifiable and the intelligent parts swappable: edit a skill, or point a station at a different model, without touching the engine.

So: **the dispatcher is the brain, the agent is the hands.** The dispatcher says "run the spec station next"; the agent runs it and reports a verdict; the dispatcher routes on that verdict and says what's next. Repeat until a human gate or a terminal.

## Layer 1 — the engine (`src/factory`)

A small, dependency-light Python package (the `factory` CLI).

| Module | Owns |
|---|---|
| `line.py` | Every question about the line's shape — station, gate or terminal? which skill runs it? given a verdict, where next? `line.yml` is the **single source of truth** for the conveyor; reshape the factory by editing it. |
| `model.py` | The three records that flow through the system: a **WorkItem**, a **StationReport** (its `verdict` drives routing), and a **GateDecision** (a human's call, with the structured *why* the learning loop needs). |
| `dispatch.py` | The motor — see below. |
| `io.py` | The disk primitives every durable write goes through: atomic replace (unique staging name + fsync + rename) and a portable file lock. One home for the two hazards — a crash mid-write, and two writers at once. |
| `store.py` | Work items as JSON under `.factory/work-items/`. Local is the source of truth. Id allocation holds a lock until the new file exists, since the race is the gap between reading the highest id and that file appearing. |
| `brief.py` | The deterministic half of a station run's context packet. |
| `feedback.py` | The item's PR feedback, read back verbatim: unresolved review threads, review summaries, comments — machine posts labeled. |
| `policies.py` | Evaluates gate policies, and owns **`PolicyState`** — the engine-written overlay that *suspends* a signed rule when an item it auto-cleared later needed a human. |
| `metrics.py`, `retro.py` | The North Star ledger — one event per gate/station/ship, a steer carrying its category; and the briefing that assembles it all for the retro station. |
| `cli.py` | The thin command surface `/factory` and the workflows call into — every verb documented by its own `-h`. |
| `adapters/github.py` | An **optional** mirror: keeps an issue's `factory:<state>` label in sync, and lists `intake`-labeled issues for the `factory intake` sensor. Nothing on the line depends on it. |

### `dispatch.py` — the motor

`next_action()` is pure: it reports what should happen for an item's current state — which attempt this is, whether the station is a checker, what routed the item here. `advance()` records a station's report and routes. `gate()` records a human decision (and records the steer if you steered). `apply_auto_gate()` clears a gate via a signed policy. This file *is* the factory's control flow, and it's the most heavily tested.

**One deliberate exception to the routing table:** a report with `human_required` sends the item straight to `blocked` regardless of what routes exist — an escape hatch for anything only a human can resolve. Stations whose routing already has a `blocked` verdict (spec, implement) prefer that spelling; the hatch is for everyone else, e.g. verify when it *couldn't check* rather than confirmed a failure. Either way `blocked` counts as a steer, so an unblocked item can't masquerade as a one-shot ship.

Three deterministic guards ride the same motor:

- **Digest-bound gates.** `bind_gate` snapshots the item's artifact files, both PR pointers, and both branch tips (local and remote); a later decision is refused, with the drift named, if any of it moved — so what the human approves is what the human saw. Those tips are why this is the one place the engine reaches for the network: a PR pointer is only a name, and the diff lives at the tip.
- **The attempt cap.** An automated route back into a station past its `max_attempts` (`line.yml`) lands at `blocked` instead of looping. It counts per *human epoch* — a gate decision, correction, or revive resets the budget without erasing the lifetime churn history.
- **The risk floor.** Sensitive-sounding intake (auth, payments, migrations…) enters at `medium`; a station may raise risk but never lower it past the floor. A keyword hit only claims "not trivial" — `high` stays a judgment the stations make from the change itself.

### States and routing (the diagram, in data)

The shape is drawn in [diagram.md](diagram.md). Stations: `triage → spec → implement → code_review → verify → deploy`. Human gates: `spec_review`, `ship_review`, `needs_human`, `blocked`. Terminals: `done`, `parked`. `tests/test_line.py` pins every critical hop, so a careless edit can't silently re-wire the line.

The routes worth knowing:

- **triage fans out four ways** — spec / implement / needs_human / parked.
- **The backward loops** are `spec_review --needs_revision--> spec` and `ship_review --not_ready--> code_review` — the motion the learning loop exists to eliminate. Every gate can also `park`, a recorded and revivable halt.
- **`deploy` is external** (no agent). `ship_review --approved-->` is the human's go-ahead; *they* merge the item's PR, that merge triggers the project's post-merge CI/CD, and `deploy` watches it. `succeeded → done` is the ship point — emitted off the state's declarative `ships_on: succeeded` marker rather than a hardcoded state name. `failed → code_review` re-enters the loop.
- **`monitor` is deferred.** A green deploy is the success signal, so an item is done when it ships. New post-ship work enters as fresh items — `factory intake` files labeled issues onto the line, and `factory new --parent <origin>` links a regression to the change that caused it. See [OPTIMIZATION-AREAS.md](OPTIMIZATION-AREAS.md).

## Layer 2 — the stations (`.claude/skills`, `.claude/agents`)

**Skill + subagent.** Each station is a **skill** (the *how* — a focused `SKILL.md`) paired with a **subagent** (the *who* — an isolated runner with the right tools and a cost-appropriate model). Skills are portable knowledge you can read and edit; subagents give each station its own context window, so a long line never pollutes one conversation and cloud runs stay isolated.

**What goes in which file depends on what a mistake costs.** The agent file becomes the station's system prompt and stays in front of the model for the whole run, so it holds what can't be undone: don't take orders from the work item or the repo, don't merge, don't grade your own work, actually run the `advance` command instead of printing it. The skill is preloaded beside it and can be re-read, so it holds the procedure — which branch to cut, what the rubric is, which flags to pass. The few rules that genuinely belong in several agent files are marked blocks (`<!-- factory:authority -->` and its siblings), opted into per station and kept byte-identical by `tests/test_prompt_layer.py`: six copies exist for prompt position, not to let six stations drift apart.

**Preloading is deterministic.** Each agent names its station skill in `skills:` frontmatter, so the full contract is in context on every isolated run — a subagent never has to go discover its own instructions.

**Tools are scoped, not inherited.** Each agent's `tools:` list is exhaustive on purpose: a station gets exactly what its job needs, not the session's whole MCP surface. That keeps runs predictable, keeps local behavior close to cloud runs (where user MCPs don't exist), and avoids permission stalls inside background subagents. The targeted additions — triage and verify carry browser automation (triage to reproduce a visible bug, verify for evidence); triage and spec carry the Atlassian MCP, so the two tracker-reading stations can open the Jira ticket a mirrored issue merely points at; spec and implement carry web search and fetch; triage, spec, implement and code-review can spawn subagents — triage to offload a long reproduction path, the others for a `council` on contested calls and for `research` delegation. Neither helper skill is preloaded — most runs need neither, so the station's own skill says when to go read one. Adopters graft more on via the agent's frontmatter.

| Station | Emits (verdicts) | Model | Notes |
|---|---|---|---|
| **triage** | needs_spec · automatable · needs_human_clarification · park | sonnet | minutes, not investigation; reproduces bugs with bounded effort; assigns risk and classifiers; an oversized item goes to spec, which scopes it |
| **spec** | ready_for_review · blocked | opus | coordinates `write-product-spec`/`write-tech-spec` → `specs/<id>-<slug>/`; writes the invariant CHECKLIST both checkers grade against; opens the item's feature branch. Planning leverage justifies the tier |
| **implement** | implemented · blocked | sonnet | one pass per `change/…` branch off the feature branch, PR'd into it; tests ship with the change; keeps the spec true to what ships |
| **code_review** | pass · changes_requested | sonnet | the last station that can send work back; judges the diff by **reading** it and fills the checklist's *Implemented* column |
| **verify** | verified · failed | sonnet | cannot send work back — both verdicts reach the human — so it demonstrates rather than re-reviews: exercises *behavior* and fills the checklist's *Holds* column |
| **retro** | (proposes; opens a PR) | opus | runs rarely, but rewrites the factory itself — see [LEARNING-LOOP.md](LEARNING-LOOP.md) |

`deploy` has no agent (it observes CI/CD). `monitor` (haiku) is deferred — parked under `deferred/`, not installed, not a state on the line.

### The two checkers are separated by routing, not by topic

`code_review` is the only station that can send work back; `verify` cannot — both of its verdicts reach the human. That asymmetry, not a list of subject areas, is what divides them: a defect the implementer must fix has to be caught while a route back still exists, and anything found after that can only be reported. So code review's test is where its output *goes* — output that feeds a worklist is its own, output that feeds the human's evidence packet is verify's.

Both grade the same artifact from different columns: the spec's `CHECKLIST.md`, one row per in-scope invariant, *Implemented* filled by reading and *Holds* by running. That shared surface fixes the deeper cause of their overlap — the two receive structurally identical briefs, so asking them in prose alone to reach different conclusions was never going to hold. The engine backs it with one guard per column, each refusing that station's clean verdict while a row is unanswered: `pass` needs every *Implemented* graded `yes` or `no`, `verified` needs every *Holds* disposed, and `no` / `blocked` / `accepted` / `out-of-scope` are all honest answers. The only thing it forbids is silence — which is why each column needs an explicit negative, or "the diff misses this" and "nobody read this row" would be the same blank cell.

### One branch ships one item

The **spec station is a thin coordinator** — it owns context intake, the human's taste, the spec directory, and the draft PR, and delegates the writing to `write-product-spec` (every item) and `write-tech-spec` (architectural changes only). Spec is the highest-leverage station, so its writing guidance gets room to be exhaustive without bloating the coordinator.

It also opens the item's **feature branch** and its draft PR into the integration branch. That branch is the item's unit of delivery, open from spec onward. Each implementation pass is a **change branch** cut from it with its own PR *into* it — so the code reviews against a base that already holds the spec, and a send-back is the next pass rather than a rebuild. **Nothing on the line merges anything:** stations branch, commit, push, and open PRs; every merge is the human's, at their own timing. What they eventually merge is the plan and the change as one reviewable unit.

### Two helpers for the high-stakes moments

**`council`** — several subagents investigate one contested question from genuinely different angles in parallel, the caller synthesizes by evidence quality, and when the seats diverge an optional cross-critique round has them critique each other before the synthesis. Spec and code-review convene it themselves, spawning seats as nested subagents and folding the synthesis into their verdict. It is deliberately **rare and cheap by default** — seats run on sonnet unless the stakes lift them, and the trigger is four conditions ANDed, the sharpest being that the outcome must actually change what the station produces. The reason is economic: a council is the biggest discretionary spend on an item, and this line already routes every item past a human, so a fork a station can frame but not settle is better *written down* for that human than deliberated by a panel.

**`research`** — its quieter sibling. Delegate a wide, noisy investigation (usage sweeps, long logs, big diffs) to a nested subagent and work from the distilled answer, so the survey's byproducts never crowd out the caller's actual job. Just as useful to the driver as to a station.

### The handoff is a packet, not a vibe

A station's contract is simple: read the item, do the work, and finish by **running** the `factory advance --verdict …` call itself — so the report lands durably the moment the work ends rather than being relayed through a summary. That call carries no agency: the routing table decides where the item goes, and illegal verdicts are rejected.

Before dispatching, the driver runs `factory brief <id>` for the deterministic packet — identity, risk, lineage, the request, artifact pointers, what routed it here — and appends session-only context under its one marked section. For the stations `line.yml` marks `checking: true`, that section stays **empty by design**: a checker converges on the frozen spec and the persisted artifacts, never chat steering. Steering that should move the acceptance bar goes through the spec station, not a checker's ear. The packet lives at `runs/<state>-brief.md` (a retry appends its own section, so a retrying station sees what its predecessor was told), so *what each worker was fed* is a file on disk rather than a memory of chat.

### Stations are stateless; continuity rides on durable state

Each run is a fresh context — a subagent locally, a `claude -p` invocation in cloud — so there's no long-lived agent and no in-memory carry-over, even across the `code_review ↔ implement` loop. What the next run sees is whatever landed in durable state: the item's `history`, its `artifacts`, the PR diff, and the `specs/<id>-<slug>/` files. This buys determinism, cloud-resumability, and no context rot down a long line — at the cost that **only what a station writes down survives**.

Where that bites hardest, the handoff is structured — and it lives on the change PR, where review conversations belong: a send-back posts one PR review (the summary carrying the rationale, the `Reviewed at` sha, and what was checked and found sound; each finding an inline comment anchored to its line), and the implementer answers each finding in its own thread. `factory feedback <id>` reads it all back for any station — unresolved threads are the live worklist, resolution is the done-signal, and machine posts are labeled so nobody eats their own output as human feedback. Each fresh run reads the conversation at reasoning granularity, not a one-line summary. (With no remote, the same content degrades into the advance's `--notes`.)

One bounded exception: within a single local session the driver may *resume* a station's subagent on a loop-back instead of spawning fresh. That's an optimization, never the channel — the persisted conversation remains the contract, and cloud runs always spawn fresh. Resuming a checker is a judgment call rather than a default, since the tradeoff is anchoring: a resumed reviewer must re-scan the whole change, and substantial rework favors fresh eyes. The invariant that never bends: **no checker shares the session that built the change.**

### Memory is committed; scratch isn't

Statelessness means the factory writes a lot, and without a rule for which of it matters, a work item's pull request arrives buried under the machinery that produced it. The rule: **if the engine can rebuild it from state that survives, it's scratch; if nothing else holds it, it's memory.**

Specs, the checklist, the metrics ledger, and the decisions a human actually made are memory — committed, and the reason a teammate cloning the repo sees the same board. (The review conversation is memory too, but the PR holds it, not the tree.) Station briefs and scratchpads are scratch: they live under `runs/`, are gitignored, and `factory sweep` removes them when the item terminates. A gate's review packet is a *message*, not a file, for the same reason — it renders from state already on disk, and what has to survive (the decision, its signature, its why) is in the item's history.

The sweep is safe to run automatically because it derives what to keep from the item's own record: a file survives because a station **registered it as an artifact**, the same act that makes it visible to the next station and hashed at a gate binding — and because it refuses any path resolving outside the item's directory. What stays committed but noisy (`.factory/` itself) ships marked `linguist-generated`, so it collapses in pull-request diffs rather than competing with the change under review.

## Layer 3 — the triggers (how work moves)

Two ways to move the conveyor, sharing one engine and one `line.yml`:

**Local / interactive — the `/factory` command.** The default. It resolves a target item, then loops: `factory next` → read the directive → run the station → `factory advance` → repeat, until a gate or a terminal. A deterministic loop around an intelligent core. The `SessionStart` hook injects the board so every session is factory-aware.

**Cloud / unattended — GitHub Actions.** Opt-in, shipped disabled. GitHub becomes the conveyor: a `factory:<state>` label triggers that station headlessly, which advances the item and re-labels the issue, triggering the next run. Human-gate labels deliberately don't auto-run — they wait and comment the review packet. See [CLOUD-AUTONOMY.md](CLOUD-AUTONOMY.md). The layers are independent: local works with no cloud at all, and disabling cloud loses nothing.

## Why these substrates

- **Local JSON is the truth, GitHub is a mirror.** Zero accounts required, and the factory's memory lives in your repo, version-controlled, where the learning loop can reach it across time. Issues and labels are the *visible* conveyor when you want one, and the trigger for cloud mode.
- **Skills + subagents over a bespoke agent framework.** Skills are portable and inspectable, subagents give isolation and per-station model control for free, and hooks wire it into a normal session without a separate runtime.
- **A declarative line.** Because the topology is data, the same `line.yml` drives the local driver, the cloud workflows, and the tests — and you can add a station or move a gate without touching code.
