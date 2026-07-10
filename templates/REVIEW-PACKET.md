# Review packet — <WI-id> @ <gate>

> The shape the `/factory` driver (or a cloud station commenting on an issue) renders
> when the line stops at a human gate. The goal is a **decision in ten seconds**, not
> a transcript to wade through.

**Item:** <title> — one paragraph: what it is and what the station produced.
**Artifacts:** <links: spec files / PR / diff / screenshot>
**Confidence:** <0..1>   ·   **Risk:** <low | medium | high>
**Evidence:**
- `spec_review` → the spec's key decisions + open questions.
- `ship_review` → the verification results (tests run, behavior exercised).
- High-risk items → fold in the `council` skill's synthesis.

## Your decision
- ✅ **Approve** → `factory gate <WI-id> --decision approved`
- ✏️ **Approve, but you edited the work yourself** → add `--changed --notes "<what you changed & why>"`
  (`--changed` exists for exactly this case: the decision alone wouldn't reveal the steer)
- ↩️ **Send back** → `factory gate <WI-id> --decision <needs_revision | not_ready> \`
  `--notes "<what & why>" --category <kind>`
- ⏸ **Shelve** → `factory gate <WI-id> --decision park --notes "<why not-now>" --category <kind>`
  (→ `parked`, revivable later)

A send-back or park counts as a steer on its own — no `--changed` needed there.

Every decision is **signed**: `factory gate` records it under your git identity
automatically (override with `--by <name>`; a cloud station passes the reviewer's
`github.actor`), so who approved what is tracked with no extra typing.

If you send it back or approve-with-tweaks, the `--notes` and `--category` are
exactly what the **learning loop** uses to make this gate disappear for this class
of work over time. Thirty seconds of "why" now buys you fewer gates later.
