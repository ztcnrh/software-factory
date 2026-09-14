# Software Factory

A software factory that lives in GitHub Actions. Open an issue and Claude Code triages it. Add one label and it writes a spec, or builds the change on a branch with tests, reviews its own pull request, and answers the review until it passes. You decide by merging: the spec PR, then the code PR. Everything the factory knows about an item is on the issue and its PRs; nothing lands in your repo but a handful of skills and one workflow file.

```mermaid
flowchart LR
  O([issue opened]) --> T[triage] --> H1{{you: add a ready label}}
  H1 -->|ready-to-spec| S[spec PR] --> H2{{you: merge the spec}} --> I
  H1 -->|ready-to-implement| I[implement PR] --> R[review]
  R -->|changes requested| I
  R -->|approved| H3{{you: merge}} --> D([issue closed])
```

Hexagons are yours. Everything else is a station: one headless `claude -p` run that reads a packet of context the workflow prepared, does its work, and reports a verdict the workflow turns into labels, a comment, and, for review, a PR review.

## Install

```bash
git clone https://github.com/ztcnrh/software-factory && cd software-factory
./install.sh /path/to/your/repo
```

That copies the skills into `.claude/skills/`, the caller workflow into `.github/workflows/factory.yml`, and creates the labels. Then, once: commit those files, add the `CLAUDE_CODE_OAUTH_TOKEN` secret (`claude setup-token`; it runs on your Claude subscription) or `ANTHROPIC_API_KEY`, and allow GitHub Actions to create and approve pull requests in the repository's Actions settings. Open an issue.

## What you see

Every station leaves one short comment on the issue: what happened, why, what to do next, details folded. Labels say where an item stands; yellow ones wait on you.

| Label | Means |
|---|---|
| `factory:triaged` | triage ran; its recommendation is the first line of its comment |
| `factory:needs-info` | triage needs the reporter; answer, then remove the label to triage again |
| `factory:ready-to-spec` | you asked for a spec |
| `factory:spec-review` | the spec PR is open; merge it to start implementation, or request changes |
| `factory:ready-to-implement` | you asked for the build, or the spec PR merged |
| `factory:in-review` | the factory is building and reviewing |
| `factory:ship-review` | review approved; merge the PR to ship, or request changes |
| `factory:needs-human` | three review rounds without you, or a station is stuck; look at the PR |

A merged code PR closes the issue (`Resolves #n`). Closing an issue as not planned parks it. A Request-changes review from you on either PR sends it back to the station that owns it, with your review in its packet; a comment in the PR conversation is read too.

## Metrics

`factory metrics` prints cost per shipped item, cycle time, autonomy (shipped with no human steer), and steers per item, all derived from the issues and PRs. It runs anywhere `gh` is logged in for the repo:

```bash
uv tool install /path/to/software-factory && factory metrics --since 30d
```

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) has the labels and events in full, the four jobs, the packets, and the trust boundaries.

*Built on the skills and patterns in Warp's [cloud-factory-demo](https://github.com/warpdotdev/cloud-factory-demo).*
