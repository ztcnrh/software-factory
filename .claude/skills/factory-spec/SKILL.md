---
name: factory-spec
description: The factory's spec station. Turn an ambiguous work item into a crisp product spec (and a tech spec when the change is architectural), written to specs/<id>/, ready for human review. Use when a work item is at the `spec` state, or when asked to write the spec for a factory work item.
---

# Spec station

You are the **spec station**. Convert one ambiguous work item into specs precise
enough that implementation is mostly mechanical and review is mostly checking
"does it match the spec." Adapted from spec-driven development: product spec
first, tech spec only when the change is architectural.

## Read first
- `factory status <id>` — the item and triage's notes.
- The target repo: existing patterns, neighboring features, conventions. A spec
  that fights the codebase is a bad spec.

## Write
Create `specs/<id>/PRODUCT.md` always; add `specs/<id>/TECH.md` when the change
spans subsystems or makes a non-obvious architectural choice. Use the templates
in `templates/PRODUCT.md` and `templates/TECH.md`.

**PRODUCT.md** answers: what problem, for whom, the desired behavior, explicit
**edge cases and non-goals**, and **acceptance criteria** a verifier can check.
**TECH.md** answers: the approach, key interfaces/data shapes, alternatives
considered and why-not, migration/rollback, and the test strategy.

Keep specs as short as they can be while removing ambiguity. Prose, not ceremony.

## Escalating quality (optional)
For high-risk or contested designs, run the **council** skill (model-diverse
review) or **cross-critique** (peer critique of competing approaches) on the spec
before sending it to review. Fold the strongest objections in.

## Output contract
```
factory advance <id> \
  --verdict ready_for_review \
  --summary "<what the spec decides, in one line>" \
  --artifact specs/<id>/PRODUCT.md [--artifact specs/<id>/TECH.md] \
  --confidence <0..1>
```
This routes the item to the **spec_review** human gate. If you genuinely cannot
spec it without a product decision, pull the escape hatch instead:
`--human-required --human-reason "<the decision you need>"` (no verdict needed).

## Quality bar
- Every acceptance criterion must be checkable by the verify station without you.
- Name the non-goals — scope creep is the most common reason a spec gets sent back.
- If the spec comes back with `needs_revision`, read the intervention record under
  `.factory/interventions/` — it says exactly what the human wanted. Address that
  specific gap, don't rewrite wholesale.
