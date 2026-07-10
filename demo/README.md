# Demo

The worked example lives in its own repo next door: **[`../software-factory-demo`](../../software-factory-demo)** (a separate git repo, so it mirrors how the factory adopts a real project rather than nesting inside the toolkit).

It's a tiny FastAPI "Quotes API" that the factory drove a full feature through — triage → spec → implement → review → verify → ship — including one human intervention at spec review that the **Retro station** then turned into a permanent improvement (and a gate that now clears itself for read-only work).

Look at, in that repo:
- `git log` — base → factory tooling → the shipped feature → loop state.
- `.factory/work-items/WI-0001.json` — the complete station-by-station history.
- `.factory/interventions/` — the human steer, captured as learning fuel.
- `.factory/retro/2026-06-27/` — what the factory proposed to improve itself.
- `specs/WI-0001/PRODUCT.md` — the spec the factory wrote (v2, after the steer).

See [docs/LEARNING-LOOP.md](../docs/LEARNING-LOOP.md) for the narrated walkthrough.
