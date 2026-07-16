---
name: write-tech-spec
description: Write a TECH.md implementation spec for an architectural or cross-cutting change, grounded in researched code — context, approach, and a validation plan mapped to the product spec's invariants. Use when writing a technical spec, implementation plan, or architecture doc tied to a product spec, typically after PRODUCT.md is agreed. In the factory, the spec station drives this skill for changes that span subsystems or make non-obvious architectural choices.
---

# write-tech-spec

Write a `TECH.md` that translates product intent into an implementation plan that fits the existing codebase, documents the architectural choices, and makes the work easier for agents to execute and reviewers to review.

## When to write one

When the implementation spans multiple modules, carries meaningful architectural tradeoffs, or when reviewers will benefit from seeing the plan before or alongside the code. Skip it for localized work — a tech spec for a one-file fix is waste.

Prefer to have `PRODUCT.md` first so the plan is anchored to agreed behavior; when the design is too uncertain to plan on paper, build an e2e prototype first and then write the tech spec from what actually held up — the spec still goes to review before the real implementation.

## Research before writing

Read the product spec, then inspect the relevant code: the main files, types, data flow, and ownership boundaries in the area being changed. Do not guess about current architecture when the code can be inspected directly.

When referencing relevant code chunks in the spec, prefer commit-pinned references so future readers can inspect exactly what you saw: `path/file.py:120-180 @ <short-sha>` (capture the SHA with `git rev-parse --short HEAD`), linked to the remote's `blob/<sha>/…#Lx-Ly` URL when one is accessible.

## Structure

Required sections:
1. **Context** — what's being built and how the current system works in the area being changed, grounded in the most relevant files with pinned references. Combine "problem", "current state", and "relevant code" into this one section. Reference `PRODUCT.md` for behavior rather than restating it.
2. **Approach** — the plan: which modules change, the new types/interfaces/data shapes, data flow and ownership boundaries, and how the design follows the repo's existing patterns. Call out sequencing when order matters, and tradeoffs when more than one path is reasonable.
3. **Testing & validation** — how the implementation will be proven against `PRODUCT.md`'s numbered Behavior invariants: each important invariant maps to a concrete test or verification step — unit/integration tests, manual steps, and, for visual or UI changes, screenshots or a short recording. This is the evidence whoever verifies and signs off relies on before shipping, so it owns proving the feature works; `PRODUCT.md` deliberately has no validation section.

Optional sections — include only when they add signal; omit the heading entirely rather than writing "None":
- **Alternatives considered** — when a real alternative was on the table: the why-not matters more than the list.
- **End-to-end flow** — only when tracing the path through the system tells the reader something Approach doesn't.
- **Diagram** — a Mermaid diagram (data flow, state transitions, sequence) only when a visual explains the design faster than prose. Prefer one or two focused diagrams over decorative ones.
- **Risks & mitigations** — when there are real failure modes, regression or rollout hazards; blast radius and how each is contained.
- **Migration / rollback** — required whenever data, schemas, or live traffic are touched: how it rolls out, and exactly how it rolls back.
- **Follow-ups** — Include when there is deferred cleanup or future work worth naming.

## Length heuristic

Right-size the spec to the change:
- Single-file change with a clear approach: skip the tech spec, or keep it under ~40 lines.
- Multi-module change with some ambiguity: target ~80–150 lines.
- Large, cross-cutting, or architecturally novel change: longer is fine when every section earns its place.

If Context and Approach end up describing the same files and state from different angles, collapse them.

## Writing guidance

- Ground the plan in the codebase's actual structure and patterns; explain why this design fits *this* repo.
- Pin important code references to a commit SHA and link them to the corresponding GitHub lines when the repository has an accessible remote.
- Prefer concrete implementation guidance over generic architecture language.
- Reference `PRODUCT.md` for behavior instead of restating it; reference invariants by number.
- Each section should earn its place — if a section would repeat another or contain only boilerplate, omit it.
- Approved specs ship in the same PR as the implementation, and this file is kept true as the approach evolves — `TECH.md` describes the implementation that actually ships.
