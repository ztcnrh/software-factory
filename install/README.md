# Installing the factory into a repo

The factory operates *on* a target repository. This installer drops everything a repo needs to be driven by the factory.

```bash
# from the software-factory directory:
python3 install/install.py /path/to/your/repo --dry-run  # review the plan first (writes nothing)
python3 install/install.py /path/to/your/repo            # local-first
python3 install/install.py /path/to/your/repo --with-cloud     # also add the (disabled) workflows
python3 install/install.py /path/to/your/repo --with-direction # also plant a DIRECTION.md starter
python3 install/install.py /path/to/your/repo --upgrade      # three-way merge to the latest toolkit
python3 install/install.py /path/to/your/repo --force        # refresh factory-owned files (clobbers)
python3 install/install.py /path/to/your/repo --uninstall    # opt out (keeps .factory/ state)
```

Or let your agent drive it: in a Claude Code session in this repo, say *"install the factory into \<path\>"* — the `install-factory` skill plans with `--dry-run`, confirms with you, then installs and walks the first-run steps.

**Scope guarantee.** The installer only ever touches factory-owned paths (the list below). `--force` overwrites *those* — never anything else the project keeps under `.claude/` or elsewhere. Two shared files get special handling in every mode: `settings.json` is always **merged** (your own hooks/permissions survive), and `CLAUDE.md` is only ever written between its `<!-- factory:begin/end -->` markers.

**Updating.** Pull the latest toolkit, then run `--upgrade`. It diffs three ways per file — what's installed, what the toolkit shipped at install time (the manifest's commit is the baseline), and what it ships now — so it can do the right thing per file: apply toolkit changes to files you never touched, **keep** files the retro station (or you) improved locally, and flag true conflicts (both sides changed) for a hand merge, printing the exact diff commands for each. The kept-local list doubles as the **upstreaming radar** — local improvements the toolkit might want back. Nothing is ever clobbered; `--force` remains the explicit "take the toolkit side wholesale" escape hatch, and a plain rerun still just fills gaps. Every install stamps `.factory/install-manifest.json` (toolkit version + commit + what was created); a reinstall or upgrade prints what was there before, and pre-manifest installs fall back to a conservative two-way compare (differences are kept, never overwritten).

**Uninstalling.** `--uninstall` removes exactly what the installer created (per the manifest), strips the CLAUDE.md, `.gitignore`, and `.gitattributes` blocks, and unmerges the factory's settings entries — your own files are untouched. `.factory/` (work items, interventions, metrics) is deliberately left behind; delete it manually for a clean slate. `--dry-run` works here too.

### What it copies into your repo
- `.claude/skills/` — the station skills (triage, spec, implement, code-review, verify, retro), the spec-writing pair the spec station drives (`write-product-spec`, `write-tech-spec`), `council` (which includes its cross-critique second round), and `research` (delegate noisy investigation to a subagent, keep the caller's context clean). (The deferred `monitor` station is parked under `deferred/` and is not installed.)
- `.claude/agents/` — the matching subagents (isolated runners).
- `.claude/commands/` — `/factory` and `/factory-status`.
- `.claude/hooks/` + merged `.claude/settings.json` — the board + steering hooks.
- `line.yml`, `policies.yml` — the line and its gate policies.
- `classifiers.yml` — the vocabulary stations classify work items with, and what gate policies match on. Ships seeded with universal terms; yours to grow.
- `github-labels.yml` — the `factory:<state>` conveyor labels mirrored onto GitHub issues (presentation, not policy input). Named `labels.yml` before v0.6.0; an upgrade removes the old file.
- `FACTORY-MANUAL.md` — the human's operating guide (setup, gate playbook, homework).
- `templates/` — the live artifact shapes (the review packet; spec shapes live in the spec-writing skills); see its README.
- `.factory/` — empty runtime state dirs (the factory's memory).
- A marked block in **`.gitignore`** and **`.gitattributes`** (same `factory:begin`/`factory:end` mechanism as the CLAUDE.md block; only what's between the markers is ever written or removed). The first keeps factory *scratch* out of git — per-run station briefs, station scratchpads, and gate renders no decision bound to, all of which the engine can rebuild. The second marks `.factory/` as generated, so the factory's bookkeeping is still committed (a teammate needs the same board) but collapses in pull-request diffs instead of burying the change under review.
- A short **factory block in `CLAUDE.md`** (created or appended between `<!-- factory:begin/end -->` markers; reinstalls refresh only that block, your own content is never touched) — so every session discovers the factory even before the repo's hooks are trusted.
- `--with-cloud`: `.github/workflows/*.disabled` — the opt-in cloud layer.
- `--with-direction`: a `DIRECTION.md` starter at the repo root — the project north star / roadmap buckets / non-negotiables the spec station anchors specs to (it flags divergence rather than drifting). Planted once, then it's **yours**: untracked by the manifest, never overwritten (not even by `--force`), never uninstalled. Skipped the flag? Copy `templates/DIRECTION.md` yourself anytime.

### Then
1. `uv tool install /path/to/software-factory` — puts the `factory` CLI on PATH.
2. `factory init` in your repo — validates config, creates state dirs.
3. **Commit the installed files.** `.claude/` and `.factory/` are dot-directories — some IDE file explorers hide them by default, so check they're visible and *not* gitignored. They're meant to live in version control: `.factory/` is the factory's durable memory, and `.claude/` skills evolve as the retro station learns — the repo history is both the audit trail and your revert path.
4. `factory new "..."` then `/factory` in Claude Code — drive the line.
5. (Optional) `factory github-labels --github` — create the conveyor labels in GitHub.

The local source of truth is `.factory/`. GitHub is an optional mirror; the cloud workflows are off until you rename them, add an `ANTHROPIC_API_KEY` secret, and set the `FACTORY_TOOLKIT_GIT` repo variable they install the CLI from (see `docs/CLOUD-AUTONOMY.md`).
