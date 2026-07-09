# The learning loop — how the factory improves itself

This is the part that makes it a *factory* and not just a pipeline. A pipeline runs the same way forever. A factory measures itself, finds where it needed a human, and re-tools so it doesn't next time. The guiding line, from Lloyd's thesis: **every time you have to step in is a failure to learn from.** Not a failure to feel bad about — a signal to capture and convert.

## The mechanism in four moves

1. **Capture.** Every time you steer at a gate — send a spec back, mark "not ready", approve-with-changes — the dispatcher writes a structured **intervention record** to `.factory/interventions/`: what the station produced, what you wanted instead, the category, and *why*. Steering you type in chat while an item waits is captured too (by a hook). This is the raw material; nothing else works without it. (The record's exact shape lives in `src/factory/interventions.py`, which writes it — read any file under `.factory/interventions/` for a real example.)

2. **Measure.** The **metrics ledger** (`.factory/metrics/`) tracks the North Star — the **one-shot ship rate**, the share of changes that shipped with **zero** human rework (no send-back, correction, or unblock) — plus *where* humans had to step in, ranked worst-first, and a cost-per-change proxy. `factory metrics` shows it. Note what this does *not* penalize: a human attending a gate and approving unchanged is the line working, not a miss. The "where humans step in" ranking is the factory's to-do list for itself.

3. **Learn.** The **Retro station** (`factory-retro` skill, opus-class) reads the interventions and the metrics, clusters them by *root cause* (not surface symptom), and for each recurring pattern picks the **smallest permanent lever**:
   - the station keeps missing the same thing → **edit that station's skill**;
   - a gate approves the same category unchanged every time → **propose a dormant gate policy**;
   - specs keep omitting the same section → **edit the template**;
   - work is mis-routed → **adjust `line.yml`** (rare, conservative).
   It writes its findings and concrete proposals to `.factory/retro/<date>/` and opens a PR titled `retro: <date>`.

4. **Dispose.** You review the PR. Skill/template edits take effect when you merge. **Gate policies stay dormant until you sign them** — you activate a proposed rule by setting `approved_by:` on it in `policies.yml`. From then on, every matching work item clears that gate untouched; that slice ships without reaching you at all — one more class of change that lands one-shot.

The asymmetry is the whole point: you make a decision *once* (or a few times), the Retro station generalizes it, and the factory carries it forever. You propose nothing and dispose everything; the machine proposes and you dispose.

## Gate policies: the lever that moves the number

A gate policy is a small rule: *if a work item reaching gate G matches these conditions (labels, risk ceiling), apply this decision automatically.* It lives in `policies.yml`, and it does nothing until `approved_by` is set — so the factory can *suggest* shortcuts but never *take* them without your signature. Conservative by construction: the default at every gate is "require a human," and a learned policy only ever narrows that for a proven-safe slice.

This is how "raise the one-shot ship rate" becomes a *consequence* of the learning loop rather than a setting you flip. You don't tell the factory to skip gates; you teach it — sharper stations so work needs no rework, plus the occasional signed policy for a proven-safe slice — and the metric follows.

## Worked example (the demo)

The demo repo shows the full cycle on one real feature ("let visitors submit a quote"):

1. The Spec station wrote a happy-path spec for `POST /quotes` — **no input validation**.
2. At `spec_review`, the human sent it back: *"public write endpoints must always specify input validation and rejection behavior."* That steer became `.factory/interventions/WI-0001-spec_review-...md`, category `missing-edge-case`.
3. The spec was revised, approved, implemented (with validation + four regression tests), reviewed, verified (valid → 201, invalid → 422), and shipped. Metrics: one-shot ship rate 0% (the one change needed a spec send-back), and the ledger pointed at `spec_review` as where the human had to step in.
4. The **Retro station** read that intervention and produced `.factory/retro/2026-06-27/`: it **edited the spec station's skill and the PRODUCT template** to require a validation section for any input-accepting endpoint (so the omission can't recur), and **proposed a dormant gate policy** to auto-approve `spec_review` for low-risk, read-only changes — explicitly flagged as needing more evidence before activation.
5. With that policy activated, a new **read-only** item (WI-0002) ran `triage → spec → spec_review → implement` and the spec gate was cleared by `[policy:auto-approve-readonly-spec]` with **human touches: 0**.

One intervention. One generalization. A gate that now clears itself for a whole class of work. That's the loop closing.

## The economics (the "at what cost" half)

The North Star has two halves: *more* shipped without rework, *and* at an acceptable cost. The ledger tracks a cost proxy per change so you can ask Lloyd's question — "if I spend a dollar on automation, does it return more than a dollar?" Treat factory output as a variable cost you're trying to drive down per unit, not a fixed R&D line. The Retro station's job is to spend your scarce attention where it buys the most future autonomy: the worst gate, the most-repeated steer. Cheap stations stay cheap; the expensive station (Retro on opus) runs rarely and earns its cost by removing recurring human rework.

## What you do

Mostly: **steer with a reason.** `--changed --notes "<generalizable why>" --category <kind>` is the single highest-leverage habit, because it's the difference between the Retro station learning a rule and learning noise. Then run `/factory retro` now and then (or schedule it — [CLOUD-AUTONOMY.md](CLOUD-AUTONOMY.md)), read its PRs, and sign the policies you trust. Watch the one-shot ship rate climb.
