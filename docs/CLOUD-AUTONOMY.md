# Cloud autonomy (opt-in)

This is the "factory runs while you sleep" layer. It's **off by default** and the least battle-tested part of the system — turn it on deliberately, on a sandbox repo first, and supervise the first runs. Everything works fully without it; this only adds *unattended* operation.

## What it does

GitHub becomes the conveyor. When an issue gets a `factory:<state>` label, a workflow runs the matching station headlessly with Claude Code (`claude -p`), which does the work, calls `factory advance`, commits the updated `.factory/` state, and re-labels the issue to the next state — which triggers the next run. The line moves itself. Human-gate labels (`factory:spec-review`, `factory:ship-review`) deliberately **don't** auto-run: the workflow comments the review packet on the issue and waits for you.

Two workflows ship (as `.disabled`):
- **`factory-station.yml`** — the per-station runner, triggered by issue labels.
- **`factory-retro.yml`** — the learning loop on a schedule (weekly) plus on-demand, opening improvement PRs.

## Enabling it

1. **Install with the cloud layer:** `python3 install/install.py /path/to/repo --with-cloud`. This drops the workflows under `.github/workflows/` (still `.disabled`).
2. **Add the API secret:** repo *Settings → Secrets and variables → Actions →* `ANTHROPIC_API_KEY` (or `CLAUDE_CODE_OAUTH_TOKEN`).
3. **Create the labels:** `factory labels --github` (uses your `gh` CLI). Or `factory labels` to print them first.
4. **Flip the switch:** rename `factory-station.yml.disabled` → `factory-station.yml` (and the retro one if you want scheduled learning).
5. **Shake it down:** open an issue, add `factory:triage`, and *watch* the Actions run. Keep a hand on the wheel for the first several items.

## How it stays safe

- **Human gates never auto-run.** The `if:` guard only fires for station labels, never gate labels. A spec or ship decision always waits for you, in cloud mode too.
- **Local and cloud share one source of truth.** State lives in `.factory/`, committed back by each run, so you can switch between driving locally and letting the cloud run without divergence.
- **It's reversible.** Rename the workflows back to `.disabled` and you're fully local again, having lost nothing.
- **Policies still gate themselves.** Auto-approval only happens for rules you've signed (`approved_by`), the same as local.

## Known rough edges (be honest with yourself here)

This layer is a solid, well-commented **template**, not a turnkey product. Before relying on it:

- **Issue ↔ work-item mapping.** The workflow hands the agent the issue number and trusts it to find/create the matching work item in `.factory/` and re-label correctly. That works because the agent is capable, but it's the seam most likely to need tightening for your repo's conventions — consider a small `issues: opened` workflow that calls `factory new` and applies `factory:triage` deterministically.
- **Concurrency.** Two stations committing `.factory/` state at once can race. For low volume it's fine; at higher throughput add a concurrency group or a queue.
- **Cost and loops.** Headless runs cost tokens and a mis-configured route could loop. Start with the Monitor station off, watch the metrics/cost ledger, and set GitHub Actions spending limits.
- **Permissions.** The workflow runs with `acceptEdits` and broad tools by design (it's unattended). Scope the `GITHUB_TOKEN` permissions to the repo and keep it on a sandbox until you trust it.

The local loop is production-quality for personal use today. The cloud loop is where you and I will iterate next — see [EXTENDING.md](EXTENDING.md).
