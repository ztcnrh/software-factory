# Code tour — how the factory spins

If you want to peek under the hood and actually understand how the factory works, this is what you read and in what order. It's a companion, not a reference: [ARCHITECTURE.md](ARCHITECTURE.md) explains the layers and the *why*; this doc gives you the reading path and the handful of functions worth loading into your head first. It deliberately doesn't explain every file or signature — once you've walked these blocks, the rest of the code reads easily on its own.

## The mental model in one sentence

A work item is a JSON record with a `state` field; the entire engine exists to answer one question — **"given this state and this verdict, what's next?"** — and to write down everything that happens along the way.

## Block 1 — the motor (~45 min): `line.yml` + four files

Read `line.yml` first. It's the single source of truth for the conveyor: `states` (each with a `kind`: station / human_gate / terminal), `start`, and `routing` — a table of `state → {verdict: next_state}` edges. Nothing else in the system hardcodes the topology; everything asks this file. Then, in order:

### 1. `src/factory/model.py` (~10 min) — the nouns

Three dataclasses; everything else just moves them around.

- **`WorkItem`** — the thing on the conveyor. The fields that matter: `state` (where it is), `history` (every transition, appended via `log()` — this is why persisted items are readable as a story), `human_touches` (the North Star counter), and `risk` + `labels` (what gate policies match on).
- **`StationReport`** — what a station hands back. `verdict` is the routing key; `human_required` is the escape hatch (below); `spawn` is how a station files a follow-up work item (the mechanism a deferred monitor / future issues-watcher uses; child enters at triage).
- **`GateDecision`** — a human's call at a gate. `changed` / `notes` / `category` are the learning signal.

### 2. `src/factory/line.py` (~5 min) — the map reader

Tiny on purpose. Two things to internalize: `_validate()` — every routing source *and* destination must be a defined state, checked at load, which is why a careless `line.yml` edit fails loudly instead of stranding items — and `route(state, verdict)`, a dict lookup that raises on unknown verdicts. That's the entire routing "algorithm." Everything else is one-line topology questions (`is_gate`, `skill_for`, …) so no other file ever touches the YAML's shape.

### 3. `src/factory/dispatch.py` (~20 min) — the motor; the file to read slowly

One decider and three movers:

- **`next_action()`** — *pure*: state in, `Action` out, mutates nothing. The order of its checks matters: terminal → gate (policy first, then human) → external → station.
- **`advance()`** — a station finished; record its report and route on the verdict. Note the **escape hatch** near the top: if the report set `human_required`, the item goes straight to `blocked`, *bypassing the routing table entirely*. Any station can pull this cord at any time — it's the one movement the routing diagram doesn't show.
- **`gate()`** — a human decided. The `is_intervention` line is the learning loop's front door: `changed` or a steering verdict (`needs_revision` / `not_ready` / `park`) → an intervention record gets written.
- **`apply_auto_gate()`** — a signed policy clears a gate with no human (emits `required_human=False`, and no steer). That's *one* way a change lands one-shot, but not the main one: the headline metric counts ships with zero human *rework*, so the primary driver is stations good enough that the human approves unchanged.

So there are **four ways an item moves**: a station verdict (`advance` → `route`), a human decision (`gate` → `route`), a policy auto-clear (`apply_auto_gate`), and the escape hatch (`human_required` → `blocked`, no routing).

### 4. `src/factory/cli.py` (~10 min, but only two spots) — where Claude meets the engine

Read it *after* dispatch.py, because it's the boundary, not the brain — argparse plumbing around Dispatcher calls. Two parts deserve real attention:

- **`_resolve_next()`** — the auto-gate walker. `next_action()` never mutates, so *someone* has to actually apply policy-cleared gates and step forward; this loop is that someone, and it runs after every `new` / `next` / `advance` / `gate`. When you wonder "when do policies actually fire?", the answer is here.
- **`_print_action()`** — prints the `NEXT: {json}` line. This is the protocol between the engine and the LLM driver: `/factory` parses that JSON to decide what to do. It's the factory's only API contract with Claude.

The rest (board rendering, label creation) is skimmable plumbing.

**Pair with:** `tests/test_dispatch.py` — it drives full passes down the line; reading one test case after dispatch.py confirms your mental model cheaply.

## Block 2 — the memory and the learning machinery (~20 min)

These are the leaf modules the motor calls into. None of them affect the line's *motion*; each owns one artifact on disk.

- **`store.py`** — work items persist as JSON under `.factory/work-items/`, one file per item, `WI-NNNN` ids. Local JSON is the source of truth; everything else (GitHub issues, metrics) derives from or mirrors it.
- **`policies.py` + `policies.yml`** — the autonomy lever, worth its own sitting. A policy is a small rule: *at gate G, if the item matches (`labels_any` / `labels_all` / `max_risk`), apply this decision automatically.* The load-bearing detail is in `auto_decision()`: a rule is **dead until a human sets `approved_by`** — the factory can propose shortcuts but never take them unsigned. This one mechanism is how a proven-safe slice safely earns a hands-off clear — cleared without you, but never unsigned.
- **`interventions.py`** — writes one markdown record per human steer (what the station produced, what the human wanted, *why*, plus a machine-readable block) to `.factory/interventions/`. This module's `_TEMPLATE` is the record's source of truth. These records are the fuel for everything in [LEARNING-LOOP.md](LEARNING-LOOP.md).
- **`metrics.py`** — an append-only event ledger (`.factory/metrics/events.jsonl`) rolled up by `summary()` into the North Star: the one-shot ship rate (shipped with no human rework), where humans had to step in (ranked worst-stage-first, blocks included), cost per shipped change.
- **`retro.py`** — assembles interventions + metrics into a briefing for the retro *station* (the skill does the thinking; this module just gathers).
- **`adapters/github.py`** — optional mirror: syncs a `factory:<state>` label and comments onto a GitHub issue so the conveyor is visible there. Nothing depends on it; skip until you care about cloud mode.

## Block 3 — the intelligence layer and the periphery (~15 min)

Most of this needs one sentence each, because the pattern repeats.

- **`.claude/skills/factory-*/SKILL.md`** — one skill per station, 1:1 with the states in `line.yml`. A skill is the station's instruction manual, and every one ends the same way: an output contract telling the agent which `factory advance --verdict …` call to make. Read `factory-triage` and `factory-spec` fully to get the pattern; skim the rest. (`council` and `cross-critique` are helpers for high-stakes moments, not stations.)
- **`.claude/agents/factory-*.md`** — the vehicles that run the skills: thin subagent wrappers whose real job is pinning a cost-appropriate model per station (opus for retro, haiku for the deferred monitor, sonnet elsewhere) and giving each station an isolated context window.
- **`.claude/commands/factory.md`** — the `/factory` driver: resolve an item, then loop `factory next` → run the station → `factory advance` until a human gate or terminal state. It's the consumer of the `NEXT:` contract from block 1.
- **`.claude/hooks/`** — two small stdlib scripts: `factory_board.py` injects the board at session start; `record_intervention.py` captures steering you type in chat *while an item sits at a gate* — the second, quieter source of intervention records.
- **`templates/`** — the live artifact shapes (spec templates, review packet). Its own `README.md` states the rule: one consumer per template, nothing restates a template's shape elsewhere.
- **`install/install.py`** — copies all of the above into a target repo; read the `CLAUDE_ITEMS` / `ROOT_FILES` lists and you know exactly what "adopting the factory" means. It also plants a pointer block in the target's CLAUDE.md, stamps `.factory/install-manifest.json` (toolkit version + created paths), and can `--uninstall` exactly what it created.
- **`workflows/*.yml.disabled`** — the opt-in cloud layer: GitHub issue labels trigger headless station runs. Ship disabled, least battle-tested; read [CLOUD-AUTONOMY.md](CLOUD-AUTONOMY.md) before enabling. `labels.yml` defines the `factory:<state>` label set that drives it.

## Cement it: trace one real item (~10 min)

The demo repo (a separate worked-example repository — see [demo/README.md](../demo/README.md) for where it lives) has real factory state you can read. Open its `.factory/work-items/WI-0001.json` and read `history` top to bottom with the four movement paths in mind: every event's `kind` maps to exactly one dispatch function (`station` → `advance`, `gate` → `gate`, `auto_gate` → `apply_auto_gate`). Then WI-0002's history shows the policy path firing for real — a gate cleared with zero human touches. That turns the abstractions into a story faster than any doc.
