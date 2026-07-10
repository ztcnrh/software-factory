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
  (add `--risk` and `--label`s if obvious — labels are what gate policies match on).

## 2 — Run the loop
Repeat until you hit a human gate or a terminal state:
1. `factory next <id>` → read the `NEXT:` JSON directive.
2. Dispatch on `type`:
   - **run_station** → run that station, then make the `factory advance <id>
     --verdict ...` call its skill specifies. *Where* it runs matters:
     - **Checking stations (`code_review`, `verify`) always run in their fresh
       subagent (`factory-<station>`) — no exceptions.** A checker sharing the
       session that produced the work grades its memory of the intent, not the
       artifact; isolation is what makes these independent checks instead of
       self-grading.
     - Producing stations (`triage`, `spec`, `implement`) may apply their skill
       (`factory-<station>`) directly in this session for low-risk or
       automatable items; spawn the subagent for anything bigger. Either way, a
       station works only from persisted artifacts (the work item, `specs/`,
       the diff) — never from this chat's memory.
   - **run_external** → the post-merge CI/CD deploy (build + deploy + health-wait);
     e.g. watch the merge's GitHub Actions run, then `factory advance <id>
     --verdict succeeded|failed`. A green deploy is the ship point → `done`.
   - **human_gate** → **STOP.** Build the review packet (§3). Never decide for the human.
   - **done / parked / blocked** → report briefly and stop.

## 3 — At a human gate, present a tight review packet
- Render it per `templates/REVIEW-PACKET.md` — that file is the single source for
  the packet's shape, including the per-gate evidence and the decision commands.
- For **high-risk** items, run the `council` skill first and fold in its synthesis.
- Record the decision under the human's **real identity** — `factory gate` auto-signs
  with the operator's git identity (override with `--by <name>`), so no extra step is
  needed. Only ever record a decision the human actually made; never sign a gate for them.

Keep the human's surface minimal — a decision, not a transcript. You handle the rest.
