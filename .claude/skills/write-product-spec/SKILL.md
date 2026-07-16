---
name: write-product-spec
description: Write a PRODUCT.md spec focused on precise user-facing behavior — numbered, testable invariants that double as acceptance criteria. Use when writing a product spec, PRD, or desired-behavior doc, when defining feature behavior before implementation, or when a change is substantial or behaviorally ambiguous enough that a written spec would improve implementation or review. In the factory, the spec station drives this skill.
---

# write-product-spec

Write a `PRODUCT.md` spec for a significant feature, which makes the desired behavior unambiguous enough that an agent can implement it correctly and avoid regressions — while explicitly marking where the implementer's judgment is invited.

## Overview

Describe the feature purely from the user's perspective — what they see, do, and can rely on. Do not include implementation details (internal types, state layout, module boundaries, algorithms): implementation choices in a product spec are latitude stolen from the implementer, and they belong to `TECH.md` (the `write-tech-spec` skill) anyway. Write the product spec so a tech spec could be written directly from it without re-deriving product intent.

**"User" is whoever consumes the surface being designed:**
- For UI/UX features: the human using the product.
- For a data model: the code that reads and writes it.
- For an API, protocol, or library: its callers — services, client code, plugins, agents.
- For a CLI or developer-facing surface: the developer invoking it.

## Before writing

Gather only the context you need — and inspect rather than guess. You're pinning down four things: **who** the consumer is, **what** behavior they need, the **edge cases** the item implies, and the **outcome** that counts as success. Sources:
- The work item: title, body, discussion, attachments. If it mirrors a tracker issue (GitHub, Jira, Linear, …), fetch the full thread — never spec from a title alone.
- `roadmap.md` and `vision.md` if the repo has them: anchor the spec's direction to them, and flag divergence explicitly rather than drifting off-vision in silence.
- Neighboring, already-shipped features: how the adjacent behavior works *for the user*, so this feature stays consistent with what they already know. This is product consistency — the code-level conventions are `TECH.md`'s concern, not this spec's.
- Missing product intent: if you can ask the human (interactive session), ask targeted questions rather than guessing; if you can't (a non-interactive run), decide what's decidable and mark the rest as inline **Open question:** markers — they surface for whoever reviews the spec.

**Design references.** If the feature has a visual or interaction surface, look for a mock (e.g. Figma) or design asset on the work item and link it under a `## Design reference` section. If design matters and none exists, write `Design reference: none provided` — an explicit absence beats a silent guess, and layout then falls under Latitude. Omit the section entirely for non-visual features.

## Structure

Required sections:
1. **Summary** — 1–3 sentences: the capability, its consumer, and the outcome it buys.
2. **Behavior** — the meat of the spec; see below. Everything else stays thin so this section can be exhaustive.

Optional sections — include only when they add signal beyond the core. Omit the heading entirely if empty; do not write "None" as a placeholder.

- **Problem** — only when the motivation isn't obvious from Summary.
- **Scope — Goals / Non-goals** — Include when scope is ambiguous or has been contested. Naming non-goals is the single best defense against the scope creep that bounces specs and PRs.
- **Walkthrough** — for experience-heavy features: one concrete end-to-end scenario in the consumer's shoes, with real inputs. The gestalt the invariants atomize.
- **Latitude** — see below.
- **Design reference** — see "Before writing".
- **Open questions** — prefer inline `**Open question:** …` next to the behavior it affects; a dedicated section only when several are worth collecting.

Do **not** include Validation, Success criteria, or Testing sections — validation lives in the companion `TECH.md` (produced by `write-tech-spec`). Write Behavior as numbered invariants that are testable on their own — the tech spec can reference them directly.

## The Behavior section

**Behavior is the spec. Everything else is framing.**

Write it as numbered, testable invariants — **each one is an acceptance criterion**: written so each can be checked on its own, one by one, and so the tech spec's test plan can map to them by number. The goal of Behavior is a complete English description of how the feature works, detailed enough that a tech spec can be written directly from it without the author having to guess or re-derive product intent. The bar: if a reader finishes Behavior with questions about what the feature does in some situation, the section is not done.

Describe, at minimum:
- Default behavior and the happy-path user flow.
- Every user-visible state and the transitions between them.
- All inputs the user can provide and how the feature responds to each.
- Empty states, error states, loading/pending states, and cancellation.
- Edge cases a reasonable implementer would not think to ask about — permission denied, offline, timeouts, races between state changes, concurrent instances, stale or missing data, interactions with adjacent features.
- The expectations native to the surface: for a UI, keyboard/focus/accessibility; for an API, idempotency, versioning, and compatibility; for a CLI, exit codes and stdin/stdout contracts; for a data model, integrity and consistency guarantees.
- Invariants that must hold at all times and behaviors that must not regress.

A small visual belongs inline when it clarifies faster than prose: a Mermaid diagram for states and flows, an ASCII wireframe for layout — shape, not pixels.

The expected form, in miniature:

```markdown
1. Submitting the form with an empty title shows an inline error and fires no request.
2. On success, the list updates without a reload and the new item receives focus.
3. On a 5xx, the user's input is preserved and a retry affordance appears.
   - **Open question:** cap retries, or retry indefinitely?
```

Length Behavior to match the feature. Trivial features may need a handful of invariants; complex features may need many, with sub-sections per flow or state. The rest of the spec should stay thin so Behavior can be as exhaustive as the feature requires without producing a bloated document overall. Err toward enumerating one more edge case rather than one fewer.

## Latitude

The invariants are the contract; anything not pinned by one belongs to the implementer. Where a good outcome depends on taste rather than compliance — visual polish, copy, interaction feel — add a **Latitude** section: name the area and set the **quality bar**, not the mechanism. A spec that pins everything produces compliance; one that pins the right things and names the free ones invites genuinely better outcomes.

## Length heuristic

Behavior should be as long as the feature requires — never truncate edge cases to hit a line target. The heuristic below applies to everything around Behavior (Summary, optional sections): keep that framing thin so the spec's total length reflects the feature's actual complexity, not structural overhead.
- Small feature (single surface/module, few edge cases): framing plus Behavior typically ~30–60 lines total.
- Medium feature (cross-module, multiple states): typically ~80–150 lines.
- Large or behaviorally rich feature: longer is fine, with most of the length in Behavior.

If the same idea appears in Summary, Problem, and Behavior, collapse the framing — not the Behavior content.

## Writing guidance

- Prefer concrete, observable behavior over aspirational wording.
- Err toward enumerating one more edge case rather than one fewer.
- Each section must earn its place — a section that would repeat another or hold only boilerplate gets omitted.
- Avoid implementation details unless unavoidable for the UX.
- Approved specs ship in the same PR as the implementation, and this file is kept true as reality drifts within the approved intent — `PRODUCT.md` describes the feature that actually ships.
