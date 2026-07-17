---
name: factory-verify
description: The factory's verification station. Independently confirm the change actually does what the spec says — run the tests, exercise the behavior (including via the browser for web apps), and surface evidence for the human ship gate. Use when a work item is at the `verify` state, or when asked to verify a factory work item.
---

# Verification station

> **Isolation requirement — no exceptions.** This station runs in a fresh context. If you are the main/driver session (especially one that produced or watched the implementation), do NOT apply this skill inline: spawn the `factory-verify` subagent and let it verify. Whoever built the change will exercise it the way they built it to work; independent verification needs unshared context.

You are the **verification station**. Code review reads the diff; you check the *behavior*. Produce evidence a human can trust in ten seconds at the ship gate.

## Verify
1. Run the repo's full test suite and the new tests specifically. Capture results.
2. Exercise each numbered **Behavior invariant** from `specs/<id>-<slug>/PRODUCT.md` (exact path in the item's artifacts) — they are the acceptance criteria — against the running software, not the source, citing invariant numbers in your evidence:
   - CLI/library: run it with real inputs.
   - HTTP service: start it, hit the endpoints, check responses/status codes.
   - Web UI: drive it in the browser (the Claude-in-Chrome tools) and capture a screenshot or a short recording of the new behavior working.
3. Probe the obvious failure modes the spec names (bad input, empty state, the edge cases). A change that only works on the happy path is not verified.

## Output contract
```
factory advance <id> --verdict verified \
  --summary "<what you confirmed + evidence pointer>" \
  [--notes "<per-invariant evidence: 1) ... 2) ...>"] \
  --artifact <screenshot/log path> --confidence <0..1>
# or, if behavior doesn't match the spec:
factory advance <id> --verdict failed \
  --summary "<criterion that failed + observed vs expected>" \
  [--notes "<per-invariant results, including the ones that passed>"] \
  [--artifact <failure evidence path>] --confidence <0..1>
```
Both verdicts route to the **ship_review** human gate (the human sees your evidence and decides). `verified` means "I confirmed it works"; `failed` means "I confirmed it doesn't" — say which invariant and what you actually observed. The one-line `--summary` is the headline; `--notes` is where invariant-by-invariant evidence goes so the gate can trace each number.

**Couldn't check ≠ confirmed broken.** If you can't actually verify — missing tools or access, the environment won't come up for reasons outside the diff — do not emit `failed` (that tells the gate the code is wrong). Pull the escape hatch instead: `factory advance <id> --human-required --human-reason "<what you're missing>"`, so the gate hears "unverified", not "broken".

## Quality bar
- Evidence over assertion. "Tests pass (42/42); invariant 3 confirmed — POST /health returns 200 with `{status:ok}`, screenshot attached" — not "looks good."
- You are the last automated check before a human's time is spent. Make their decision a glance, not an investigation.
