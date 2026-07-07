# Optimization areas — known tradeoffs & future work

A living log of deliberate v1 tradeoffs and known weaknesses **that we already have an idea how to improve**. This is not a bug list and not a wishlist — an entry earns its place only when we can name both the current cost and a plausible direction. Prune entries as they ship or stop being true.

Each entry: what it is today · why it's fine for now · the idea for later.

---

## 1. Lossy handoff between stateless stations

**Today.** Stations are stateless — every run is a fresh context, and continuity rides on durable state (the work item `history` log, `artifacts` paths, the PR/diff, `specs/<id>/`). See [ARCHITECTURE.md](ARCHITECTURE.md), Layer 2. When `code_review` sends work back to `implement` (and back again), the only thing that crosses the boundary is `StationReport.summary`, recorded as a one-line history note. The prior run's actual reasoning is gone.

**Why it's fine for now.** The `factory-code-review` skill is told to emit a *precise, actionable worklist*, which is the compression of its reasoning. For most changes a good worklist is enough, and statelessness buys determinism + cloud-resumability + no context rot.

**The idea for later.** A structured review/handoff artifact instead of a single summary string: a per-item worklist file (e.g. `.factory/work-items/<id>/review-<n>.md`) carrying the reviewer's rationale, the specific asks, and — on the way back — what the implementer changed and why. Then each fresh agent reads "the conversation so far" at summary-of-reasoning granularity, not just a one-liner. Keeps statelessness; makes the handoff far less lossy.

---

## 2. The learning loop is blind to automated inner-loop churn

**Today.** Interventions — the retro station's fuel — are written *only when a human steers at a gate* (`dispatch.gate()` → steering verdicts). The `code_review ↔ implement` loop is fully automated, so no matter how many times it ping-pongs, it produces **zero** intervention records. The only trace is `WorkItem.attempts[state]` (per-state run counts) and raw metrics events, which the retro briefing doesn't currently foreground.

**Why it's fine for now.** The North Star is human touches, and optimizing the human frontier is the highest-leverage target first. Agent-loop thrash costs tokens, not human time.

**The idea for later.** Surface `attempts` as a retro signal: flag items whose `attempts[<state>] ≥ N` (e.g. an implement/code_review loop that bounced 4+ times) as a distinct input to `factory retro`, so the learning station can see *"this class of work churns internally"* and sharpen the spec or the code-review bar even when no human ever stepped in. Cheap: the data already exists on the work item; it just needs to be read and clustered.

---

## 3. Parked items always revive at `triage`

**Today.** `parked` is revivable, and `revive → triage` — so a fully-spec'd item shelved at `ship_review`, when revived, re-enters the line at the very top and re-runs everything.

**Why it's fine for now.** It's the safe default: while an item sat parked the codebase and priorities may have moved, so re-triaging avoids reviving a stale plan. Parking is also rare.

**The idea for later.** Record the pre-park state on the work item and let `revive` optionally resume near where it left off (e.g. re-enter at `spec` or `code_review`) when the human signals the context is still fresh — with re-triage remaining the default.

---

<!-- Add new entries only when you can state the cost AND a direction. Keep it lean. -->
