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

## 4. The tracker mirror is one-way and coarse — the issue label goes stale, and stations never talk back

**Today.** GitHub issues are now a real intake surface — `factory intake` files labeled issues onto the line, records the mirror link (`source_ref`), and stamps the conveyor label at ingest. After that the mirror stops: `sync_label` has exactly one call site (`cmd_intake`), so an item driven locally leaves its issue frozen at `factory:triage` for the rest of its life, and the cloud workflow's re-label lands only because its prompt *asks the agent* to run `gh issue edit` — deterministic state, non-deterministic mirror. A subscriber watching the issue sees one label flip at ingest and then silence: no "implementation started", no progress, no final status. (Auto-linking softens this: GitHub links the PR from the `Closes`/`Related to` reference, and a Jira site with the GitHub app connected populates the issue's Development panel whenever the issue key appears in the branch name or PR title — the stations' follow-the-repo's-branch-convention guidance produces exactly that. So what's missing is narration and a live state marker, not linkage.) All progress narration lives in `--summary`/`--notes` history, visible only on the factory board.

**Why it's fine for now.** The operator is solo and board-centric — `/factory-status` and the review packets are the surfaces that matter, and nobody else subscribes to the mirrored issues. Baking comment etiquette into station skills now would add chatter with no reader, and every posted comment is another surface that can leak or drift.

**The idea for later.** Two halves, cheapest and highest-value first. **(a) Deterministic label sync:** call `sync_label` after every applied transition from the CLI boundary — where `cmd_intake` already puts its adapter call, never inside `Dispatcher`, so the engine stays offline and pure — best-effort and warn-on-failure like intake, passing `old_state` so labels replace rather than accumulate, and no-oping for items whose `source` isn't a tracker. That alone makes the issue a live state anchor for anyone watching, local driving included. **(b) Narration:** wire `adapters/github.comment` (dead today; and a future Jira adapter, per EXTENDING.md's adapter seam) into the same seam behind config, posting on the milestone transitions (implementation started, PR opened, blocked-with-reason, shipped) from the same `--summary` the board shows — one source of truth, two surfaces. Whoever filed the intake issue is the natural first reader. **The constraint to design around:** `factory-station.yml` triggers on `issues: labeled`, so once both layers are live a locally-written label is itself an event that can kick off a duplicate cloud run — the sync needs a bot-actor guard, a requested-vs-current label split, or the honest rule that one driver runs at a time.

---

## 5. `.factory/` state isn't fully parallel-safe — the id counter and the retro logs still collide

**Today.** Metrics are sharded one event file per item (`metrics/events/<item>.jsonl`, single-writer), and the other per-item artifact — `work-items/<id>.json` — merges cleanly by construction. So two drivers in the same repo (several engineers, or one person across N worktrees) working *different* items no longer conflict on the high-frequency writer. Three seams remain. (1) The work-item id counter: `_next_id()` is `max(existing)+1`, so two parallel `factory new`s hand out the same `WI-NNNN` — same filename, same identity. (2) The retro ledger is still a single shared append file: `retro/ledger.jsonl`. (3) `retro/LEDGER.md` is a committed *derived* view that conflicts on every concurrent ledger write. And a level up from files: even with every file conflict-free, an item mid-flight is authoritative only on *its branch* — `main` has no single consistent "what is the factory doing right now" until branches land.

**Why it's fine for now.** The operator is solo and drives one item at a time, so id collisions need two simultaneous `new`s that don't happen. Retro is infrequent and effectively single-writer, so its shared logs rarely collide. Metrics — the one writer that fires on every transition — is already sharded, which removes the conflict that would actually bite day to day.

**The idea for later.** (a) Make ids collision-proof: key a tracker-sourced item off its immutable issue number (`WI-gh-7`), and give purely-local items a short random or author suffix — which also unifies with the issue-as-anchor direction in #4. (b) Apply the same shard-per-unit trick to the ledger if it starts colliding — shard `ledger.jsonl` by proposal id. (c) Stop committing `LEDGER.md`; render it on read, since it's a pure function of the ledger. (d) The consistent-view gap is the bigger call: either a coordination server, or a convention that `.factory/` state is authoritative only on `main` and every transition lands there via a small dedicated commit — decide that before running true multi-driver, since file-level mergeability buys mergeability, not a live shared picture.

---

## 6. Nothing re-checks the merged result — ship is the last look

**Today.** Verification is pre-merge: verify exercises the branch, the human merges at ship_review, and `deploy` watches the project's post-merge CI/CD (which, for the health-gated app class this factory targets, is a real check). But the *factory* never looks again: a post-merge failure surfaces as `deploy --failed--> code_review` only if the CI/CD run itself goes red, and nothing automatic reverts a merge whose damage shows up past that window — recovery is a human filing a follow-up item (`--parent` keeps the lineage).

**Why it's fine for now.** The target app class delegates exactly this to CI/CD with health-wait, deploy-failed already routes back into the code loop, and an auto-revert bot needs main-branch write access plus judgment about *what* to revert — a heavy trust grant while ship volumes are small and a human watches every merge.

**The idea for later.** A factory-owned **observe** step after `deploy` succeeds (the codex bench build's post-merge check + auto-revert): run the repo's own check commands against the merged integration branch once more; on failure, open a revert PR automatically (never force-push), spawn a follow-up item with `--parent`, and suspend any policy that auto-cleared the shipped item — closing the loop between a bad ship and the autonomy that allowed it.

---

## 7. Cost is counted in station runs — structural, but blind to what a run spends

**Today.** Two channels, neither a meter. `--cost` on advance is whatever the station claims, and across five real items in the first adopting repo every recorded value was `0.0` or `1.0` — the stations simply don't report it, so the North Star's "and at what cost" half had no data at all. `station_runs` / `runs_per_shipped` (v0.6.0) fixed the *empty* problem by deriving cost from history the engine already writes: one station event is one agent doing one job, needing nothing from any station. What it can't see is that a run is not a unit of spend. An opus council convened inside one code-review run — several full investigations plus a synthesis — reads exactly the same as a routine sonnet review. So the proxy tracks rework faithfully (which is where the money actually went: one item that looped twice cost four extra runs) and tracks *depth* not at all.

**Why it's fine for now.** Interactive driving means the human *is* the budget — they see every loop and can stop it (and the attempt cap stops the silent ones). Runs-per-shipped against a six-run minimum path is a real, comparable number today, and the thing it measures well is the thing worth cutting first.

**The idea for later.** Two paths into the same `--cost` channel, so `factory metrics` needs no further change. **Headless:** when station runs go headless (`claude -p`, as the bench's fab build runs them), real per-run cost arrives for free in the result stream — capture it into `advance --cost`, add per-item/per-day caps the driver checks before dispatching (fab's `run_budget = min(per_run, item_remaining, day_remaining)`), and surface both in `factory metrics`. **Interactive:** the Claude Code session transcript already carries per-message `usage`, with `isSidechain` distinguishing subagent messages from the driver's — enough to attribute tokens to a station run. That belongs in a `.claude/`-layer adapter, never in the engine: it parses an undocumented internal format that only exists on one runtime, and the engine has to stay portable and offline. The `--ran` trace field already distinguishes headless runs, so proxy-cost and metered-cost items can be told apart in the ledger.

---

<!-- Add new entries only when you can state the cost AND a direction. Keep it lean. -->
