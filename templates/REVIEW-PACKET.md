# Review packet — <WI-id> @ <gate>

> The shape the `/factory` driver (or a cloud station commenting on an issue) renders when the line stops at a human gate. The goal is **orientation in ten seconds** — everything worth reviewing is one link away, nothing to hunt for. The review itself takes as long as it deserves: the spec gate merits a real read (plan quality decides outcome quality), and the ship gate merits a real diff-plus-evidence review. The packet's job is that none of that time is spent assembling context.
>
> The packet is a message in the conversation, not a file — everything in it renders from state already on disk. When the item has a PR, its headline (the verification counts and the decision being asked) also lands there as a comment, so the ask is visible where the review actually happens; inline comments the human leaves in return are gate input, read back with `factory feedback <id>`. The driver runs `factory gate <id> --bind` before presenting, which content-hashes the item's artifacts and records both PR pointers and both branch tips (local and remote), so the decision below is checked against exactly what was reviewed — down to the commit — and refused if any of it moved first.

**Item:** <title> — one paragraph: what it is and what the station produced. **Artifacts:** <links: spec files / PR / diff / screenshot> **Confidence:** <0..1>   ·   **Risk:** <low | medium | high>

**Verification:** at `ship_review`, lead with the checklist's own counts — `<n>/<total> invariants verified by running`, then every row that wasn't, by number and category (`blocked`, `accepted`, `out-of-scope`). This is the line the human reads first: it says what was actually demonstrated versus what they're being asked to take on trust, without opening the evidence.

**Evidence:**
- `spec_review` → the spec's key decisions + open questions, and the item's PR (the feature branch against the integration branch — carrying only the spec so far). Approving means *build against this plan*; nothing lands here.
- `ship_review` → the filled checklist (`specs/<id>-<slug>/CHECKLIST.md` — per-invariant evidence lives there), the test results, both PRs (the pass under review and the item's own), and if it looped through code review, the change PR's review threads — the review↔implement conversation, each ask answered in place.
- If a station convened a `council` on the item (check its notes) → fold in the synthesis and any split. Councils are rare by design, so most packets won't have one.

## Your decision
- ✅ **Approve** → `factory gate <WI-id> --decision approved` — your call that it's good. The merges stay yours, in your own UI, whenever you want them.
- ✏️ **Approve with changes** — you fixed the work at the gate, by hand *or by directing your agent*, rather than sending it back → add `--changed --notes "<what changed & why>"` (`--changed` exists for exactly this case: the decision alone wouldn't reveal the steer)
- ↩️ **Send back** → `factory gate <WI-id> --decision <needs_revision | not_ready> \` `--notes "<what & why>" --category <kind>`
- 🔁 **Re-verify** (ship gate only) → `factory gate <WI-id> --decision recheck --notes "<the blocker you cleared>"` — for when the code is fine and the only gap is a `blocked` row you've now unblocked (access granted, environment up). It re-runs verification alone rather than the whole code loop.
- 🏷 **Fix a classification** → add `--retract <name> --retract-reason "<why>"` to any decision. Unlike a station's, your retraction works on any classifier, whoever applied it.
- ⏸ **Shelve** → `factory gate <WI-id> --decision park --notes "<why not-now>" --category <kind>` (→ `parked`, revivable later)

A send-back or park counts as a steer on its own — no `--changed` needed there. Rule of thumb: a small fix applied at the gate → approve `--changed`; anything that needs the station to redo its work → send back.

Every decision is **signed**: `factory gate` records it under your git identity automatically (override with `--by <name>`; a cloud station passes the reviewer's `github.actor`), so who approved what is tracked with no extra typing.

If you send it back or approve-with-tweaks, the `--notes` and `--category` are exactly what the **learning loop** uses to make this gate disappear for this class of work over time. Thirty seconds of "why" now buys you fewer gates later. Name a `--category` for the *failure mode*, not the fix (`missing-edge-case`, not `add-validation`), in kebab-case, and reuse an existing one wherever it fits — the retro's recurrence check joins on that exact string, so a near-miss spelling quietly breaks it. The CLI prints the categories already in use whenever you introduce a new one.
