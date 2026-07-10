# Installing the factory into a repo

The factory operates *on* a target repository. This installer drops everything a
repo needs to be driven by the factory.

```bash
# from the software-factory directory:
python3 install/install.py /path/to/your/repo --dry-run  # review the plan first (writes nothing)
python3 install/install.py /path/to/your/repo            # local-first
python3 install/install.py /path/to/your/repo --with-cloud   # also add the (disabled) workflows
python3 install/install.py /path/to/your/repo --force        # refresh factory-owned files
python3 install/install.py /path/to/your/repo --uninstall    # opt out (keeps .factory/ state)
```

Or let your agent drive it: in a Claude Code session in this repo, say
*"install the factory into \<path\>"* — the `install-factory` skill plans with
`--dry-run`, confirms with you, then installs and walks the first-run steps.

**Scope guarantee.** The installer only ever touches factory-owned paths (the list
below). `--force` overwrites *those* — never anything else the project keeps under
`.claude/` or elsewhere. Two shared files get special handling in every mode:
`settings.json` is always **merged** (your own hooks/permissions survive), and
`CLAUDE.md` is only ever written between its `<!-- factory:begin/end -->` markers.

**Updating.** Pull the latest toolkit, then rerun the installer: a plain rerun fills
gaps and refreshes the CLAUDE.md block; `--force` refreshes all factory-owned files
to the new version. Every install stamps `.factory/install-manifest.json` (toolkit
version + commit + what was created), and a reinstall prints what was there before.
⚠ If the retro station has improved this repo's skills/templates, `--force` replaces
them with toolkit versions — review the git diff before committing, and cherry-pick
any local improvements you want to keep (git history is your safety net).

**Uninstalling.** `--uninstall` removes exactly what the installer created (per the
manifest), strips the CLAUDE.md block, and unmerges the factory's settings entries —
your own files are untouched. `.factory/` (work items, interventions, metrics) is
deliberately left behind; delete it manually for a clean slate. `--dry-run` works
here too.

### What it copies into your repo
- `.claude/skills/` — the station skills (triage, spec, implement, code-review,
  verify, retro) + `council` and `cross-critique`. (The deferred `monitor` station
  is parked under `deferred/` and is not installed.)
- `.claude/agents/` — the matching subagents (isolated runners).
- `.claude/commands/` — `/factory` and `/factory-status`.
- `.claude/hooks/` + merged `.claude/settings.json` — the board + steering hooks.
- `line.yml`, `policies.yml`, `labels.yml` — the line, gate policies, labels.
- `FACTORY-MANUAL.md` — the human's operating guide (setup, gate playbook, homework).
- `templates/` — the live artifact shapes (spec + review packet); see its README.
- `.factory/` — empty runtime state dirs (the factory's memory).
- A short **factory block in `CLAUDE.md`** (created or appended between
  `<!-- factory:begin/end -->` markers; reinstalls refresh only that block, your
  own content is never touched) — so every session discovers the factory even
  before the repo's hooks are trusted.
- `--with-cloud`: `.github/workflows/*.disabled` — the opt-in cloud layer.

### Then
1. `uv tool install /path/to/software-factory` — puts the `factory` CLI on PATH.
2. `factory init` in your repo — validates config, creates state dirs.
3. **Commit the installed files.** `.claude/` and `.factory/` are dot-directories —
   some IDE file explorers hide them by default, so check they're visible and *not*
   gitignored. They're meant to live in version control: `.factory/` is the
   factory's durable memory, and `.claude/` skills evolve as the retro station
   learns — the repo history is both the audit trail and your revert path.
4. `factory new "..."` then `/factory` in Claude Code — drive the line.
5. (Optional) `factory labels --github` — create the conveyor labels in GitHub.

The local source of truth is `.factory/`. GitHub is an optional mirror; the cloud
workflows are off until you rename them and add an `ANTHROPIC_API_KEY` secret
(see `docs/CLOUD-AUTONOMY.md`).
