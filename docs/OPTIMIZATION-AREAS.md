# Optimization areas — known tradeoffs & future work

A living log of deliberate v1 tradeoffs and known weaknesses **that we already have an idea how to improve**. This is not a bug list and not a wishlist — an entry earns its place only when we can name both the current cost and a plausible direction. Prune entries as they ship or stop being true.

Each entry: what it is today · why it's fine for now · the idea for later.

---

## 1. Lossy handoff between stateless stations

**Today.** Stations are stateless — every run is a fresh context, and continuity rides on durable state (the work item `history` log, `artifacts` paths, the PR/diff, `specs/<id>-<slug>/`). See [ARCHITECTURE.md](ARCHITECTURE.md), Layer 2. When `code_review` sends work back to `implement` (and back again), the only thing that crosses the boundary is `StationReport.summary`, recorded as a one-line history note. The prior run's actual reasoning is gone.

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

**Today.** The line's tail is `ship_review → deploy → done`. A green post-merge deploy (the project's CI/CD, which for ECS/`fsd` services blocks on steady-state + health) is treated as the ship-and-success signal, so an item is *done* when it ships. There is no perpetual `monitor` station on the line — the `factory-monitor` skill/agent are parked under `deferred/` (not installed into adopting repos) and aren't wired in. Post-ship regressions are handled as *new* work items, not by reopening the shipped one.

**Why it's fine for now.** Perpetual monitoring needs a real signal layer (Grafana/Loki/Prometheus/CloudWatch reasoning) that these apps don't own at the factory level, and wiring an agent to reason over it is a large lift. Deploy-green is a legitimate 80/20 success signal for this app class, and "later bugs are new cycles" is an honest model.

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

## 8. The retro station has no memory of its own proposals — and provenance has no home

**Today.** Retro is purely forward-looking. `factory retro` emits a briefing of *new* interventions + metrics; the skill clusters those and proposes new levers. Nothing reads the prior `retro/<date>/` folders, reconciles a past proposal against what actually got adopted, or checks whether an accepted change *worked*. Two gaps fall out of that. First, dormant policies can sit un-adjudicated indefinitely and a stale optimization has nothing watching for it — the backward-looking audit has to be driven by hand from the main session (see FACTORY-MANUAL.md §4). Second, when a retro edits a skill or template, its **provenance has nowhere structured to go**: the only homes are an inline note in the artifact itself — as the demo's `templates/PRODUCT.md` shows, `_(Section added by retro 2026-06-27 after WI-0001.)_` — or the `retro: <date>` PR trail. Inline notes are the wrong home: they clutter the living artifact, don't survive a later revision of that section, and duplicate what the PR already records (noise the moment it merges).

**Why it's fine for now.** The forward loop is the value driver, and with only a handful of retros a human can hold the history in their head or reconstruct it from git + the PR trail. No optimization has yet had time to go stale.

**The idea for later.** Give retro a durable memory: an append-only **retro ledger** (`.factory/retro/ledger.jsonl`, rendered to a human-readable `LEDGER.md`) with one row per proposal — date, id, lever + files touched, the intervention(s) it answered, its "how you'll know it worked" signal, and a mutable **status** (`applied` / `dormant` / `activated` / `rejected` / `superseded`) plus the later observed outcome. Then: (a) keep provenance *out* of the templates and skills — the ledger plus the PR are the record, not an inline annotation; (b) add a "reconcile past proposals" read-first step so every retro run opens by reading the ledger — surfacing dormant policies whose evidence bar is now met and flagging optimizations that stopped paying off; (c) let the human (or main session) drive audits off one file instead of grepping folders; (d) store the PR URL on each ledger row and link the PR body back to the entry, so the full detail — report, diff, discussion — is always one GitHub click away; and (e) close the review loop: the retro station opens the PR (a draft is fine) once its conviction clears the evidence bar, and the human's final verdict on that PR — approve / request-changes / reject — writes back to the row's status, so the ledger tracks what actually happened, not just what was proposed. The revision path already has skill guidance (see `factory-retro`'s "Revising a proposal from human feedback"); the ledger is what makes its outcome durable. This turns the learning loop from write-only into a closed loop that grades its own past decisions — the highest-leverage hardening for the factory's core selling point.

---

## 9. Metrics are a point-in-time aggregate — no trend over time

**Today.** `metrics.summary()` folds *every* event into one cumulative number; `factory metrics` prints a single one-shot ship rate. There is no time-series, no windowing, no period-over-period comparison — and the events themselves aren't even timestamped (`emit(**event)` writes only what the caller passes, and no caller passes a time). So the North Star we most want to watch *climb as the factory learns* (see LEARNING-LOOP.md) can't actually be shown climbing: a lifetime cumulative rate weights the factory's earliest, worst runs forever, understating recent gains, and there's no way to answer "is it improving?"

**Why it's fine for now.** With few shipped items the cumulative rate *is* the signal, and the honest read is sample-size-first ("a rate over 3 ships is noise"), which the `/factory-status` summary already asks for. Trend matters only once there's enough volume for a window to mean something.

**The idea for later.** Timestamp events at `emit()` (a one-line, backward-compatible `setdefault("ts", ...)`), then add a rolling/bucketed view to `summary()` and surface it in `factory metrics` — e.g. one-shot rate over the last N ships vs. the prior N, or a simple monthly bucket — so the learning loop's payoff is visible, not just asserted. The timestamp is the cheap prerequisite; do it early even before the rest, since it can't be backfilled onto events already written without one.

## 10. No project-level north star for the spec station to anchor to

**Today.** The spec station's only durable inputs are the work item and the surrounding code. It has no place to learn *where the product is going* — the vision, the roadmap, the non-negotiables — so a spec is optimized locally to the issue and can drift "off-brand" from the project's direction without anything noticing. The spec-writing skills already read `roadmap.md` / `vision.md` *if a repo happens to have them*, but the factory neither ships those files, prompts the adopter to write them, nor treats them as first-class.

**Why it's fine for now.** For a solo operator holding the vision in their head, the interactive spec interview (the human's taste, captured at the gate) carries the same signal ad hoc. The gap bites as the factory runs more autonomously, or across a team where the direction isn't in one person's head.

**The idea for later.** Make project-direction docs a first-class, optional anchor: ship a `vision.md` + `roadmap.md` starter pair (or a single `DIRECTION.md`) the installer offers to plant, teach the spec station to weight them and to *flag* a spec that diverges rather than silently complying, and let the retro station notice when accepted steers keep pulling against a stale roadmap (a signal the roadmap, not the spec, is what's wrong). Keep it optional — absent files must stay a graceful no-op, never a hard dependency.

## 11. Delivery is serial — one item at a time, no feature decomposition

**Today.** The driver runs one work item start-to-finish before the next, and no station splits a large feature into smaller ones. The engine *can* spawn children (`StationReport.spawn` → new items into triage, linked by `WorkItem.parent`), but that path was built for follow-ups (e.g. a monitor filing a regression); no station skill instructs decomposition. So a big feature flows as one oversized item — one spec, one PR, one review — slower to build, harder to review as a unit, and with no throughput gain from sub-tasks that are genuinely independent.

**Why it's fine for now.** A solo operator driving one interactive session wants one thing moving at a time anyway, and oversized items are rare when intake is well-scoped. The cost bites as volume grows or the factory runs more autonomously.

**The idea for later.** Two complementary levers, both preferring the *item* boundary over intra-station fan-out (which would break a station's per-unit isolation and collide on one branch). (1) Teach **triage** to decompose: when an item is genuinely separable, spawn leaf-sized child items (reusing the existing spawn/parent machinery) instead of routing the whole thing — with a guard against runaway subdivision (children must be leaf-sized, not re-splittable). (2) Let the driver run **independent items concurrently** rather than strictly serially. Together they turn a big feature into several small units that move in parallel, each keeping its own spec/review/verify/PR — which is where the real cycle-time win is, without the review-coherence cost of one giant multi-agent PR.

---

## 12. The tracker mirror is one-way and coarse — stations never talk back to the issue

**Today.** When a work item mirrors a tracker issue (`source_ref`), the only feedback to that issue is the `factory:<state>` label sync — and even that runs only in the cloud workflow's prompt; the local `advance` path calls no adapter. A subscriber watching the issue sees label flips at best: no "implementation started", no progress, no final status. (Auto-linking softens this: GitHub links the PR from the `Closes`/`Related to` reference, and a Jira site with the GitHub/Bitbucket app connected populates the issue's Development panel whenever the issue key appears in the branch name or PR title — the stations' follow-the-repo's-branch-convention guidance produces exactly that. So what's missing is narration, not linkage.) All progress narration lives in `--summary`/`--notes` history, visible only on the factory board.

**Why it's fine for now.** The operator is solo and board-centric — `/factory-status` and the review packets are the surfaces that matter, and nobody else subscribes to the mirrored issues. Baking comment etiquette into station skills now would add chatter with no reader, and every posted comment is another surface that can leak or drift.

**The idea for later.** Wire `adapters/github.comment` (and a future Jira adapter, per EXTENDING.md's adapter seam) into the advance path behind config: on the milestone transitions (implementation started, PR opened, blocked-with-reason, shipped), post a terse status comment built from the same `--summary` the board shows — one source of truth, two surfaces. Pairs with the issues-watcher (§5): once issues are the intake surface, the issue becomes the natural progress surface for whoever filed it.

---

<!-- Add new entries only when you can state the cost AND a direction. Keep it lean. -->
