# Optimization areas — known tradeoffs & future work

A living log of deliberate v1 tradeoffs and known weaknesses **that we already have an idea how to improve**. This is not a bug list and not a wishlist — an entry earns its place only when we can name both the current cost and a plausible direction. Prune entries as they ship or stop being true.

Each entry: what it is today · why it's fine for now · the idea for later.

---

## 1. Continuous monitoring + auto-spawn is deferred

**Today.** The line's tail is `ship_review → deploy → done`. A green post-merge deploy (the project's CI/CD, which for ECS/`fsd` services blocks on steady-state + health) is treated as the ship-and-success signal, so an item is *done* when it ships. There is no perpetual `monitor` station on the line — the `factory-monitor` skill/agent are parked under `deferred/` (not installed into adopting repos) and aren't wired in. Post-ship regressions are handled as *new* work items — `factory new --parent <origin-WI>`, or a labeled issue pulled in by `factory intake` — and the parent link keeps the learning thread: a regression traces back to the shipped change that caused it, so a retro can aim at the verify/code-review bar that let it through.

**Why it's fine for now.** Perpetual monitoring needs a real signal layer (Grafana/Loki/Prometheus/CloudWatch reasoning) that these apps don't own at the factory level, and wiring an agent to reason over it is a large lift. Deploy-green is a legitimate 80/20 success signal for this app class, and "later bugs are new cycles" is an honest model — with lineage now preserved, it's also a learning-compatible one.

**The idea for later.** Re-add a `monitor` state + routing to `line.yml` and run `factory-monitor` on a cron against shipped items once a signal source is connected. Its follow-ups spawn with `parent` already set (the spawn machinery does this today), so the learning thread is ready for it.

---

## 2. The toolkit's prompt layer has no eval

**Today.** The engine is pinned by unit tests, and upgrades are merge-aware (`install.py --upgrade` three-way-diffs against the manifest's commit and reports divergence) — but "did this wording change make agents drive the line better or worse?" is only observable in live metrics after the fact. A skill edit that regresses agent behavior ships silently.

**Why it's fine for now.** The metrics ledger (one-shot ship rate with its recent-vs-prior trend, steers by stage, cost) is an honest live eval on real work; synthetic agent-driving benchmarks would cost more than the current scale justifies, and the human reviews every retro PR anyway.

**The idea for later.** A prompt-layer eval harness: a scripted scenario repo + headless driver runs, scored on protocol conformance (stopped at gates, honored station isolation, emitted valid CLI calls) and steers/cost — run against toolkit changes to skills/commands before merging, so prompt regressions are caught before adopters inherit them.

---

## 3. Delivery is serial — the driver runs one item at a time

**Today.** Triage can decompose a genuinely separable item into leaf-sized children (the spawn/parent machinery; the umbrella parks), so oversized work arrives as several small units, each with its own spec/review/verify/PR. But the driver still moves one item start-to-finish before the next, so independent leaves gain no wall-clock parallelism.

**Why it's fine for now.** A solo operator driving one interactive session wants one thing moving at a time anyway, and decomposition already bought the review-coherence win — the cycle-time cost only bites as volume grows or the factory runs more autonomously.

**The idea for later.** Let the driver run **independent items concurrently** — parallel station subagents on disjoint branches, keeping the item as the isolation unit (never intra-station fan-out, which would collide on one branch). The care points: gate presentation (batch the human's pending decisions rather than interleaving them), `.factory/` write contention (engine calls are cheap to serialize through one driver), and keeping cost visible while several meters run. The moment *two drivers* can run (local + cloud, or two sessions), claims need **leases** — an `{owner, expires}` field on the item plus a claim step that reaps expired leases (the codex bench build's crash-safe pattern) — so a dead session's item is reclaimable and two runners can't double-work one item.

---

## 4. The tracker mirror is one-way and coarse — stations never talk back to the issue

**Today.** GitHub issues are now a real intake surface — `factory intake` files labeled issues onto the line, records the mirror link (`source_ref`), and stamps the conveyor label at ingest. After that, though, feedback to the issue is still just the `factory:<state>` label sync — and even that runs only in the cloud workflow's prompt; the local `advance` path calls no adapter. A subscriber watching the issue sees label flips at best: no "implementation started", no progress, no final status. (Auto-linking softens this: GitHub links the PR from the `Closes`/`Related to` reference, and a Jira site with the GitHub app connected populates the issue's Development panel whenever the issue key appears in the branch name or PR title — the stations' follow-the-repo's-branch-convention guidance produces exactly that. So what's missing is narration, not linkage.) All progress narration lives in `--summary`/`--notes` history, visible only on the factory board.

**Why it's fine for now.** The operator is solo and board-centric — `/factory-status` and the review packets are the surfaces that matter, and nobody else subscribes to the mirrored issues. Baking comment etiquette into station skills now would add chatter with no reader, and every posted comment is another surface that can leak or drift.

**The idea for later.** Wire `adapters/github.comment` (and a future Jira adapter, per EXTENDING.md's adapter seam) into the advance path behind config: on the milestone transitions (implementation started, PR opened, blocked-with-reason, shipped), post a terse status comment built from the same `--summary` the board shows — one source of truth, two surfaces. Now that issues are the intake surface, whoever filed the intake issue is the natural first reader.

---

## 5. Nothing re-checks the merged result — ship is the last look

**Today.** Verification is pre-merge: verify exercises the branch, the human merges at ship_review, and `deploy` watches the project's post-merge CI/CD (which, for the health-gated app class this factory targets, is a real check). But the *factory* never looks again: a post-merge failure surfaces as `deploy --failed--> code_review` only if the CI/CD run itself goes red, and nothing automatic reverts a merge whose damage shows up past that window — recovery is a human filing a follow-up item (`--parent` keeps the lineage).

**Why it's fine for now.** The target app class delegates exactly this to CI/CD with health-wait, deploy-failed already routes back into the code loop, and an auto-revert bot needs main-branch write access plus judgment about *what* to revert — a heavy trust grant while ship volumes are small and a human watches every merge.

**The idea for later.** A factory-owned **observe** step after `deploy` succeeds (the codex bench build's post-merge check + auto-revert): run the repo's own check commands against the merged integration branch once more; on failure, open a revert PR automatically (never force-push), spawn a follow-up item with `--parent`, and suspend any policy that auto-cleared the shipped item — closing the loop between a bad ship and the autonomy that allowed it.

---

## 6. Cost is a self-reported proxy — no real meter, no budget

**Today.** `--cost` on advance is whatever the station claims (usually a rough effort proxy), metrics sum it, and the attempt cap is the only enforceable spend brake. Nothing measures real tokens/dollars per run, and nothing refuses to start a run over a budget — in-session subagents expose no per-run cost to the driver, so there is honestly nothing to meter yet.

**Why it's fine for now.** Interactive driving means the human *is* the budget — they see every loop and can stop it (and the attempt cap now stops the silent ones). Cost-per-shipped stays comparable as a proxy even if its unit is fuzzy.

**The idea for later.** When station runs go headless (`claude -p`, as the bench's fab build runs them), real per-run cost arrives for free in the result stream — capture it into `advance --cost`, add per-item/per-day caps the driver checks before dispatching (fab's `run_budget = min(per_run, item_remaining, day_remaining)`), and surface both in `factory metrics`. The `--ran` trace field already distinguishes headless runs, so proxy-cost and metered-cost items can be told apart in the ledger.

---

<!-- Add new entries only when you can state the cost AND a direction. Keep it lean. -->
