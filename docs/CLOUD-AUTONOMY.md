# Cloud autonomy (opt-in)

The "runs while you sleep" layer. It's **off by default** and the least battle-tested part of the system — turn it on deliberately, on a sandbox repo first, and supervise the first runs. Everything else works fully without it.

## What it does

GitHub becomes the conveyor. A `factory:<state>` label on an issue triggers a workflow that runs that station headlessly (`claude -p`), calls `factory advance`, commits the updated `.factory/` state, and re-labels the issue — which triggers the next run. The line moves itself.

Human-gate labels (`factory:spec-review`, `factory:ship-review`) deliberately **don't** auto-run: the workflow comments the review packet on the issue and waits for you.

Two workflows ship, both as `.disabled`: **`factory-station.yml`** (the per-station runner, triggered by issue labels) and **`factory-retro.yml`** (the learning loop, weekly plus on-demand, opening improvement PRs).

## Enabling it

1. **Install with the cloud layer** — `python3 install/install.py /path/to/repo --with-cloud` drops the workflows under `.github/workflows/`, still `.disabled`.
2. **Add the API secret** — `ANTHROPIC_API_KEY` (or `CLAUDE_CODE_OAUTH_TOKEN`) under *Settings → Secrets and variables → Actions*.
3. **Point at the toolkit** — an Actions *variable* `FACTORY_TOOLKIT_GIT`, a pip-installable ref like `git+https://github.com/<you>/software-factory@main`. An adopted repo carries only the `.claude` layer and config, so the workflow installs the CLI from this ref; it fails fast with a clear message if unset. A private toolkit repo needs a token in the URL or its own checkout step.
4. **Create the labels** — `factory github-labels --github` (or without the flag to print them first).
5. **Flip the switch** — rename `factory-station.yml.disabled` → `factory-station.yml`, and the retro one if you want scheduled learning.
6. **Shake it down** — open an issue, add `factory:triage`, and *watch* the Actions run. Keep a hand on the wheel for the first several items.

## How it stays safe

- **Human gates never auto-run.** The `if:` guard fires only for station labels. A spec or ship decision always waits for you, cloud or not.
- **One source of truth.** State lives in `.factory/`, committed back by each run, so you can switch between driving locally and letting the cloud run without divergence.
- **It's reversible.** Rename the workflows back to `.disabled` and you're fully local again, having lost nothing.
- **Policies still gate themselves.** Auto-approval happens only for rules you've signed, exactly as it does locally.

## Known rough edges

A well-commented **template**, not a turnkey product. Before relying on it:

- **Issue ↔ work-item mapping** is the seam most likely to need tightening for your conventions — the workflow hands the agent an issue number and trusts it to find or create the matching work item and re-label correctly. The deterministic half already exists: `factory intake` files every open `intake`-labeled issue as a work item, deduped on issue number. A small `issues: opened` workflow (or a local cron) running that makes issues the intake surface with no agent in the loop.
- **Concurrency** — two stations committing `.factory/` at once can race. Fine at low volume; add a concurrency group or a queue above that.
- **Cost and loops** — headless runs cost tokens, and a mis-configured route could loop. Watch the cost ledger and set Actions spending limits before going unattended.
- **Permissions** — the workflow runs with `acceptEdits` and broad tools by design. Scope `GITHUB_TOKEN` to the repo, and stay on a sandbox until you trust it.

The local loop is production-quality for personal use today; this one is the least exercised. Known gaps and the ideas for closing them are logged in [OPTIMIZATION-AREAS.md](OPTIMIZATION-AREAS.md).
