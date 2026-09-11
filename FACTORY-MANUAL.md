# User Manual — operating your software factory

This is the human's guide. It covers what you set up once, what you do day to day, how to act at the three gates, and how to make the factory learn. Read the [README](README.md) first for the big picture.

Your job here is not to write features. It's to **operate the line and keep raising the share of work that ships without you.** Every time you step in, you're either steering a one-off *or* generating the signal that makes that step unnecessary next time — and the second one is the point.

---

## 1. One-time setup

### Required (local, no accounts)
1. **Install the CLI.** `uv tool install /path/to/software-factory` puts the `factory` command on your PATH. (uv already owns Python on your machine, so this just works.)
2. **Adopt the factory into a repo.** From the factory directory: `python3 install/install.py /path/to/your/repo`. This copies the skills, subagents, commands, hooks, the line/policy/classifier/label config, and templates into the repo; plants marked blocks in `CLAUDE.md`, `.gitignore`, and `.gitattributes`; and creates the `.factory/` state directory. Then `cd` there and run `factory init`.
3. **Open that repo in Claude Code.** The `SessionStart` hook will greet you with the board; `/factory` and `/factory-status` are available as commands.

That's the whole local setup. You can run the entire loop from here, by hand-driving with `/factory`.

### Optional homework (only when you want more autonomy)
These unlock the "runs while you sleep" behavior and richer integrations. None are needed to start. See the linked docs.

- [ ] **Anthropic API key as a GitHub secret** — to run stations unattended via GitHub Actions. Add `ANTHROPIC_API_KEY` (or `CLAUDE_CODE_OAUTH_TOKEN`) under the repo's *Settings → Secrets and variables → Actions*. See [CLOUD-AUTONOMY.md](docs/CLOUD-AUTONOMY.md).
- [ ] **Enable the workflows** — install with `--with-cloud`, then rename `.github/workflows/factory-*.yml.disabled` → `.yml`. Treat the first runs as a supervised shakedown.
- [ ] **Create the conveyor labels in GitHub** — `factory github-labels --github` (needs the `gh` CLI). These are the `factory:<state>` issue labels from `github-labels.yml`, not the classifiers in `classifiers.yml` — different file, different job.
- [ ] **Skim `classifiers.yml`** — the vocabulary stations classify work items with, and what gate policies match on. It ships seeded with universal terms (`bug`, `feature`, `docs`, …); add what your work actually looks like. A label outside it is still recorded, just flagged and inert for policy, so this is a nudge rather than a wall.
- [ ] **A sandbox repo** — for your first cloud run, point it at a throwaway repo, not something precious.
- [ ] **A `DIRECTION.md`** — install with `--with-direction` (or copy `templates/DIRECTION.md`) and spend ten minutes filling in the north star, Now/Next/Later, and non-negotiables. The spec station anchors specs to it and flags divergence instead of drifting off-vision — the more autonomously the factory runs, the more this file substitutes for the vision in your head.
- [ ] **(Later) Monitoring + notifications** — connect the Monitor station to whatever you use (Sentry/Datadog/logs) and route gate pings to Slack. Both are noted as extension points in [EXTENDING.md](docs/EXTENDING.md).

---

## 2. Day-to-day: driving the line

The mental model: **the `factory` CLI decides what's next; Claude does the work; you only show up at gates.**

```bash
factory new "let users export their data as CSV"   # or open a GitHub issue…
factory intake          # …and pull every open issue labeled `intake` onto the line (needs gh)
/factory                # drives the item down the line until it needs you
/factory-status         # the board, the metrics, and anything waiting on you
```

GitHub issues can be the factory's inbox: label an issue `intake` (the label set from `factory github-labels --github` includes it) and `factory intake` files it as a work item — title/body carried over, the mirror link recorded, already-ingested issues skipped, so it's safe to run on a schedule. `factory intake --dry-run` previews.

`/factory` keeps moving an item — triage, spec, implement, review, verify — running each station and advancing automatically, and **stops at the first human gate** (or when it's done). You can also drive a specific item (`/factory WI-0003`) or kick the most actionable one (`/factory next`).

When writing a new item (`factory new --body`, or a GitHub issue), you don't need to *pre-solve* it — no spec, no edge cases, no technical design; that's the line's job. But do be *clear*, not just brief: name the two things triage can't guess — **what** it is (one paragraph) and **why** it matters — plus any **notes** you already have (links, constraints, context). Triage can refine a rough idea; it can't read your mind, and a genuinely vague item just bounces straight back to you as a clarification. Clear-but-brief is the target, not precise-but-exhaustive.

**Keep the thread on follow-ups.** When new work traces back to an earlier item — a regression from a shipped change, a follow-on to a feature — create it with `--parent <WI-id>` so the lineage is recorded (station-spawned follow-ups get this automatically). That link is what lets a retro connect *"this shipped item later caused a bug"* back to the verify/code-review bar that let it through — the single highest-value learning signal post-ship work carries. If the item mirrors a tracker issue, `--source-ref` records that link too — a bare number reads as a GitHub issue; any other key needs its tracker named (`--source jira --source-ref AMPS-94`).

One backstop worth knowing at intake: work whose text touches sensitive ground (auth, payments, secrets, migrations, …) enters at **medium risk** automatically, and stations can raise its risk but never lower it back below that floor — so an under-triaged auth change can't slide past a gate on a low rating. The floor is deliberately the *weak* claim; judging such an item `high` (which tightens its gates, and puts a review council on the table for the rarer diff that's genuinely contested rather than merely sensitive) stays with triage and the code-review station, who read the change rather than a keyword. Your explicit `--risk` at creation always wins (the bypass is recorded in the item's history).

Under the hood each step is just the CLI:
- `factory next <id>` — what to do next (auto-clears any gates an approved policy covers).
- `factory brief <id>` — the station run's context packet, written into the item's `runs/` dir (the driver adds session context, then hands it to the station — every run's inputs stay on disk).
- `factory sweep <id>` — reclaim a finished item's scratch. Runs automatically when an item ends, so you'll rarely type it; `--all` catches up items from before it existed.
- `factory advance <id> --verdict <v> ...` — a station reports its result; the item routes onward.
- `factory gate <id> --decision <d> ...` — your decision at a gate (below).
- `factory feedback <id>` — the item's PR conversation, verbatim: every unresolved review thread, plus review summaries and comments.
- `factory status [<id>]` / `factory metrics` / `factory doctor` — inspect; doctor cross-checks the stores for consistency.

You rarely type `advance` yourself — `/factory` does. You *do* type `gate`, or just tell Claude your decision in chat.

---

## 3. The gate playbook (your three decision points)

When the line stops, you get a **review packet**: what the item is, what the station produced (links to the spec / PR / verification evidence), its confidence, and the decision options. The packet is built for **orientation in seconds** — everything worth reviewing is one link away, nothing to hunt for. The review itself takes as long as it deserves: these gates are where your judgment is the product, so read the spec, the diff, and the evidence properly. What the packet buys you is that none of that time goes to assembling context.

The packet is also **bound**: before presenting it the driver runs `factory gate --bind`, snapshotting exactly what you're reviewing — the item's artifact files (content-hashed), both PR pointers, and **where both branches actually point**, locally and on the remote you're reading the PR on. That last part is what makes the promise real: a PR number is just a name, so a pass re-pushed while you were reviewing would otherwise clear a gate you gave to different code. Binding decides nothing — the gate still waits on you. If any of it changes before your decision lands, `factory gate --decision` refuses and names what moved (`change branch … moved (remote): a1b2c3d → e4f5a6b`) — you re-review the changed part instead of approving blind. What you approve is what you saw; `--accept-drift` exists for deciding *with the change in view*.

If a branch tip can't be read — you're offline, the branch was never pushed, the remote needs credentials — you get a warning at bind time and again at the decision, and the gap is written into the item's history. It never blocks you: an unreachable remote proves nothing either way, and a gate that fails closed on a flaky network is a gate nobody can use.

**Your comments on the PR are gate input.** Review where you already work: leave inline comments in the GitHub UI — on spec lines at spec review, on code at ship review — and tell the driver your decision; *"needs revision, my comments are on the PR"* is a complete send-back. The revision station reads them itself (`factory feedback <id>` prints every unresolved thread verbatim), answers each in its own thread, and never resolves one — **resolving a thread is yours**: do it when an answer satisfies you, and whatever you leave unresolved stays in front of every later station until it's dealt with. Reviews flow the other way too: the code-review station posts its findings as inline comments, so the review↔implement loop reads as a normal PR conversation. Machine posts carry an invisible marker (`[factory:…]` in the feedback view), so unlabeled words are always a human's. Chat keeps working as before — the PR is an added surface, not a replacement.

### Spec review (`spec_review`)
The Spec station wrote `specs/<id>-<slug>/PRODUCT.md` (plus `TECH.md` for architectural changes), committed them to the item's **feature branch**, and opened that branch's draft PR against your integration branch — review it there, or read the files directly. The **Behavior** section is the contract — numbered invariants the verify station will later check one by one — with explicit **Latitude** marking what's deliberately left to the implementer, and inline **Open question** markers waiting on you. Approve if the invariants remove the ambiguity and the non-goals are named; send it back if something's missing.

**Approving here lands nothing.** It means *build against this plan*; the spec is already on the branch implementation builds on. Each pass then arrives as a `change/…` branch with its own PR *into* the feature branch, so the code diffs against a base that already holds the spec — a spec edit made during implementation reads as a diff you can see, instead of vanishing into a wall of new lines — and a send-back is just the next pass, not a rebuild.

**You own every merge button.** The factory never merges: stations branch, commit, push, and open PRs, and that's all. Merging a pass into the feature branch, and the feature branch into your integration branch, is yours — in your own UI, on your own timing. If you merge a pass before the item is done, the next one comes on a fresh numbered change branch; if you leave it open, the next pass just pushes to it.
```bash
factory gate <id> --decision approved
factory gate <id> --decision needs_revision \
    --notes "why, generalizably" --category missing-edge-case
```

### Ship review (`ship_review`)
The Verify station filled the checklist's evidence by running the software (and commented any screenshot or recording on the change PR). **Approving means you're clear to ship — it doesn't ship.** The merge is still yours: when you merge the feature branch into your integration branch, that triggers your project's post-merge CI/CD, and the external `deploy` step watches it — a green deploy = shipped → done.

Read the packet's headline first: it counts how many of the spec's invariants were **verified by running** versus categorized as `blocked` (out of verify's reach), `accepted` (low risk, not exercised), or `out-of-scope`. That line tells you in one glance what was demonstrated and what you're being asked to take on trust — the per-invariant evidence sits in `specs/<id>-<slug>/CHECKLIST.md` when you want it. If code review found the diff misses an invariant outright, the headline says `not implemented` and names it. Neither checker can leave a row blank: the engine refuses `pass` and `verified` while a row in that station's column is unanswered, so an invariant nobody settled can't reach you disguised as one that passed.

You have two ways back, and which you pick says where the problem was. **`not_ready`** returns it to code review — something is wrong with the change. **`recheck`** returns it straight to verification — nothing is wrong with the change; verification just couldn't demonstrate part of it (it needed access, or an environment that wouldn't come up), you've since cleared that blocker, and it needs demonstrating rather than rebuilding. That costs one station run instead of three.
One thing to check for: if implementation legitimately drifted from the spec you approved (an edge case surfaced, a better approach won), the implement station updated `specs/<id>-<slug>/` in the same PR and flagged it — re-read the changed spec sections here, because you're approving what actually ships, spec included. A drift that *broke* the approved intent never gets this far; the station is required to block and ask you instead.
```bash
factory gate <id> --decision approved        # then you merge → deploy → done
factory gate <id> --decision not_ready --notes "..." --category ...
factory gate <id> --decision recheck --notes "granted staging access"   # → back to verify
```

### Shelving at either gate (`park`)
Both gates also let you stop the line: `--decision park --notes "why" --category ...` moves the item to `parked` (terminal but **revivable**). Use it when the item shouldn't proceed *now* — an external/org blocker, a premature vision, more tech debt than it's worth. Because `park` is a steering decision, your `--notes` reason is recorded with the steer, so shelving also feeds the learning loop.

To bring it back: `factory revive <id>` re-enters at triage (the safe default — the codebase and priorities may have moved while it sat), or `factory revive <id> --resume` re-enters at the state it was parked from (recorded at park time) when you know the shelved context is still fresh — e.g. an item parked at `ship_review` goes straight back to that gate instead of re-running the whole line.

### Fixing a label at any gate
Labels are gate-policy inputs, so a wrong one isn't cosmetic — it's a live input to auto-approval. Add `--retract <name> --retract-reason "<why>"` to any decision to take one off. Yours works on any label, whoever applied it; a station can only retract what a station applied, so it can correct another station's guess but never overrule yours. Nothing is erased either way: the log keeps the original application beside the reason it came off, and `factory status <id>` shows both.

### Clarification (`needs_human`)
Triage couldn't proceed without a product/priority call only you can make. Answer, and it re-enters triage.

### The one habit that matters
**When you steer, say *why* — generalizably.** A send-back or `park` counts as a steer on its own; add `--changed` only when you *approve* but fixed the work at the gate yourself (by hand or by directing your agent), so that steer gets recorded too. Either way, `--notes "..." --category ...` is what turns a one-off correction into a permanent fix. "Public write endpoints always need input validation" teaches the factory; "fix this" doesn't. Thirty seconds of *why* now buys you fewer gates later.

**Keep `--category` a small, reused vocabulary.** Name the *failure mode*, not the fix (`missing-edge-case`, not `add-validation`), in kebab-case, and reuse a word you've used before wherever it fits. The retro's recurrence check joins ledger rows to recorded steers on that exact string, so `missing_edge_case` and `missing-edge-case` are two unrelated categories and the join quietly finds nothing. Nothing validates the vocabulary — it's yours to grow — but the CLI prints the categories already in use whenever you introduce a new one, so a typo is visible at the moment you make it.

---

## 4. Making the factory learn

Periodically (or on a schedule, in cloud mode), run the learning station:

```bash
/factory retro          # or: factory retro   (then apply the factory-retro skill)
```

It reads your accumulated steers and the metrics, finds the patterns, and **proposes** changes — sharper station skills, better templates, and dormant **gate policies** — written to `.factory/retro/<date>/` and opened as a PR. You **dispose**: review the PR, and activate any proposed policy by setting `approved_by:` on it in `policies.yml`. Each thing you accept aims to take a recurring class of work off your plate. (See [LEARNING-LOOP.md](docs/LEARNING-LOOP.md) for the mechanism behind it.)

Watch `factory metrics`. The number to grow is the **one-shot ship rate** — the share of changes that ship with no human rework (send-back, correction, or unblock). It is *not* about removing yourself from the loop: you still own the ship decision and can attend every gate; the goal is that the line gets good enough that your review is a rubber-stamp. Expect it low early on and climbing as the factory learns. The list of "where humans had to step in" tells you and the Retro station where the next win is.

**Looking back at what the factory has learned.** Every retro proposal gets a row (`RP-####`, for Retro Proposal) in the **retro ledger** — `.factory/retro/LEDGER.md`, rendered from the append-only `ledger.jsonl`: what changed, the evidence it answered, the *"how you'll know it worked"* signal, a status (`proposed / applied / dormant / rejected / superseded`), and the outcome once one is observed. The retro station opens every run by **reconciling its open rows** against the record since — adjudicating past proposals, resurfacing dormant policies whose evidence bar is now met, and flagging optimizations that stopped paying off — so the learning loop grades its own past decisions instead of only proposing new ones.

Two habits keep the ledger honest on your side:
- When you merge or decline a retro PR, make sure the verdict lands on the row — `factory ledger update RP-#### --status applied` (a policy reaches `applied` once you sign it; `rejected` when you decline). The session handling the PR review usually does this for you; it takes seconds either way.
- For your own backward-looking audit, start from `factory ledger list --open` (or read `LEDGER.md`, or ask your main session to walk it) — one file, no folder archaeology. Each row links its PR, so the full detail is one click away.

Two checks also run **mechanically**, so the loop grades itself even when nobody remembers to: the briefing's *recurrence check* flags any applied proposal whose steer category has recurred since it took effect (rows carry `--category` for exactly this join — the fix didn't hold), and a signed gate policy whose auto-cleared item later needed your rework is **auto-suspended**: the gate quietly returns to you, `factory policy list` shows which rule and why, and `factory policy reinstate <id>` re-arms it once you've judged the failure wasn't the rule's fault. Autonomy is an asymmetric ratchet on purpose — only you promote; failures demote by themselves.

---

## 5. Files you'll touch vs. files the factory owns

- **You edit:** `line.yml` (reshape the line), `policies.yml` (activate learned policies), the station skills under `.claude/skills/` (when you want to teach a station directly).
- **The factory owns (commit it — it's the memory):** `.factory/work-items/`, `.factory/metrics/`, `.factory/retro/`. Keep these in version control; they're what the system learns from across time.

---

## 6. When something's off

- **An item is stuck** — `factory status <id>` shows its full history and current state. A `blocked` state means a station hit something only you can resolve (a missing dependency, an access or environment problem, an ambiguity that needs a real decision) and **blocked itself** — spec and implement via their explicit `blocked` verdict, any other station via the escape hatch (`--human-required`), which works even where the line diagram draws no arrow. Either way it counts as a human step-in against the one-shot rate — a block is autonomy breaking, however it's spelled. From `blocked` you either clear the obstacle (`--decision unblocked`, back to triage) or shelve it (`--decision park`). This is also the honest home for "verify couldn't run" — not "the code is wrong," but "I lacked the tools/access to check."
- **You advanced or gated the wrong item** — usually the typed-verdict guardrail catches it (the verdict isn't valid from the wrong item's state, so nothing happens). If the verdict *was* valid there and the item routed, put it back in one audited move: `factory correct <id> --state <where-it-belongs> --reason "advanced the wrong item"`. History is append-only, so the mistaken event stays visible — that's the audit trail, not damage — and a correction doesn't count against the one-shot metrics. A correction can move in either direction — the target is wherever the true event left the item. If the slip swallowed a real decision (a gate or deploy outcome), restore the item to that state and re-record the decision through `factory gate`/`advance` rather than correcting straight to its destination — that keeps identity and the ship metrics honest. Your driving agent follows the same recipe for its own slips, signed with its own identity (`--by driver:claude`), never yours — and never to change what a station or human actually decided.
- **A gate keeps bouncing the same way** — that's a retro signal, not a nuisance. Run `/factory retro`.
- **An automated loop got stopped** — an item at `blocked` with an "attempt cap" note means a station re-ran its per-epoch budget (`max_attempts` in line.yml) and the engine cut the loop instead of burning more tokens on the same fight. Read the item's history and the PR review threads (`factory feedback <id>`), then unblock with real guidance (your decision opens a fresh budget) or park it.
- **A gate you'd delegated is asking for you again** — a signed policy was probably suspended: an item it auto-cleared later needed your rework, so the engine pulled the rule. `factory policy list` shows which and why; reinstate it, or let the next retro propose a tighter one.
- **Something feels inconsistent** — `factory doctor` cross-checks the config and every store (unparseable items, unknown states, ids that disagree with their filename, artifact paths that no longer exist, broken lineage, stale gate bindings, torn ledger lines, and both halves of the retro's category join) and says exactly what's off. Warnings inform; errors exit 1. Run it after a crash, a move, or an upgrade — and whenever a station's output reads like it never saw the spec, since a wrong artifact path is invisible everywhere else.
- **The cloud workflow misbehaves** — disable it (rename back to `.disabled`) and drive locally; the layers are independent. See [CLOUD-AUTONOMY.md](docs/CLOUD-AUTONOMY.md).
- **You want to change the line itself** — edit `line.yml`; the engine validates it on load, and the routing is unit-tested, so a bad edit fails loudly.
