---
name: install-factory
description: Adopt this software factory into a target repository, agent-guided. Use when someone asks to install, adopt, or set up the factory in their project ("install this factory into my repo", "set this up for ~/code/myapp"). Plans first with --dry-run, confirms with the human, then installs and walks the post-install steps. Toolkit-only — not copied into target repos.
---

# Install the factory into a repo

You are guiding a human through adopting the factory into their project. Plan first, confirm, then act — never install without showing what will happen.

## 1 — Orient the human (one short paragraph)

If they seem new to the factory, say what they're adopting: an agentic delivery line — a deterministic dispatcher (`factory` CLI + `line.yml`) drives work items through stations (triage → spec → implement → code-review → verify), pauses at human gates for their decisions, and learns from every steer (the retro station). Point them at `README.md` for the pitch and `FACTORY-MANUAL.md` for what *they* will do day to day. Don't lecture; one paragraph and the pointers.

## 2 — Resolve the target and plan

- Confirm the target repo path (must be an existing directory, ideally a git repo).
- Run the plan: `python3 install/install.py <target> --dry-run` (from this toolkit's root).
- Show the human the operation list, and flag anything notable: `skip (exists)` lines mean those files are already there (a previous install — reinstalling only fills gaps unless `--force`, which overwrites and would clobber any retro-made local improvements); the CLAUDE.md line only ever touches the `<!-- factory:begin/end -->` block.
- Ask whether to include the cloud layer (`--with-cloud`, ships disabled either way). Default: without.
- Ask whether to plant a `DIRECTION.md` starter (`--with-direction`) — the project north-star doc the spec station anchors specs to. Worth a yes when the repo will run with real autonomy or the direction lives only in the human's head; it's theirs to fill in afterward (untracked, never overwritten or uninstalled). Skippable — `templates/DIRECTION.md` can be copied later.

## 3 — Install (only after the human confirms)

```
python3 install/install.py <target> [--with-cloud]
```

## 4 — Walk the post-install steps

1. `uv tool install <toolkit-path>` — puts the `factory` CLI on PATH (skip if already installed).
2. `cd <target> && factory init` — validates config, creates state dirs.
3. **Commit the installed files.** `.claude/` and `.factory/` are dot-directories — some IDE file explorers hide them, so confirm they're visible and not gitignored. They belong in version control: `.factory/` is the factory's memory, `.claude/` skills evolve as the retro learns, and git history is the revert path if anything (like a `--force` refresh) ever overwrites a local improvement.
4. Remind them: on their first Claude Code session in the target repo, Claude Code will ask to trust the project's hooks — say yes, that's the factory's board + steering capture.
5. If you planted `DIRECTION.md`, nudge them to spend ten minutes filling it in (north star, Now/Next/Later, non-negotiables) — the spec station anchors to it from the very first item.
6. First drive: `factory new "<something small>"` then `/factory` in a Claude Code session in that repo.

Their guide from here is the target repo's own `FACTORY-MANUAL.md` (the install put it there). If they ever want out: `python3 install/install.py <target> --uninstall` removes exactly what the installer created (their own files and `.factory/` history stay) — worth mentioning up front; it lowers the cost of trying.
