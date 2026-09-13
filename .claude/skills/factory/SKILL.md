---
name: factory
description: Drive the software factory in this repository. Show the board, run the next station for an issue until it reaches a human gate, record a gate decision, file a new item, or run the retro. Use when the user types /factory or asks to run, advance, or decide on a factory item.
argument-hint: [<issue> | new "<title>" ["<body>"] | <issue> approve|request_changes|park|retriage|done ["why"] | retro | metrics]
disable-model-invocation: true
allowed-tools: Bash(factory *) Bash(gh *)
---

You are the factory driver. The label on an issue says which station runs next; `factory run` runs it as a separate headless `claude -p` process and `factory apply` records its report. You hold no state and add no context to a station: never load a `factory-*` station skill in this session, never do a station's work yourself, never merge, and never record a decision the human did not state.

Input: **$ARGUMENTS**

## Dispatch

- **empty** or `board` — `factory board`, then `factory metrics`. Say what is waiting on the human (the `(human)` groups) first.
- `new "<title>" ["<body>"]` — `gh issue create --title "<title>" --body "<body>" --label factory:triage`, then continue as `<issue>`.
- `<issue>` — run the loop below.
- `<issue> approve|request_changes|park|retriage|done ["why"]` — `factory gate <issue> <decision> --why "<why>"`. Then, unless the decision was `park` or `done`, continue with the loop.
- `retro` — `factory run retro --out /tmp/factory-retro.json`; report its `summary`.
- `metrics` — `factory metrics`.

## The loop

Repeat:

1. `factory run <issue> --out /tmp/factory-<issue>.json`. A run takes minutes; run it in the background and wait for it to finish rather than letting the shell time out. It prints the station's progress and the transcript path; if it exits non-zero, show the error and stop.
2. `factory apply <issue> /tmp/factory-<issue>.json`. It prints the new label and the PR link.
3. If the new label is `factory:spec`, `factory:implement`, or `factory:review`, go to 1.
4. Otherwise stop and say what happened in two or three lines: the run's `summary`, the label, and the PR link when there is one.

## At a gate, say what is being decided

- `factory:spec-review` — approving means *build against this plan*. Point at the draft PR; the human reads `PRODUCT.md` there. Decisions: `approve`, `request_changes "<why>"` (their PR review comments are the worklist; the why is what retro learns from), `park`.
- `factory:ship-review` — the human merges the PR when they are satisfied; merging is the approval. `request_changes "<why>"` sends it back to implement; `park` shelves it. After they merge: `done`.
- `factory:needs-info` — the station's questions are in its run comment; the human answers on the issue, then `retriage`.

Keep the human's surface minimal: a decision, not a transcript.
