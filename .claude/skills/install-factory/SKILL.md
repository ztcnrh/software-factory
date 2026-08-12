---
name: install-factory
description: Drive the software factory's full adoption lifecycle in a target repo, agent-guided — install, upgrade (merge-aware), or uninstall. Use when someone asks to install / adopt / set up the factory, update / upgrade / pull the latest toolkit, or remove / opt out of it in a project. Plans with --dry-run, confirms, then executes and walks the steps itself. Toolkit-only — not copied into target repos.
---

# Operate the factory's adoption lifecycle

You drive adoption end-to-end for the human — they should never have to run a command themselves. Work out which operation they want, plan it with `--dry-run` and show them, get a yes, then run every step yourself from this toolkit's root. `python3 install/install.py -h` is the authoritative flag reference; every operation supports `--dry-run` (plans, writes nothing) — always run that first.

## Route by what they asked

| They want… | Operation |
| --- | --- |
| install / adopt / set up the factory in `<repo>` | **Install** (first time) |
| update / upgrade / pull the latest toolkit | **Upgrade** (merge-aware) |
| uninstall / remove / opt out | **Uninstall** |
| add the cloud layer, or a `DIRECTION.md` | rerun Install with `--with-cloud` / `--with-direction` |

Not sure whether a repo already has the factory? `.factory/install-manifest.json` present means it does — that's an **Upgrade**, not a fresh install.

## Install (first time)

- If they're new, orient in one paragraph: an agentic delivery line — a deterministic dispatcher (`factory` CLI + `line.yml`) drives work items through stations (triage → spec → implement → code-review → verify), pauses at human gates for their decisions, and learns from every steer (the retro station). Point at `README.md` (the pitch) and `FACTORY-MANUAL.md` (their day-to-day). One paragraph, then the pointers.
- Confirm the target path (an existing directory, ideally a git repo).
- `python3 install/install.py <target> --dry-run`, and show the plan. `skip (exists)` lines are files already there; the CLAUDE.md line only ever touches the `<!-- factory:begin/end -->` block.
- Offer the two opt-ins: cloud workflows (`--with-cloud`, ship disabled either way) and a `DIRECTION.md` starter (`--with-direction`, the north-star doc the spec station anchors to — theirs to fill in, untracked, never overwritten). Default both off unless the repo will run with real autonomy.
- On yes: `python3 install/install.py <target> [flags]`, then the first-run steps below.

## Upgrade (a repo that already has the factory)

The safe update path — it never clobbers local work. Have them pull the latest toolkit first, then:

1. `python3 install/install.py <target> --upgrade --dry-run` — read the summary line and the per-file classification: `upgrade` (a toolkit change applied to a file they never touched), `kept (your changes…)` + the 📡 radar (a local improvement kept intact), `conflict — kept yours` (both sides changed), `install (new)`.
2. Show them, then run `--upgrade` for real.
3. For each conflict, run the two diff commands it printed to surface both sides, and offer to merge by hand — nothing was overwritten, their version stands until they choose otherwise.
4. Have them review the git diff and commit. `--force` is the explicit "take the toolkit side wholesale" clobber — only on request, and warn first.

If `--upgrade` reports *everything* as `conflict … (no baseline)`, the manifest's install commit is no longer reachable in this toolkit checkout (rebased or squashed away). Say so plainly — the honest fix is a per-file hand-merge, or a `--force` only after they've committed/stashed their local changes so git is their safety net; never a blind force.

## Uninstall (opt out)

The low-cost exit — worth naming even at install time, it lowers the cost of trying.

1. `python3 install/install.py <target> --uninstall --dry-run`, and show what leaves.
2. On yes: `--uninstall`. It removes exactly what the installer created, strips only the marked blocks it planted (CLAUDE.md, `.gitignore`, `.gitattributes`), and unmerges only the factory's settings entries. Their own files, `.factory/` history, a filled-in `DIRECTION.md`, and any workflow they enabled all stay put. `.factory/` is left on purpose — delete it by hand only if they want a clean slate.

## First-run steps (after a fresh install)

1. `uv tool install <toolkit-path>` — puts the `factory` CLI on PATH (skip if already installed). You can run this.
2. `cd <target> && factory init` — validates config, creates state dirs. You can run this.
3. Tell them to **commit the installed files.** `.claude/` and `.factory/` are dot-directories some IDE explorers hide — confirm they're visible and not gitignored. They belong in version control: `.factory/` is the factory's memory, `.claude/` skills evolve as the retro learns, and git history is the revert path if a `--force` ever overwrites a local improvement. The install also plants ignore rules for the factory's *scratch* (per-run briefs, station scratchpads, undecided gate renders) and marks `.factory/` generated so it collapses in PR diffs — mention it if they ask why their work-item PRs stay readable.
4. On their first Claude Code session in the repo, Claude Code will ask to trust the project's hooks — they should say yes (the factory's board + steering capture). This one's theirs, not yours.
5. If you planted `DIRECTION.md`, nudge them to spend ten minutes filling it in (north star, Now/Next/Later, non-negotiables) — the spec station anchors to it from the first item.
6. First drive: `factory new "<something small>"` then `/factory` in a Claude Code session in that repo.

Their guide from here is the target repo's own `FACTORY-MANUAL.md` (the install put it there).
