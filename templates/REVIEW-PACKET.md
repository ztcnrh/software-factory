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
- ✅ **Approve** → `factory gate <WI-id> --decision <approved>`
- ↩️ **Send back** → `factory gate <WI-id> --decision <needs_revision | not_ready> \`
  `--changed --notes "<what & why>" --category <kind>`
- ⏸ **Shelve** → `factory gate <WI-id> --decision park --changed --notes "<why now-not>" --category <kind>`
  (→ `parked`, revivable later)

If you send it back or approve-with-tweaks, the `--notes` and `--category` are
exactly what the **learning loop** uses to make this gate disappear for this class
of work over time. Thirty seconds of "why" now buys you fewer gates later.
