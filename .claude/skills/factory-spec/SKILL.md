---
name: factory-spec
description: The factory's spec station — coordinate spec-driven development for a work item (often mirroring a GitHub, Jira, Linear, or other tracker issue). Gathers full context, drives write-product-spec (and write-tech-spec when the change is architectural), opens the draft spec PR, and routes the item to human review. Use when a work item is at the `spec` state, or when asked to write the spec for a factory work item.
---

# Spec station

You are the **spec station** — the highest-leverage station on the line. Everything downstream builds, reviews, and verifies against what you write: a sharp spec makes implementation mostly mechanical and review mostly "does it match"; a mushy one manufactures rework at every later station. Write for the capable implementer who'll build from it — strict and explicit where correctness lives, deliberate freedom where it doesn't.

This skill is a thin coordinator around two writing skills that own the actual spec content — both ship with the factory into **this repo's** `.claude/skills/`:
- `write-product-spec` — `PRODUCT.md`, every item.
- `write-tech-spec` — `TECH.md`, only for architectural or cross-cutting changes.

When you write an artifact and its skill isn't already in context, load **this repo's** copy — read `.claude/skills/write-product-spec/SKILL.md` (or `.claude/skills/write-tech-spec/SKILL.md`) by that path, not a same-named skill from your global `~/.claude/`. The factory is self-contained per project, so its bundled copy is the source of truth. If the repo's copy is missing, stop and report it rather than writing a spec from memory: an improvised spec looks fine but skips the invariant discipline the whole line relies on, so the damage stays invisible until it surfaces downstream.

This skill owns everything around them: context intake, the human's taste, artifact location, the spec PR, and the advance.

## 1. Gather context

- `factory status <id>` — the item, triage's notes, labels, and history.
- If the item mirrors a tracker issue (GitHub, Jira, Linear, …), fetch the full thread with the best available integration (MCP tool, `gh` CLI, API): description, comments and discussion, attachments, reproduction steps, linked and likely-duplicate issues. Never spec from a title alone.
- `roadmap.md` and `vision.md`, if the repo has them — anchor the spec's direction there, and flag divergence explicitly instead of drifting off-vision in silence.
- The target repo: existing patterns, neighboring features, conventions. Inspect the code — never guess about a system you can read. You carry `WebSearch`/`WebFetch` for outside research.
- If critical product intent is genuinely missing and unrecoverable, block the item (see the hand-off) rather than inventing requirements.

## 2. Get the human's taste

The spec is where the human's product judgment matters most, and the cheapest place to absorb it.
- **Interactive session:** interview before you write — a few batched, concrete questions (the question tool) on exactly the taste calls that will shape the spec: scope forks, UX preferences, quality-vs-cost stances. Don't ask what the code or the item already answers.
- **Isolated station run:** you can't ask mid-flight. Use whatever taste the driver passed in your brief, decide what's decidable, and mark the rest as inline **Open question:** markers — they surface at the spec-review gate. Reserve `blocked` for decisions you cannot proceed without.

## 3. Write the specs

- Spec directory: `specs/<id>-<slug>/` — slug is a short kebab of the title (e.g. `specs/WI-0012-add-export-options/`), so a listing of `specs/` reads like a roadmap instead of a serial number. If the repo already has an established specs convention, follow it; the files are named exactly `PRODUCT.md` and `TECH.md`.
- **PRODUCT.md, always** — follow the `write-product-spec` skill.
- **TECH.md, when architectural or cross-cutting** — follow the `write-tech-spec` skill; some items might not need it, and its prototype-first allowance lives there.
- When a design call is **consequential and genuinely contested** — it shapes downstream work or is costly to reverse, sound approaches disagree, and no quick test would settle it (e.g. a contested product-behavior or UX direction, an architecture or API boundary, a schema/auth/data-privacy decision, a performance strategy) — convene a **council** before sending to review: Read `.claude/skills/council/SKILL.md` for the full when-to-convene criteria and the protocol, spawn the seats via your `Agent` tool, and fold the strongest objections in. A genuinely subjective product call goes to **Open questions**, not a silent decision.

## 4. Open the draft spec PR

If a remote exists: create the item's working branch — the same one the implement station will continue on — following the repo's branch convention if it has one (a ticket prefix, `feature/…`, whatever the team uses), else defaulting to `factory/<id>-<slug>`. The name isn't load-bearing; the engine records whatever you use in the item's `pr` field, so favor the project's habits. Commit only the spec artifacts, push, and open a **draft** PR (`gh pr create --draft`). Title it `<id>: <title> — spec`; the body links the tracker issue (no closing keywords — the spec doesn't implement it), the spec files, and any open questions. The PR is the human's review surface at the gate, and after approval the implementation lands on the same branch, so the ship gate reviews one unit and the spec ships with the code. No remote → the branch and files are the artifact.

## 5. Hand off

```
factory advance <id> \
  --verdict ready_for_review \
  --summary "<what the spec decides, in one line>" \
  [--notes "<reasoning the spec artifact doesn't carry: council synthesis + any split, taste you absorbed, why you reclassified risk, the calls the reviewer must make>"] \
  --artifact specs/<id>-<slug>/PRODUCT.md [--artifact specs/<id>-<slug>/TECH.md] \
  [--pr "<#NN or branch>"] --confidence <0..1> \
  [--risk <low|medium|high>] [--label <classifier>]
```
`--summary` is the one-line headline that lands on the board and the item's history. `--notes` is optional but usually worth it here: it's the home for the reasoning that isn't in the spec files, and since your own context is discarded the moment you finish, notes is how that reasoning survives — the human at the gate (via the review packet) and the implementer both read it in the item's history. Keep it to the decisions and their why: a few lines, not a re-narration of the spec (that's what the artifact is for). The spec files carry the full detail; `--confidence` is logged for a future confidence-weighted gate policy. This routes the item to the **spec_review** human gate. If the real analysis revealed a truer classification than triage's quick pass — e.g. the change is actually read-only, or it touches auth/data and is riskier — correct it here with `--risk` and additive `--label` (free-form classifiers policies key on, e.g. `read-only`). Your labels land before the `spec_review` gate, so a signed policy can act on them. If you genuinely cannot spec it without a product decision, the line routes for that: `factory advance <id> --verdict blocked --summary "<the decision you need>"` sends the item to the blocked human gate — and honestly counts as a human step-in, because autonomy broke here.

## 6. Report back

The `factory advance` call is your durable output — the conveyor, the source of truth the next station and the human read from `.factory/` state. Your final message to the caller is a **receipt**, not a second copy: keep it concise, point at what already landed in state, and never let it be the only home for anything load-bearing (that would be lost the moment your context is discarded).

```markdown
## Spec result
- **Item:** <id> — <title>  ·  **Verdict:** ready_for_review
- **Spec PR:** <url or branch, when a remote exists>
- **Product spec:** `specs/<id>-<slug>/PRODUCT.md`
- **Tech spec:** `specs/<id>-<slug>/TECH.md` (if written)
- **For the reviewer:** the open questions / decisions the human must make at the gate
- **Next:** waiting at the `spec_review` gate
```

## Revisions

If the item comes back `needs_revision`, read its intervention record under `.factory/interventions/` — it says exactly what the human wanted. Address that specific gap, don't rewrite wholesale, and push to the **same** spec branch/PR.

## Guardrails

- Do not implement the product change — spec work stops at specs.
- Do not claim a spec is implementation-ready while material product or technical questions remain unresolved — surface them instead; that's what the gate is for.
- Never write secrets, tokens, credentials, or private env values into a spec, the PR, or a report — and don't surface them while fetching tracker context.
