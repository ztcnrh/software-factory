---
name: factory-spec
description: The factory's spec station — coordinate spec-driven development for a work item (often mirroring a GitHub, Jira, Linear, or other tracker issue). Gathers full context, drives write-product-spec (and write-tech-spec when the change is architectural), opens the item's feature branch and its pull request, and routes the item to human review. Use when a work item is at the `spec` state, or when asked to write the spec for a factory work item.
---

# Spec station

You are the **spec station** — the highest-leverage station on the line. Everything downstream builds, reviews, and verifies against what you write: a sharp spec makes implementation mostly mechanical and review mostly "does it match"; a mushy one manufactures rework at every later station. Write for the capable implementer who'll build from it — strict and explicit where correctness lives, deliberate freedom where it doesn't.

This skill is a thin coordinator around two writing skills that own the actual spec content — both ship with the factory into **this repo's** `.claude/skills/`:
- `write-product-spec` — `PRODUCT.md`, every item.
- `write-tech-spec` — `TECH.md`, only for architectural or cross-cutting changes.

When you write an artifact and its skill isn't already in context, load **this repo's** copy — read `.claude/skills/write-product-spec/SKILL.md` (or `.claude/skills/write-tech-spec/SKILL.md`) by that path, not a same-named skill from your user-level skill directory. The factory is self-contained per project, so its bundled copy is the source of truth. If the repo's copy is missing, stop and report it rather than writing a spec from memory: an improvised spec looks fine but skips the invariant discipline the whole line relies on, so the damage stays invisible until it surfaces downstream.

This skill owns everything around them: context intake, the human's taste, artifact location, the item's branch and PR, and the advance.

## 1. Gather context

- `factory status <id>` — the item, triage's notes, labels, and history.
- If the item mirrors a tracker issue (GitHub, Jira, Linear, …), fetch the full thread with the best integration your run actually has — the `gh` CLI or the tracker's CLI/API from your shell; a tracker MCP tool only if your session carries one (isolated station runs don't, unless this repo's agent frontmatter grants it): description, comments and discussion, attachments, reproduction steps, linked and likely-duplicate issues. Never spec from a title alone.
- `DIRECTION.md` at the repo root (the project's north star, roadmap buckets, and non-negotiables — the installer plants a starter on request), plus `roadmap.md` / `vision.md`, if the repo has them. Treat them as the product frame: anchor the spec's direction there, and when the right spec for *this* item genuinely pulls against the stated direction, **flag the divergence** — an explicit callout in the spec (Open questions is a good home) and in your `--notes` — rather than silently complying with either side; the human at the gate decides whether the spec or the direction doc is what's stale. Absent files are a normal no-op, never a reason to block.
- The target repo: existing patterns, neighboring features, conventions. Inspect the code — never guess about a system you can read. Search and fetch from the web for outside research when your run can.
- When gathering any of this would flood you with survey noise — a wide codebase sweep, a long tracker thread, several independent questions that could run at once — read this repo's `research` skill (`.claude/skills/research/SKILL.md`) and delegate the digging to a subagent. What comes back is the answer instead of the noise, and your context stays clear for the spec itself.
- If critical product intent is genuinely missing and unrecoverable, block the item (see the hand-off) rather than inventing requirements.

## 2. Get the human's taste

The spec is where the human's product judgment matters most, and the cheapest place to absorb it.
- **Interactive session:** interview before you write — a few batched, concrete questions (the question tool) on exactly the taste calls that will shape the spec: scope forks, UX preferences, quality-vs-cost stances. Don't ask what the code or the item already answers.
- **Isolated station run:** you can't ask mid-flight. Use whatever taste the driver passed in your brief, decide what's decidable, and mark the rest as inline **Open question:** markers — they surface at the spec-review gate. Reserve `blocked` for decisions you cannot proceed without.

## 3. Write the specs

- Spec directory: `specs/<id>-<slug>/` — slug is a short kebab of the title (e.g. `specs/WI-0012-add-export-options/`), so a listing of `specs/` reads like a roadmap instead of a serial number. If the repo already has an established specs convention, follow it; the files are named exactly `PRODUCT.md` and `TECH.md`.
- **PRODUCT.md, always** — follow the `write-product-spec` skill.
- **TECH.md, when architectural or cross-cutting** — follow the `write-tech-spec` skill; its prototype-first allowance lives there. Plenty of items don't need one, but a real share do, so reach for it readily rather than reluctantly: writing it costs you a page, and skipping it costs an implementer inventing the architecture mid-build with no reviewer on that decision.
- **CHECKLIST.md, always** — one row per **in-scope** numbered Behavior invariant from PRODUCT.md, and the file both checking stations grade against. You write it because you are the one who already decided what's in scope: an invariant this item doesn't own (deferred, or belonging to a sibling item) is left out here and named under the table, so neither checker re-derives that call and reaches a different answer.

  Rows carry the invariant's number and text, then three columns you leave empty: **Implemented** (code review fills it, by reading), **Holds** (verify fills it, by running), and **Evidence** (prose for the human — the command or observation behind those two verdicts; the engine never reads it). Then the machine block the engine parses, marked exactly:

  ````markdown
  | # | Invariant | Implemented | Holds | Evidence |
  | - | --------- | ----------- | ----- | -------- |
  | 1 | Requests over the limit get 429 |  |  |  |
  | 2 | The limit is per-key, not global |  |  |  |

  Out of scope: 7–8 (owned by WI-0009, the dashboard).

  <!-- machine-readable: the factory engine parses this block -->
  ```yaml
  item: WI-0007
  rows:
    - n: 1
      invariant: "Requests over the limit get 429"
      implemented: ""
      holds: ""
    - n: 2
      invariant: "The limit is per-key, not global"
      implemented: ""
      holds: ""
  ```
  ````

  Write the scope line even when nothing is out of scope (`Out of scope: none — this item owns all of them`) — a checker reading a checklist with no scope line can't tell a decided scope from a skipped one. A row's `invariant` is a handle, not a quotation: the number is the contract, so condensing PRODUCT.md's wording to fit a cell is expected. Leave `implemented` and `holds` empty — they are the checkers' columns, and you are recording the contract, not grading it. `implemented` later takes `yes` or `no`, and nothing else; `holds` takes one of `verified`, `failed`, `blocked`, `accepted`, `out-of-scope`. Anything else, blank included, leaves that row unanswered. There is no `evidence` key — that column lives in the table only.

  Register it with `--artifact` alongside the specs. Registration is what arms the engine's guard (a `pass` is refused while any row is ungraded, a `verified` while any row is undisposed) and what keeps the file through the sweep — an unregistered checklist guards nothing and no station will find it. Keep it to invariants: it's the acceptance contract, not a task list.
- A **council** is the rare exception here, not a step in the flow — most specs, including hard ones, should ship without one. Every item you spec goes to a human at the spec-review gate a moment later, so the cheap move is almost always to write the fork down: a subjective product call, or a design fork you can frame but not settle, belongs in **Open questions** where the human decides it — never a silent decision, and rarely a panel. Convene only when a call is consequential *and* genuinely contested between sound approaches *and* unsettleable by a quick test *and* would change what you write — if you already know what you'd recommend, write it. When that bar is truly met, Read `.claude/skills/council/SKILL.md` (the criteria and the protocol), spawn the seats as isolated subagents, and fold the strongest objections in. **Everything a council writes is working material** — seat reports and your own memo both belong in `runs/scratchpad/` (e.g. `council-1.md`), which is swept when the item finishes; don't register any of it with `--artifact`. What survives is the decision itself: a call the council settled belongs in the spec, where it is now simply the design; a split it couldn't settle belongs in **Open questions**. Say in `--notes` that a council ran, what was contested, and what you landed on — the human can open the memo while the item is in flight, but nothing later reads it.

## 4. Open the item's branch and its pull request

Create the item's **feature branch** — `feature/<TICKET-KEY>__<slug>` when the item mirrors a tracker issue (e.g. `feature/AMPS-91__session-leak`), else `feature/<id>-<slug>` — off an up-to-date integration branch, commit the spec artifacts to it, push, and open a **draft** PR into the integration branch (`gh pr create --draft`). Title it `<id>: <title>`; the body links the tracker issue — `Closes #N` when it's a GitHub issue in this repo (this PR is the one that will resolve it); for any other tracker (Jira, Linear, …) link the ticket URL instead, since GitHub's closing keywords don't reach them — plus the spec files and any open questions. Follow the repo's convention where it has one; the engine records whatever you use.

That PR is the item's, and it stays open for the item's whole life. It carries only the spec today; implementation lands on the same feature branch, one pass at a time, each on its own `change/…` branch PR'd *into* this one. So the thing the human eventually ships is the plan and the change reviewed together, as a single unit, and no PR against the integration branch ever exists without the work it describes.

It also means the spec gate lands nothing: approving it says *build against this plan*, and the plan is already where the building happens. A later edit to the spec still reads as a line-level diff, because the base it's edited against already contains it.

Record both with `--branch` and `--pr`. No remote → the branch and files are the artifact; say so in `--notes`. **Never merge anything** — every merge on this item is the human's, at their own timing.

## 5. Hand off

```
factory advance <id> \
  --verdict ready_for_review \
  --summary "<what the spec decides, in one line>" \
  [--notes "<reasoning the spec artifact doesn't carry: council synthesis + any split, taste you absorbed, why you reclassified risk, the calls the reviewer must make>"] \
  --artifact specs/<id>-<slug>/PRODUCT.md --artifact specs/<id>-<slug>/CHECKLIST.md \
  [--artifact specs/<id>-<slug>/TECH.md] \
  --branch "feature/<KEY>__<slug>" [--pr "<#NN>"] --confidence <0..1> \
  [--risk <low|medium|high>] [--classifier <name>] \
  [--retract <name> --retract-reason "<what your analysis disproved>"]
```
`--summary` is the one-line headline that lands on the board and the item's history. `--notes` is optional but usually worth it here: it's the home for the reasoning that isn't in the spec files, and since your own context is discarded the moment you finish, notes is how that reasoning survives — the human at the gate (via the review packet) and the implementer both read it in the item's history. Keep it to the decisions and their why: a few lines, not a re-narration of the spec (that's what the artifact is for). The spec files carry the full detail; `--confidence` is logged for a future confidence-weighted gate policy. This routes the item to the **spec_review** human gate. You are the first station to look properly, so you are the one positioned to correct triage's quick pass: `--risk` if the change is riskier or safer than it looked, `--classifier` to add a classification (prioritize a term your brief lists when applicable), and `--retract <name> --retract-reason "<why>"` when your analysis actually *disproved* one — reproducing a bug and finding a different cause is the textbook case. Retraction is a correction, not an erasure: the log keeps triage's original call beside your reason for taking it back. You can only retract what a station applied; a classification the human set at intake stays until they remove it at a gate. All of this lands before `spec_review`, so a signed policy acts on the corrected classification rather than the first guess. If you genuinely cannot spec it without a product decision, the line routes for that: `factory advance <id> --verdict blocked --summary "<the decision you need>"` sends the item to the blocked human gate — and honestly counts as a human step-in, because autonomy broke here.

## Revisions

If the item comes back `needs_revision`, two places hold the why. The gate's notes are in the item's history (`factory status <id>`); and when the human reviewed the spec in the GitHub UI, `factory feedback <id>` prints their inline comments on the feature PR — asks anchored to the exact spec lines they mean. Address each thread and reply in it with what changed (end replies with `<!-- factory:spec -->`; the command prints the reply one-liner); resolving the thread is theirs, not yours. Address the specific gaps, don't rewrite wholesale, and commit to the **same** feature branch.

## Guardrails

- Do not implement the product change — spec work stops at specs.
- Do not claim a spec is implementation-ready while material product or technical questions remain unresolved — surface them instead; that's what the gate is for.
- Never write secrets, tokens, credentials, or private env values into a spec, the PR, or a report — and don't surface them while fetching tracker context.
