# Extending the factory — and a candid take on what's hard

Two parts: how to extend it, then an honest assessment of where this design is strong, where it's shaky, and what to watch as you push it onto real projects. You asked for the limitations straight — section 2 is that.

## 1. How to extend it

### Add or change a station
The line is data. To add a station (say, a `security_review` between code-review and verify): add a state to `line.yml`, wire its routes, write `.claude/skills/factory-security-review/SKILL.md` and a matching subagent, and you're done — the engine, the `/factory` driver, and the cloud workflow all pick it up from `line.yml`. The routing is validated on load and unit-tested, so a malformed line fails loudly. To *reshape* flow (e.g., make verify auto-loop on failure instead of going to the human gate), just change the routing table.

### Tune cost vs. quality
Each subagent names its model. Push mechanical stations down (Monitor is on haiku), keep judgment stations on sonnet, and reserve opus for Retro. If a station underperforms, the cheapest fix is usually a sharper `SKILL.md`, not a bigger model — and the Retro station will often propose exactly that edit.

### Language coverage
The stations are language-agnostic by design: they read the repo's stack (`pyproject.toml` / `package.json` / `go.mod`) and follow its conventions. Python and TypeScript/JavaScript are the smoothest (rich tooling, fast tests). Go and Svelte work. The factory leans on three things existing in the target repo: a **test command**, a **formatter/linter**, and a **way to run the thing** — wherever those are weak, the Verify station gets weaker (see below).

### Tracker and notification adapters
Today the work-item substrate is local JSON with an optional GitHub-issue mirror. The adapter seam (`src/factory/adapters/`) is where Jira (which you use at work) or Linear would slot in — mirror a work item to a ticket, map states to statuses. Gate notifications to Slack are a natural add (a hook or a workflow step that posts the review packet). Both are deliberately *not* in v1 to keep the core dependency-free; they're clean extensions when you want them.

## 2. Where this is hard (the honest part)

**Verification is the real ceiling.** The whole loop's autonomy is capped by how well the Verify station can *prove* a change works without you. For pure functions and HTTP APIs with good tests, it's strong (the demo verifies real 201/422 behavior). For rich, interactive **UIs**, "does this look right and feel right" resists automated verification — browser/computer-use gets you partway, but visual and UX judgment is exactly where you'll keep being the gate longest. Expect the auto-ship rate to rise fast for backend/library/CLI work and plateau lower for frontend polish. That's not a bug in the factory; it's where the hard part of software actually is.

**Triage and spec quality set the ceiling on everything downstream.** A confident-but-wrong triage ("automatable") or a plausible-but-incomplete spec produces work that sails through review and wastes a cycle. The learning loop is the designed mitigation — it sharpens these stations from your interventions — but early on, *spec review is the gate worth your attention most*, because a caught spec error is the cheapest error to catch. Don't be tempted to auto-approve specs quickly.

**The learning loop can overfit.** A retro that proposes an auto-approval policy from one or two data points can wave through work that deserved review. The design is conservative on purpose (dormant rules, your signature required, risk ceilings, an explicit evidence bar in the skill), but the judgment of "is this category *really* safe to stop watching" stays yours. Treat each proposed policy like a small irreversible-ish decision. Skill-edit proposals are much safer (they can only make a station more thorough) than gate-policy proposals (they remove oversight).

**Greenfield vs. brownfield differ a lot.** On a fresh project the factory is excellent — it sets conventions and they compound. On a large existing codebase, the stations are only as good as their ability to read and respect local patterns, and a subtle convention violation can pass review. Point it at a *scoped* slice of a big repo first, not the whole thing.

**The cloud layer is a template, not a product.** Covered in [CLOUD-AUTONOMY.md](CLOUD-AUTONOMY.md): the issue↔work-item seam, concurrency, and cost-control need a shakedown on a sandbox. The local loop is solid today; the unattended loop is where the next real engineering is.

**Cost honesty.** "At what cost" is half the North Star for a reason. A loop with several model-driven stations per change isn't free, and a misrouted item can burn tokens looping. Watch `factory metrics`' cost proxy, keep Monitor cheap and rare, and set spending limits before going unattended. The win has to clear its cost, per change.

**What it is *not*.** It won't invent product judgment, make priority calls, or own architecture decisions you haven't delegated — those surface as `needs_human`/gate decisions by design. It's a machine for executing and verifying well-scoped changes with shrinking supervision, and a method for *shrinking* that supervision over time. The taste, the priorities, and the "is this the right thing to build" stay with you — which is exactly the human's job in this loop.

## 3. The iteration plan from here

This is v1 — built to be used and improved, including by itself. The highest-value next steps, roughly in order: stress-test the local loop on one of your real projects (a scoped slice); feed the first dozen interventions and run a real retro; harden the Verify station for whatever your stack needs; then, on a sandbox, shake down the cloud layer. Each loop you run makes the next one need you less — and the places it still needs you are the map for what to build next.
