# Extending the factory — and what's still hard

## Where the knobs are

| To change | Edit | Worth knowing |
|---|---|---|
| the line's shape — add a station, reroute, auto-loop instead of gating | `line.yml`, plus the station's two files: `.claude/skills/factory-<name>/SKILL.md` and `.claude/agents/factory-<name>.md` | Routing is validated on load, so a malformed line fails loudly instead of mis-routing quietly. What belongs in which file: [ARCHITECTURE.md](ARCHITECTURE.md). |
| a station's cost | `model:` in its agent file | Sharpen the `SKILL.md` first — usually the cheaper fix, and the retro often proposes exactly that edit. Which station runs on what, and why: the station table in [ARCHITECTURE.md](ARCHITECTURE.md). |
| tracker integration | a tracker MCP on triage/spec, or an adapter in `src/factory/adapters/` | An absent MCP is a graceful no-op — drop the entry if you don't use it. |

Two tracker gotchas. The MCP's tool identifier depends on **how it was installed**: the shipped `mcp__plugin_atlassian_atlassian` is the Claude Code plugin form, while the same server added via `.mcp.json` would be `mcp__atlassian`. And a headless cloud run has no interactively-authenticated MCP at all, so it needs a token-authenticated CLI or API instead.

Stations are language-agnostic — they read the repo's stack and follow its conventions. What they depend on is a **test command, a linter, and a way to run the thing**. Where those are weak, verify is weak.

## Where it's hard

| The limit | What it means for you |
|---|---|
| **Verify is the ceiling.** Automation can prove an endpoint returns 422; it can't judge whether a UI feels right. | The one-shot ship rate climbs fast on backend, CLI, and library work, and plateaus lower on frontend polish. |
| **Triage and spec set everything downstream.** A wrong `automatable`, or a plausible-but-vague spec, sails through review and burns a whole cycle. | Spend your attention at `spec_review`. A caught spec error is the cheapest error to catch. |
| **The retro can overfit.** A policy proposed off one or two data points removes oversight from a whole class of work. | Merge skill edits freely — they can only make a station more thorough. Treat every gate policy as a small, near-irreversible call. |
| **It needs a repo with a shape to hold to.** Stations read the stack, the conventions and the tests; the checkers grade against them. | Day-one greenfield is the *worst* fit — nothing to read, nothing to verify against, and scaffolding is work a single agent session does better. Bootstrap first, then hand it over. Large brownfield works, but point it at a scoped slice: a subtle convention violation can pass review. |
| **Cost is half the North Star.** A misrouted item loops and burns tokens. | Watch **runs per shipped** in `factory metrics` — six is the floor, one run per station on a clean pass. Rework is where the money goes; a council on an ordinary item is the first knob to check. |
| **It won't invent product judgment.** Priorities and architecture you haven't delegated surface as gate decisions, by design. | Taste, priorities, and "is this the right thing to build" stay yours. |

The cloud layer is a template, not a product — the local loop is solid, the unattended one is least exercised. See [CLOUD-AUTONOMY.md](CLOUD-AUTONOMY.md).
