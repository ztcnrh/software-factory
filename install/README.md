# Installing the factory into a repo

The factory operates *on* a target repository. This installer drops everything a
repo needs to be driven by the factory.

```bash
# from the software-factory directory:
python3 install/install.py /path/to/your/repo            # local-first
python3 install/install.py /path/to/your/repo --with-cloud   # also add the (disabled) workflows
```

### What it copies into your repo
- `.claude/skills/` — the station skills (triage, spec, implement, code-review,
  verify, monitor, retro) + `council` and `cross-critique`.
- `.claude/agents/` — the matching subagents (isolated runners).
- `.claude/commands/` — `/factory` and `/factory-status`.
- `.claude/hooks/` + merged `.claude/settings.json` — the board + steering hooks.
- `line.yml`, `policies.yml`, `labels.yml` — the line, gate policies, labels.
- `templates/` — the live artifact shapes (spec + review packet); see its README.
- `.factory/` — empty runtime state dirs (the factory's memory).
- `--with-cloud`: `.github/workflows/*.disabled` — the opt-in cloud layer.

### Then
1. `uv tool install /path/to/software-factory` — puts the `factory` CLI on PATH.
2. `factory init` in your repo — validates config, creates state dirs.
3. `factory new "..."` then `/factory` in Claude Code — drive the line.
4. (Optional) `factory labels --github` — create the conveyor labels in GitHub.

The local source of truth is `.factory/`. GitHub is an optional mirror; the cloud
workflows are off until you rename them and add an `ANTHROPIC_API_KEY` secret
(see `docs/CLOUD-AUTONOMY.md`).
