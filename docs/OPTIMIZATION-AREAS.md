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

**Why it's fine for now.** The North Star is human *rework* (steers), and optimizing the human frontier is the highest-leverage target first. Agent-loop thrash costs tokens, not human time.

**The idea for later.** Surface `attempts` as a retro signal: flag items whose `attempts[<state>] ≥ N` (e.g. an implement/code_review loop that bounced 4+ times) as a distinct input to `factory retro`, so the learning station can see *"this class of work churns internally"* and sharpen the spec or the code-review bar even when no human ever stepped in. Cheap: the data already exists on the work item; it just needs to be read and clustered.

---

## 3. Parked items always revive at `triage`

**Today.** `parked` is revivable, and `revive → triage` — so a fully-spec'd item shelved at `ship_review`, when revived, re-enters the line at the very top and re-runs everything.

**Why it's fine for now.** It's the safe default: while an item sat parked the codebase and priorities may have moved, so re-triaging avoids reviving a stale plan. Parking is also rare.

**The idea for later.** Record the pre-park state on the work item and let `revive` optionally resume near where it left off (e.g. re-enter at `spec` or `code_review`) when the human signals the context is still fresh — with re-triage remaining the default.

---

## 4. Continuous monitoring + auto-spawn is deferred

**Today.** The line's tail is `ship_review → deploy → done`. A green post-merge deploy (the project's CI/CD, which for ECS/`fsd` services blocks on steady-state + health) is treated as the ship-and-success signal, so an item is *done* when it ships. There is no perpetual `monitor` station on the line — the `factory-monitor` skill/agent ship in the repo but aren't wired in. Post-ship regressions are handled as *new* work items, not by reopening the shipped one.

**Why it's fine for now.** Zach-style perpetual monitoring needs a real signal layer (Grafana/Loki/Prometheus/CloudWatch reasoning) that these apps don't own at the factory level, and wiring an agent to reason over it is a large lift. Deploy-green is a legitimate 80/20 success signal for this app class, and "later bugs are new cycles" is an honest model.

**The idea for later.** (a) Re-add a `monitor` state + routing to `line.yml` and run `factory-monitor` on a cron against shipped items once a signal source is connected. (b) **Preserve the learning thread cheaply even without it:** adopt the convention that a follow-up/bug item references its origin `WI-id` (or PR) so `factory new` sets `parent`. Then a regression that traces back to a shipped change is linkable, and retro can eventually connect *"this shipped item later caused a bug"* → sharpen `verify` / `code_review` — recovering the single highest-value signal that dropping `monitor` otherwise loses.

---

## 5. No issues-watcher yet — the factory has no automatic intake

**Today.** The only things that start the line are a human running `factory new` (or the driver on an existing item). There's no sensor turning inbound requests into work items automatically. `CLOUD-AUTONOMY.md` already sketches the cloud half (an `issues: opened` workflow that calls `factory new` + applies `factory:triage`).

**Why it's fine for now.** Hand-created items are enough to exercise and trust the line; intake automation is additive and can wait until the line itself is proven.

**The idea for later.** A small **issues-watcher** sensor: poll `gh issue list --label intake --state open` on a cron (local launchd/`/loop` to start, the `issues: opened` workflow for cloud), and for each new issue run `factory new "<title>" --body "<body>"` then mark it ingested. It touches *nothing* on the line — it just feeds `start: triage` — so it's low-risk. This makes **GitHub issues the intake surface** (Jira stays for PM), and pairs naturally with the parent-link convention in §4.

---

## 6. The learning loop improves instances, not the toolkit — and upgrades have no merge story

**Today.** `install.py` copies the factory into a repo; from that moment the copy is on its own. The retro station improves *that repo's* skills, templates, and policies — and the toolkit never hears about it. Installs are version-stamped (`.factory/install-manifest.json`: toolkit version + commit + created paths — shipped 2026-07-10, enabling safe `--uninstall` and version-aware reinstalls), but upgrades still can't *merge*: a plain reinstall skips existing files, and `--force` replaces factory-owned files wholesale — including exactly the ones retro improved — leaving git history as the only safety net. Relatedly, the prompt layer (skills, driver protocol, CLI breadcrumbs) has no eval: the engine is pinned by unit tests, but "did this wording change make agents drive the line better or worse?" is only observable in live metrics after the fact.

**Why it's fine for now.** One operator, a handful of repos: the human reviews every retro PR anyway and can cherry-pick generalizable improvements into the toolkit by hand — the outer loop exists, it's just social rather than mechanical. `--force` clobbers are recoverable from git, and the reviewer sees the diff before committing. The metrics ledger (one-shot ship rate, steers by stage, cost) is an honest live eval on real work; synthetic agent-driving benchmarks would cost more than v1 justifies.

**The idea for later.** Two pieces. (a) **A real upgrade path**: an upgrade mode diffs three ways (installed copy vs. its original at the manifest's commit vs. current toolkit) so it can apply toolkit upgrades to untouched files, flag retro-modified files for a human merge instead of clobbering, and print a divergence report — which doubles as the upstreaming radar ("this skill drifted the same way in two repos; the toolkit probably wants that change"). The manifest's commit pointer already gives the three-way baseline. (b) **A prompt-layer eval harness**: a scripted scenario repo + headless driver runs, scored on protocol conformance (stopped at gates, honored station isolation, emitted valid CLI calls) and steers/cost — run against toolkit changes to skills/commands before merging, so prompt regressions are caught before adopters inherit them.

---

## 7. A mis-targeted `advance`/`gate` has no clean correction path

**Today.** State-specific verdicts are the guardrail: `factory advance <wrong-id> --verdict x` almost always fails loudly, because the verdict isn't valid from the wrong item's state and `Line.route` raises before anything is saved. The residual risk is the unlucky case — the wrong item sits at a state where that verdict *is* valid (e.g. two items both at `implement`). Then the item routes, and history/metrics/attempts are polluted with no documented recovery beyond hand-editing the item's JSON (the history event, being append-only, stays — which is arguably correct for an audit trail).

**Why it's fine for now.** The typed-verdict guardrail catches the common typo; the unlucky case needs two items at the same state *and* a wrong id, and the blast radius is one item's state (git-recoverable JSON) plus a few noise events in a ledger that aggregates in the hundreds.

**The idea for later.** An auditable admin verb — `factory correct <id> --state <s> --reason "<why>"` — that sets the state and logs a `correction` event with the operator's identity, rather than a true "undo" (unwinding metrics events, intervention files, and spawned children is complexity the mistake doesn't justify). The mistake stays visible in history; the item gets back on track in one command.

---

<!-- Add new entries only when you can state the cost AND a direction. Keep it lean. -->
