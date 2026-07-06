# Review packet — <WI-id> @ <gate>

> The shape the `/factory` driver presents when it stops at a human gate. The goal
> is a **decision in ten seconds**, not a transcript to wade through.

**Item:** <title>
**Station output:** <what was produced> — <links: spec files / PR / screenshot>
**Confidence:** <0..1>   ·   **Risk:** <low | medium | high>
**Evidence:** <verification results / spec decisions / council synthesis>

## Your decision
- ✅ **Approve** → `factory gate <WI-id> --decision <approved>`
- ↩️ **Send back** → `factory gate <WI-id> --decision <needs_revision | not_ready> \`
  `--changed --notes "<what & why>" --category <kind>`

If you send it back or approve-with-tweaks, the `--notes` and `--category` are
exactly what the **learning loop** uses to make this gate disappear for this class
of work over time. Thirty seconds of "why" now buys you fewer gates later.
