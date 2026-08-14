# Code tour — the reading path

[ARCHITECTURE.md](ARCHITECTURE.md) explains the layers and the *why*. This is the order to read the code in, and the handful of functions worth loading into your head first. Once you've walked these, the rest reads easily on its own.

**The mental model in one sentence:** a work item is a JSON record with a `state` field; the whole engine exists to answer *"given this state and this verdict, what's next?"* — and to write down everything that happens along the way.

## Read these five, in this order (~45 min)

| # | File | What to take from it |
|---|---|---|
| 1 | `line.yml` | The single source of truth for the conveyor: `states` (each with a `kind`), `start`, and `routing` — a table of `state → {verdict: next_state}`. Nothing else hardcodes the topology; everything asks this file. |
| 2 | `model.py` | The three nouns. In `WorkItem`, note that `classifiers` is a **derived property** over an append-only `classifier_log` — that's what lets a classification be corrected without erasing it. `StationReport.verdict` is the routing key. `GateDecision`'s `changed` / `notes` / `category` are the learning signal. |
| 3 | `line.py` | Tiny on purpose. `_validate()` checks every routing source *and* destination at load, so a careless edit fails loudly instead of stranding items; `route(state, verdict)` is a dict lookup that raises on an unknown verdict. That is the entire routing "algorithm". |
| 4 | `dispatch.py` | **The file to read slowly** — see below. |
| 5 | `cli.py` | The boundary, not the brain, so read it last. Two spots earn real attention: `_resolve_next()` is the auto-gate walker (`next_action()` never mutates, so *someone* has to apply policy-cleared gates and step forward — this is that someone), and `_print_action()` emits the `NEXT: {json}` line, the engine's only API contract with the driver. |

### The four ways an item moves

This is the "aha" in `dispatch.py`; everything else is bookkeeping around it.

| Path | Function |
|---|---|
| a station reported a verdict | `advance()` → `route()` |
| a human decided at a gate | `gate()` → `route()` |
| a signed policy cleared a gate | `apply_auto_gate()` |
| a station pulled the escape hatch | `human_required` → `blocked`, **bypassing the routing table** |

Three functions to actually read. `next_action()` is pure, and the *order* of its checks is the design: terminal → gate → external → station. `advance()` — spot the escape hatch near the top; it's the one movement the routing diagram doesn't show. `gate()` — its `is_steer` line is the learning loop's front door, the point where an intervention record gets written.

The guards riding those paths (digest-bound gates, the attempt cap, the policy-suspension ratchet) are explained in [ARCHITECTURE.md](ARCHITECTURE.md). Here, just notice they all validate *before* mutating, so a refusal can never half-apply a verdict.

**Pair with `tests/test_dispatch.py`** — it drives full passes down the line, so reading one case right after `dispatch.py` confirms your mental model cheaply.

## Everything else, when you need it

The leaf modules each own exactly one artifact on disk and none of them affect the line's *motion*: `store.py`, `brief.py`, `policies.py`, `interventions.py`, `metrics.py`, `retro.py`, `ledger.py`, `classifiers.py`, `checklist.py`, `sweep.py`, `adapters/github.py`. Under all of them sits `io.py` — atomic replace and a file lock, so durable writes handle crash-safety and concurrency in one place instead of each caller re-deriving it. The module table in [ARCHITECTURE.md](ARCHITECTURE.md) says what each owns — open one when you're changing it.

Same for the prompt layer: `.claude/skills/factory-*/SKILL.md` (read `factory-triage` and `factory-spec` fully to get the pattern, skim the rest), `.claude/agents/factory-*.md`, `.claude/commands/factory.md`, and the two hook scripts under `.claude/hooks/`. What belongs in which file, and why, is Layer 2 of [ARCHITECTURE.md](ARCHITECTURE.md).

To know exactly what "adopting the factory" means, read the `CLAUDE_ITEMS` / `ROOT_FILES` lists in `install/install.py` — those lists *are* the install contract.

## Then trace one real item (~10 min)

Once you've driven an item, its `.factory/work-items/WI-0001.json` is the best reading of all. Open `history` and read it top to bottom with the four movement paths in mind: every event's `kind` maps to exactly one dispatch function — `station` → `advance`, `gate` → `gate`, `auto_gate` → `apply_auto_gate`. That turns the abstractions into a story faster than any doc can.
