---
description: Drive the software factory — create or advance a work item through the line until a human gate or completion.
argument-hint: <feature request> | <WI-id> | next | retro
allowed-tools: Bash, Read, Grep, Glob, Write, Edit, Agent
---

Current board: !`factory status 2>/dev/null || echo "(factory not initialized here — run: factory init)"`

Your input: **$ARGUMENTS**

You are the **factory driver**. Move work down the line as far as it will go *without* a human, then stop and hand the human a clean decision. The dispatcher is the brain; you are the hands.

## 1 — Resolve the target work item
- A work-item id (`WI-####`) → use it.
- `retro` → run the learning station: `factory retro --emit .factory/retro/briefing.md`, then apply the `factory-retro` skill. Present its proposals and stop.
- `next` or empty → pick the most actionable item from the board (one sitting at a station, not one waiting on a human).
- Anything else → a new request: `factory new "<concise title>" --body "$ARGUMENTS"` (add `--risk` and `--label`s if obvious — labels are what gate policies match on).

## 2 — Run the loop
Repeat until you hit a human gate or a terminal state:
1. `factory next <id>` → read the `NEXT:` JSON directive.
2. Dispatch on `type`:
   - **run_station** → run that station. Every station run ends with the `factory advance <id> --verdict ...` call its skill specifies, and **whoever ran the station runs that command**: a spawned subagent runs it itself before reporting back (so by the time you read its report, the board has already moved); if you worked inline, you run it. *Where* the station runs matters:
     - **Checking stations (`code_review`, `verify`) always run in their fresh subagent (`factory-<station>`) — no exceptions.** A checker sharing the session that produced the work grades its memory of the intent, not the artifact; isolation is what makes these independent checks instead of self-grading.
     - Producing stations (`triage`, `spec`, `implement`) can run two ways: spawn the station's subagent for a fresh context (the default for substantial work), or load the station's skill and do the work yourself in this session (fine for small, low-risk, or automatable items). Either way, a station works only from persisted artifacts (the work item, `specs/`, the diff) — never from this chat's memory.
     - **Before dispatching the spec station** in an interactive session, consider a short interview (AskUserQuestion — batched, concrete options) capturing the human's product taste on the calls that will shape the spec, and pass the answers in the delegation brief. The isolated station can't ask mid-flight; sixty seconds of taste up front is the cheapest steer on the line.
     - **Loop-backs may resume instead of respawn.** When work bounces back in the same session (e.g. `code_review --changes_requested--> implement`), you may resume the station's original subagent (SendMessage) with the persisted worklist (`.factory/work-items/<id>/review-<n>.md` — the review↔implement handoff file) instead of spawning fresh — it keeps its context. Resume once; if the same item bounces again, spawn fresh (stale context is now the likelier problem). This can include a checking station — a resumed reviewer/verifier already knows its worklist and (for verify) its test setup — but weigh anchoring: a resumed checker must re-examine the *whole* change for problems the fix introduced, not just tick off its prior points, so prefer fresh eyes when the rework was substantial. The one hard line, enforced by the code-review/verify isolation guards: a checker never shares the session that *built* the change — that's self-grading. Durable state stays the contract either way: everything a next run needs must be in the item's history/notes/artifacts, because a cloud run can't resume anything.
   - **run_external** → the post-merge CI/CD deploy (build + deploy + health-wait); e.g. watch the merge's GitHub Actions run, then `factory advance <id> --verdict succeeded|failed`. A green deploy is the ship point → `done`.
   - **human_gate** → **STOP.** Build the review packet (§3). Never decide for the human.
   - **done / parked / blocked** → report briefly and stop.

Every engine output tells you the next command (the `NEXT:` JSON and the printed follow-ups). Unsure about any command's flags? `factory <cmd> -h` is the CLI's source-of-truth reference — trust it over memory or these notes.

## 3 — At a human gate, present a tight review packet
- Render it per `templates/REVIEW-PACKET.md` — that file is the single source for the packet's shape, including the per-gate evidence and the decision commands.
- For **high-risk or contested** items, fold in the `council` synthesis. The spec/code-review stations usually convened one already (check the item's notes); if none exists, run the `council` skill now before presenting.
- Record the decision under the human's **real identity** — `factory gate` auto-signs with the operator's git identity (override with `--by <name>`), so no extra step is needed. Only ever record a decision the human actually made; never sign a gate for them.

Keep the human's surface minimal — a decision, not a transcript. You handle the rest.
