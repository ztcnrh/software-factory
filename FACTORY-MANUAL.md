# User Manual — operating your software factory

This is the human's guide. It covers what you set up once, what you do day to day, how to act at the three gates, and how to make the factory learn. Read the [README](README.md) first for the big picture.

Your job here is not to write features. It's to **operate the line and keep raising the share of work that ships without you.** Every time you step in, you're either steering a one-off *or* generating the signal that makes that step unnecessary next time — and the second one is the point.

---

## 1. One-time setup

### Required (local, no accounts)
1. **Install the CLI.** `uv tool install /path/to/software-factory` puts the `factory` command on your PATH. (uv already owns Python on your machine, so this just works.)
2. **Adopt the factory into a repo.** From the factory directory: `python3 install/install.py /path/to/your/repo`. This copies the skills, subagents, commands, hooks, line/policy/label config, and templates into the repo, and creates the `.factory/` state directory. Then `cd` there and run `factory init`.
3. **Open that repo in Claude Code.** The `SessionStart` hook will greet you with the board; `/factory` and `/factory-status` are available as commands.

That's the whole local setup. You can run the entire loop from here, by hand-driving with `/factory`.

### Optional homework (only when you want more autonomy)
These unlock the "runs while you sleep" behavior and richer integrations. None are needed to start. See the linked docs.

- [ ] **Anthropic API key as a GitHub secret** — to run stations unattended via GitHub Actions. Add `ANTHROPIC_API_KEY` (or `CLAUDE_CODE_OAUTH_TOKEN`) under the repo's *Settings → Secrets and variables → Actions*. See [CLOUD-AUTONOMY.md](docs/CLOUD-AUTONOMY.md).
- [ ] **Enable the workflows** — install with `--with-cloud`, then rename `.github/workflows/factory-*.yml.disabled` → `.yml`. Treat the first runs as a supervised shakedown.
- [ ] **Create the conveyor labels in GitHub** — `factory labels --github` (needs the `gh` CLI).
- [ ] **A sandbox repo** — for your first cloud run, point it at a throwaway repo, not something precious.
- [ ] **(Later) Monitoring + notifications** — connect the Monitor station to whatever you use (Sentry/Datadog/logs) and route gate pings to Slack. Both are noted as extension points in [EXTENDING.md](docs/EXTENDING.md).

---

## 2. Day-to-day: driving the line

The mental model: **the `factory` CLI decides what's next; Claude does the work; you only show up at gates.**

```bash
factory new "let users export their data as CSV"   # or open a GitHub issue
/factory                # drives the item down the line until it needs you
/factory-status         # the board, the metrics, and anything waiting on you
```

`/factory` keeps moving an item — triage, spec, implement, review, verify — running each station and advancing automatically, and **stops at the first human gate** (or when it's done). You can also drive a specific item (`/factory WI-0003`) or kick the most actionable one (`/factory next`).

When writing a new item (`factory new --body`, or a GitHub issue), you don't need to *pre-solve* it — no spec, no edge cases, no technical design; that's the line's job. But do be *clear*, not just brief: name the two things triage can't guess — **what** it is (one paragraph) and **why** it matters — plus any **notes** you already have (links, constraints, context). Triage can refine a rough idea; it can't read your mind, and a genuinely vague item just bounces straight back to you as a clarification. Clear-but-brief is the target, not precise-but-exhaustive.

Under the hood each step is just the CLI:
- `factory next <id>` — what to do next (auto-clears any gates an approved policy covers).
- `factory advance <id> --verdict <v> ...` — a station reports its result; the item routes onward.
- `factory gate <id> --decision <d> ...` — your decision at a gate (below).
- `factory status [<id>]` / `factory metrics` — inspect.

You rarely type `advance` yourself — `/factory` does. You *do* type `gate`, or just tell Claude your decision in chat.

---

## 3. The gate playbook (your three decision points)

When the line stops, you get a **review packet**: what the item is, what the station produced (links to the spec / PR / verification evidence), its confidence, and the decision options. The packet is built for **orientation in seconds** — everything worth reviewing is one link away, nothing to hunt for. The review itself takes as long as it deserves: these gates are where your judgment is the product, so read the spec, the diff, and the evidence properly. What the packet buys you is that none of that time goes to assembling context.

### Spec review (`spec_review`)
The Spec station wrote `specs/<id>/PRODUCT.md`. Approve if it removes the ambiguity and names the non-goals; send it back if something's missing.
```bash
factory gate <id> --decision approved
factory gate <id> --decision needs_revision \
    --notes "why, generalizably" --category missing-edge-case
```

### Ship review (`ship_review`)
The Verify station attached evidence (tests, behavior, screenshots). **Approving == merging the PR**, which triggers your project's post-merge CI/CD; the external `deploy` step watches it and a green deploy = shipped → done. Bounce to code-review if it's not ready.
```bash
factory gate <id> --decision approved        # merge PR → deploy → done
factory gate <id> --decision not_ready --notes "..." --category ...
```

### Shelving at either gate (`park`)
Both gates also let you stop the line: `--decision park --notes "why" --category ...` moves the item to `parked` (terminal but **revivable** — `revive` re-enters triage later). Use it when the item shouldn't proceed *now* — an external/org blocker, a premature vision, more tech debt than it's worth. Because `park` is a steering decision, your `--notes` reason is captured as an intervention, so shelving also feeds the learning loop.

### Clarification (`needs_human`)
Triage couldn't proceed without a product/priority call only you can make. Answer, and it re-enters triage.

### The one habit that matters
**When you steer, say *why* — generalizably.** A send-back or `park` counts as a steer on its own; add `--changed` only when you *approve* but fixed the work at the gate yourself (by hand or by directing your agent), so that steer gets recorded too. Either way, `--notes "..." --category ...` is what turns a one-off correction into a permanent fix. "Public write endpoints always need input validation" teaches the factory; "fix this" doesn't. Thirty seconds of *why* now buys you fewer gates later. (Steering in chat while an item waits at a gate is also captured automatically by a hook — but an explicit `gate --notes` is richer.)

---

## 4. Making the factory learn

Periodically (or on a schedule, in cloud mode), run the learning station:

```bash
/factory retro          # or: factory retro   (then apply the factory-retro skill)
```

It reads your accumulated interventions and the metrics, finds the patterns, and **proposes** changes — sharper station skills, better templates, and dormant **gate policies** — written to `.factory/retro/<date>/` and opened as a PR. You **dispose**: review the PR, and activate any proposed policy by setting `approved_by:` on it in `policies.yml`. Each thing you accept aims to take a recurring class of work off your plate. (See [LEARNING-LOOP.md](docs/LEARNING-LOOP.md) for the worked example, where one intervention led to a gate that now clears itself.)

Watch `factory metrics`. The number to grow is the **one-shot ship rate** — the share of changes that ship with no human rework (send-back, correction, or unblock). It is *not* about removing yourself from the loop: you still own the ship decision and can attend every gate; the goal is that the line gets good enough that your review is a rubber-stamp. Expect it low early on and climbing as the factory learns. The list of "where humans had to step in" tells you and the Retro station where the next win is.

**Looking back at what the factory has learned.** The retro *station* only looks forward — it mines new steers and proposes new changes; it does not review its own past work. So for the backward-looking questions — did a past optimization actually help, has one gone stale, should I finally sign off (or drop) a dormant policy that's been parked in `.factory/retro/` — ask your **main Claude Code session** in plain language rather than running the retro station. Some asks worth keeping in your pocket:
- *"Read every `.factory/retro/*/report.md` and `proposed-policies.yml`. For each proposal, tell me whether it was adopted (check `policies.yml`, the current station skills, and git history), and whether it's still justified given the interventions since or has gone stale — as a table: proposal → status → your recommendation."*
- *"Are there any dormant gate policies parked in `.factory/retro/` that I should be signing off on by now? For each, check its evidence bar against the interventions and metrics since it was proposed, and tell me whether to sign it off (and make the `policies.yml` edit), keep waiting, or drop it."*
- *"Summarize in plain language everything the factory has learned across all retros — what changed, why, and what's still waiting on my decision."*

(That the retro station has no memory of its own past proposals or their outcomes is a known weakness we intend to close — see [OPTIMIZATION-AREAS.md](docs/OPTIMIZATION-AREAS.md).)

---

## 5. Files you'll touch vs. files the factory owns

- **You edit:** `line.yml` (reshape the line), `policies.yml` (activate learned policies), the station skills under `.claude/skills/` (when you want to teach a station directly).
- **The factory owns (commit it — it's the memory):** `.factory/work-items/`, `.factory/interventions/`, `.factory/metrics/`, `.factory/retro/`. Keep these in version control; they're what the system learns from across time.

---

## 6. When something's off

- **An item is stuck** — `factory status <id>` shows its full history and current state. A `blocked` state means a station hit something only you can resolve (a missing dependency, an access or environment problem, an ambiguity that needs a real decision) and **pulled the escape hatch**: any station can send an item straight to `blocked` at any time, even though the line diagram doesn't draw that arrow from every station. From `blocked` you either clear the obstacle (`--decision unblocked`, back to triage) or shelve it (`--decision park`). This is also the honest home for "verify couldn't run" — not "the code is wrong," but "I lacked the tools/access to check."
- **A gate keeps bouncing the same way** — that's a retro signal, not a nuisance. Run `/factory retro`.
- **The cloud workflow misbehaves** — disable it (rename back to `.disabled`) and drive locally; the layers are independent. See [CLOUD-AUTONOMY.md](docs/CLOUD-AUTONOMY.md).
- **You want to change the line itself** — edit `line.yml`; the engine validates it on load, and the routing is unit-tested, so a bad edit fails loudly.
