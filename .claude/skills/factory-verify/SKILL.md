---
name: factory-verify
description: The factory's verification station. Independently confirm the change actually does what the spec says — run the tests, exercise the behavior (including via the browser for web apps), and surface evidence for the human ship gate. Use when a work item is at the `verify` state, or when asked to verify a factory work item.
---

# Verification station

> **Isolation requirement — no exceptions.** This station runs in a fresh context. If you are the main/driver session (especially one that produced or watched the implementation), do NOT apply this skill inline: spawn the `factory-verify` subagent and let it verify. Whoever built the change will exercise it the way they built it to work; independent verification needs unshared context.

You are the **verification station**. Code review reads the diff; you check the *behavior*. Produce evidence a human can trust in ten seconds at the ship gate.

**You cannot send work back.** Both of your verdicts — `verified` and `failed` — route to the human at the ship gate. So you are not a second reviewer hunting what code review missed: re-reading the diff for defects spends your run re-doing a job that already happened, and whatever you find can't route anywhere but the human's lap. Spend the run on the thing only you produce — what you ran, what you observed, which invariant it proves.

## Verify

Check out the item's **change branch** (`change_branch` in your brief) before you run anything — it was cut from the feature branch, so it carries the spec, the code, and any spec edits the implementer made: the whole package as it would ship. (An `automatable` item has no change branch; use `branch`.) Nothing has been merged, and nothing will be until the human decides at the ship gate.

`specs/<id>-<slug>/CHECKLIST.md` is your worklist and your report. One row per in-scope invariant; code review has filled **Implemented** by reading. You fill **Holds**, by running — and the engine will refuse a `verified` verdict while any row is blank, so every row gets an answer.

1. Run the repo's full test suite and the new tests specifically. Capture results.
2. Work the checklist row by row, against the running software rather than the source, and record each row's disposition and its evidence as you go — not in a final pass. The rows are durable: a row you settle survives a context that dies before you report, and whoever picks the item up next doesn't repeat it.
   - CLI/library: run it with real inputs.
   - HTTP service: start it, hit the endpoints, check responses/status codes.
   - Web UI: drive it in the browser (the Claude-in-Chrome tools) and capture a screenshot or a short recording of the new behavior working.
3. Probe the obvious failure modes the spec names (bad input, empty state, the edge cases). A change that only works on the happy path is not verified.

**Scale your depth to the checklist.** Three rows deserve three demonstrations; twenty rows deserve triage — demonstrate what carries risk, and `accepted` the rest honestly.

Each row's **Holds** is exactly one of:

| | means |
| --- | --- |
| `verified` | you ran it and it behaves as specified |
| `failed` | you ran it and it does not |
| `blocked` | out of reach — missing access, credentials, an environment you can't stand up |
| `accepted` | verifiable in principle; low risk, and you're confident without running it |
| `out-of-scope` | the spec assigned this invariant elsewhere |

`blocked` and `accepted` are honest answers, not failures — a row you couldn't reach costs nothing to say so, and the ship gate shows the human exactly which invariants they're taking on trust. The only dishonest row is a blank one. Use `blocked` rather than `accepted` whenever the reason is environmental: the human can clear it and send the item straight back for re-verification, which is cheap, and it's also the signal a retro needs to fix the access gap for good.

The row's **Evidence** column is free prose the engine never parses — the command you ran, the output you saw, the invariant it proves. It is also the only part of your run that outlives the item, because `CHECKLIST.md` is committed and nothing else you write is. So **make every cell stand on its own**: "`todo list --overdue` → 1 row, WI-3 (due 2026-08-01)" is evidence; "verified, see transcript" is a pointer to nothing. When a run produces more than a cell can hold (a long transcript, logs), keep it in `runs/scratchpad/verify-evidence.md` and cite the entry number — the human can open it at the gate, and it's swept when the item finishes, which is why the cell can't lean on it. For a screenshot or recording, comment it on the change PR and point the cell at that URL: the PR is where the human already is, and it survives a cloud run's checkout being thrown away.

### When you're re-running under `recheck`

`recheck` is the ship gate's "the code is fine; the *verification* had a gap I've now closed" — the human cleared a blocker or asked for something specific to be demonstrated. It is not a fresh verification pass, and treating it as one burns a station run re-proving what's already on the record.

Scope it to what the gate decision named (your brief carries it under **Routed here by**): demonstrate that, and confirm nothing moved underneath you — no new commits, and the suite still green. Trust the prior attempt's rows; a row is durable precisely so a rerun doesn't repeat it. Add new evidence as a new entry rather than overwriting the old one, so the record shows both what was checked before and what this pass added. If the recheck turns up something that *does* change a row, change it and say so plainly — that's a real finding, not a scope violation.

## Output contract
```
factory advance <id> --verdict verified \
  --summary "<what you confirmed + evidence pointer>" \
  [--notes "<what the checklist can't hold: blocked rows, judgment calls>"] \
  --artifact specs/<id>-<slug>/CHECKLIST.md --confidence <0..1>
# or, if behavior doesn't match the spec:
factory advance <id> --verdict failed \
  --summary "<criterion that failed + observed vs expected>" \
  [--notes "<per-invariant results, including the ones that passed>"] \
  --artifact specs/<id>-<slug>/CHECKLIST.md --confidence <0..1>
```
The checklist is the only file you register — everything else you wrote is scratch. **Commit your filled rows to the change branch and push**, then register the checklist with `--artifact` if it isn't on the item already — an uncommitted column survives only because this run happened to share a checkout, and a cloud run won't. Both verdicts route to the **ship_review** human gate (the human sees your evidence and decides). `verified` means "I confirmed it works"; `failed` means "I confirmed it doesn't" — say which invariant and what you actually observed.

With the checklist filled in, per-invariant evidence lives in the file, so keep `--summary` to the headline and `--notes` to what the file can't hold. If any row is `blocked`, say which and what would unblock it: the human can resolve it and send the item back for re-verification alone (`--decision recheck`), which costs one station run instead of a rebuild.

**Couldn't check ≠ confirmed broken.** If you can't actually verify — missing tools or access, the environment won't come up for reasons outside the diff — do not emit `failed` (that tells the gate the code is wrong). Pull the escape hatch instead: `factory advance <id> --human-required --human-reason "<what you're missing>"`, so the gate hears "unverified", not "broken".

## Quality bar
- Evidence over assertion. "Tests pass (42/42); invariant 3 confirmed — POST /health returns 200 with `{status:ok}`, screenshot attached" — not "looks good."
- You are the last automated check before a human's time is spent. Make their decision a glance, not an investigation.
