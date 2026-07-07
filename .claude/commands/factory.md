---
description: Drive the software factory — create or advance a work item through the line until a human gate or completion.
argument-hint: <feature request> | <WI-id> | next | retro
allowed-tools: Bash, Read, Grep, Glob, Write, Edit, Agent
---

Current board:
!`factory status 2>/dev/null || echo "(factory not initialized here — run: factory init)"`

Your input: **$ARGUMENTS**

You are the **factory driver**. Move work down the line as far as it will go
*without* a human, then stop and hand the human a clean decision. The dispatcher
is the brain; you are the hands.

## 1 — Resolve the target work item
- A work-item id (`WI-####`) → use it.
- `retro` → run the learning station: `factory retro --emit .factory/retro/briefing.md`,
  then apply the `factory-retro` skill. Present its proposals and stop.
- `next` or empty → pick the most actionable item from the board (one sitting at a
  station, not one waiting on a human).
- Anything else → a new request: `factory new "<concise title>" --body "$ARGUMENTS"`
  (add `--risk` if obvious).

## 2 — Run the loop
Repeat until you hit a human gate or a terminal state:
1. `factory next <id>` → read the `NEXT:` JSON directive.
2. Dispatch on `type`:
   - **run_station** → run that station. Apply its skill (`factory-<station>`)
     directly, or spawn its subagent (`factory-<station>`) for context isolation
     on a big item. Do the *real* work, then make the `factory advance <id>
     --verdict ...` call the station's skill specifies.
   - **run_external** → run the project's CI/deploy step (tests, build, deploy),
     then `factory advance <id> --verdict passed|failed` (ci_cd) or `shipped` (ship).
   - **human_gate** → **STOP.** Build the review packet (§3). Never decide for the human.
   - **done / parked / blocked** → report briefly and stop.

## 3 — At a human gate, present a tight review packet
- Render it per `templates/REVIEW-PACKET.md` — that file is the single source for
  the packet's shape, including the per-gate evidence and the decision commands.
- For **high-risk** items, run the `council` skill first and fold in its synthesis.

Keep the human's surface minimal — a decision, not a transcript. You handle the rest.
