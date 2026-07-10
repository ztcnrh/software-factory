# Software Factory

A personal, self-improving **software factory** — an agentic delivery line that triages, specs, implements, reviews, verifies, and ships software changes, and **learns from every human steer** so it needs you less over time.

It's the working prototype of the "factory engineering" idea: you stop hand-building each feature and instead operate (and continuously improve) a machine that builds features for you. The job shifts from writing code to raising one number — the **one-shot ship rate**, *the share of changes that ship with no human rework (no send-back, correction, or unblock), at an acceptable cost*. You stay in the loop and own the ship decision; the aim isn't to remove your review but to make the line good enough that review becomes a rubber-stamp — and to drive that share up over time.

This repo is the **factory** (the reusable machinery). It operates *on* your project repos. A worked example lives next door in `[../software-factory-demo](../software-factory-demo)`.

## The loop

```
new task → Triage → ┬─ needs spec → Spec → [✋ you review] → Implement
                    ├─ automatable ───────────────────────→ Implement
                    ├─ needs clarification → [✋ you] → Triage
                    └─ park
Implement → Code review → Verify → [✋ you: ready to ship?] → Deploy → Done
                                     (approve = merge PR → post-merge CI/CD; green = shipped)
```

Five **stations** (Triage, Spec, Implement, Code-review, Verify) do the work; a sixth — **Retro** — watches where you stepped in and rewrites the factory so you don't have to next time. Three **human gates** are where you steer. Approving the ship gate merges the PR, which triggers your project's post-merge CI/CD; the external **Deploy** step watches it, and a green deploy (health-wait baked in) is the ship signal. Continuous **monitoring** and auto-spawning follow-up work is deferred — new post-ship work enters as fresh items (see [docs/OPTIMIZATION-AREAS.md](docs/OPTIMIZATION-AREAS.md)).

## How it maps to Claude Code


| Piece                | Built as                                                                                                                                   |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Each station         | a portable **skill** (`.claude/skills/factory-*`) + a **subagent** (`.claude/agents/`) — repo- and language-agnostic                       |
| The conveyor + state | a tested Python **dispatcher** (`src/factory`, the `factory` CLI) over local JSON in `.factory/`; optional GitHub-issue mirror             |
| The triggers         | the `**/factory`** command drives the loop locally; opt-in **GitHub Actions** (`workflows/`) run it unattended                             |
| The human gates      | the driver stops, shows a **review packet**, and records your decision **and your reasoning**                                              |
| The learning loop    | every steer writes an **intervention record**; the **Retro** station turns those into PRs against the factory's own skills + gate policies |
| The goal             | a **metrics ledger** tracking the North Star: the one-shot ship rate (% shipped with no human rework), and at what cost                       |


## Quickstart

```bash
# 1. Put the CLI on your PATH
uv tool install /path/to/software-factory

# 2. Adopt the factory into any repo
python3 install/install.py /path/to/your/repo
cd /path/to/your/repo && factory init

# 3. Drop in work and drive it (inside Claude Code, in that repo)
factory new "the feature I want"
/factory                      # moves it down the line until it needs you
/factory-status               # the board + metrics + what's waiting on you
/factory retro                # let the factory propose its own improvements
```

Prefer to let your agent do it? Open a Claude Code session in this repo and say *"install the factory into \<path\>"* — the `install-factory` skill plans the operations (`--dry-run`), confirms with you, then installs and walks you through the first run.

You don't need any cloud accounts to start — it's fully local. Wire up [cloud autonomy](docs/CLOUD-AUTONOMY.md) when you want it to run while you sleep.

## Where to go next

- **[FACTORY-MANUAL.md](FACTORY-MANUAL.md)** — start here. What *you* do: setup, driving the line day to day, the gate playbook, and the homework checklist (accounts/secrets).
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — how it all fits: the stations, the dispatcher/state machine, the conveyor, the triggers.
- **[docs/CODE-TOUR.md](docs/CODE-TOUR.md)** — want to peek under the hood? The code-reading path: which files first, and the handful of functions that make everything else click.
- **[docs/LEARNING-LOOP.md](docs/LEARNING-LOOP.md)** — the crown jewel: interventions → retro → self-improvement, with the demo as a worked example.
- **[docs/CLOUD-AUTONOMY.md](docs/CLOUD-AUTONOMY.md)** — enabling the unattended GitHub Actions layer (opt-in).
- **[docs/EXTENDING.md](docs/EXTENDING.md)** — adding stations, language/tracker adapters, and a candid take on what's still hard.
- **[docs/OPTIMIZATION-AREAS.md](docs/OPTIMIZATION-AREAS.md)** — a living log of deliberate v1 tradeoffs and the ideas for improving them later.
- **[docs/diagram.md](docs/diagram.md)** — the loop as Mermaid source.

## Status

v1, built and proven end-to-end on the demo repo (a full feature shipped through the whole line, one human intervention captured, and the Retro station then auto-cleared that class of work — note the demo predates the tail reshape to a single `deploy` station). The engine has unit tests (`uv run pytest`); the cloud layer is the least-exercised part and ships disabled. It is meant to be used, stress-tested on real projects, and improved — by you, and increasingly by itself.

*Inspired by Zach Lloyd's "factory engineering" thesis and the patterns in [warpdotdev/common-skills](https://github.com/warpdotdev/common-skills) (council, cross-critique, spec-driven development).*