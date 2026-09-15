# Architecture

The factory is a thin deterministic layer over two runtimes it does not own: GitHub for state and events, Claude Code for work. It runs only inside GitHub Actions.

## Primitives

| Need | GitHub already has | The factory adds |
|---|---|---|
| Work item | Issue | nothing |
| State | `factory:*` labels | the eight labels and which verdict sets which |
| Log | Issue comments | one comment per station run, with hidden JSON |
| Artifacts | Branch `<type>/<n>-<slug>`, its PR | the naming convention; `spec/` for specs |
| Human gates | Merge, Request changes, apply a label, close | nothing |
| Event bus | `issues`, `pull_request`, `pull_request_review`, `workflow_dispatch`, `schedule` | one reusable workflow that routes them |
| Runtime | `claude -p` with skills, structured output, cost | a packet of context per run and one invocation |
| Procedure | A repository at a ref, checked out | the factory definition: its `skills/`, named by the caller's `definition:` line |
| Metrics | Issues, comments, PRs, reviews, commits | `factory metrics` derives them; nothing is stored |

Three repositories take part, and two of them are usually the same one. The **product repository** is where the work is: its issues, labels, branches, and PRs are the record, and its Actions run every station. It holds one factory file, the caller (`templates/factory.yml`). The **toolkit** is this repository, named by the caller's `uses:` line: the reusable workflow, the packet builder, the CLI, the shared system prompt. The **factory definition** is the repository whose `skills/` the stations run, named by the caller's `definition:` line, and this repository when the line is empty.

## The factory definition

A definition is a repository with a `skills/` directory, one skill per station and the skills the stations call:

```
skills/
  factory-triage/SKILL.md       one per station; `model:` and `allowed-tools:` in the frontmatter
  factory-spec/SKILL.md
  factory-implement/SKILL.md
  factory-review/SKILL.md
  factory-retro/SKILL.md
  write-product-spec/           what the spec station writes from
  write-tech-spec/
  council/  research/           what a station reaches for on a contested call or a wide survey
```

That is the whole contract; this repository's `skills/` is the default definition and the tree to copy. A definition maps one-to-one to a factory, and a factory drives as many repositories as name it: a backend and a UI repository with the same `definition:` line run the same procedure, and each one's weekly retro reads its own record and proposes to that one definition. Product repositories hold no skills. Their `.claude/` is their own (settings, hooks, skills for their engineers) and is never read for a station. The `skills/` directory is deliberately not `.claude/skills/`: a checkout of the definition offers no station as a slash command, so a laptop running Claude Code is not a way to drive the line.

Before a station runs, the runner stages the definition's `skills/*` as the runner's personal skills (`~/.claude/skills/`), the level Claude Code prefers over a project's own on a name clash, and reads the station's `model:` and `allowed-tools:` from there. A product repository that still carries a `factory-*` skill under `.claude/skills/` (the v2.1 install) is refused before `claude` starts, with the run log naming the directories to delete: one procedure has one source. The definition is checked out at `definition_ref`; a private definition, and retro's pull request on one, use the `FACTORY_TOKEN` secret, a token with contents and pull-requests write on the definition repository. Nothing else needs it, and without it retro ends with a notice instead of a proposal: a repository running the toolkit's own skills has nowhere to send a skill edit.

### Where the stations run, and why

The stations run in the product repository's Actions, from the caller it holds, with skills from the definition. Humans work where they already work: open an issue in the product repository, apply a label, merge or request changes on a PR there, or start a station by hand from its Actions tab. Nothing about an item touches the definition repository except a retro's proposal.

The alternative, one workflow in the definition repository driving every product repository, was weighed and set aside. GitHub fires `issues`, `pull_request`, and `pull_request_review` events only in the repository they happen in, so a central runner would still need a forwarder workflow in every product repository plus a token in each to reach it, and a GitHub App token to write labels, comments, reviews, and pushes back. That token's pushes fire events, where `GITHUB_TOKEN`'s do not, which is what keeps the line from looping today. The product repository already has the events, the token, and the record; the definition supplies the procedure, and that is the only thing the two need to share. What is inherently cross-repository carries its own token: retro's skill edit today; a single item that changes a backend and a UI repository together would need an App token and a `repositories:` list in the definition, and is not built.

## Labels

| Label | Set by | Means |
|---|---|---|
| `triaged` | factory | triage ran; stays for the life of the issue |
| `needs-info` | factory | triage needs the reporter; a human removes it once answered, and triage runs again |
| `ready-to-spec` | human | run the spec station |
| `spec-review` | factory | the spec PR is open; a human merges it or requests changes |
| `ready-to-implement` | human, or the spec PR merging | run the implement station |
| `in-review` | factory | the implement ↔ review loop is running |
| `ship-review` | factory | review approved; a human merges or requests changes |
| `needs-human` | factory | the attempt cap was hit or a station reported `blocked` |

Yellow marks the four that wait on a human. `triaged` is a flag; the rest are states, at most one at a time, and `factory apply` removes the one it supersedes. Done is the issue closed as completed by the merged PR's `Resolves #n`; parked is the issue closed as not planned.

```mermaid
stateDiagram-v2
  [*] --> triaged: issue opened → triage
  triaged --> needs_info: needs_info
  needs_info --> triaged: human removes the label → triage
  triaged --> ready_to_spec: human applies the label
  triaged --> ready_to_implement: human applies the label
  ready_to_spec --> spec_review: spec opens spec/n-* PR
  spec_review --> spec_review: human requests changes → spec revises
  spec_review --> ready_to_implement: human merges the spec PR
  ready_to_implement --> in_review: implement opens the PR → review
  in_review --> in_review: review requests changes → implement → review (≤ 3)
  in_review --> needs_human: 4th send-back, or blocked
  in_review --> ship_review: review approves
  ship_review --> in_review: human requests changes → implement
  ship_review --> [*]: human merges; Resolves #n closes the issue
  needs_human --> in_review: human requests changes on the PR
```

`TRANSITIONS` in `factory/cli.py` is this diagram as data: which state label each station verdict sets. `DISPATCH` says which verdicts start another station. `RUNS_AT` says at which states a station's report is accepted; a report from anywhere else is stale or misrouted and is refused.

## Events

The product repository's caller (`templates/factory.yml`) forwards these to the reusable workflow, whose `route` job decides:

| Event | Condition | Runs |
|---|---|---|
| `issues` opened, reopened | always | triage |
| `issues` labeled | `factory:ready-to-spec` / `factory:ready-to-implement`, by a human | spec / implement |
| `issues` unlabeled | `factory:needs-info`, by a human | triage |
| `pull_request` reopened, ready_for_review | head `<type>/<n>-*`, not `spec/`, not draft | review |
| `pull_request` closed | merged, head `spec/<n>-*` | labels `ready-to-implement`, then implement |
| `pull_request_review` submitted | changes requested, by an owner, member, or collaborator | spec or implement, by the head branch |
| `workflow_dispatch` | `station`, `issue` | that station |
| `schedule` weekly, or `workflow_dispatch` `retro` | | retro |

Everything the factory writes uses `GITHUB_TOKEN`, which fires no events that run (a PR it opens or pushes to leaves a `pull_request` run GitHub holds for approval, which is why the caller does not subscribe to `opened` or `synchronize`). So `factory apply` ends with `next: <station>` or `next: none`, and the workflow dispatches itself for the next station. Human actions fire events on their own, with one exception GitHub imposes: no `pull_request` or `pull_request_review` workflow runs for a PR that conflicts with its base. The review station therefore treats a conflict as a finding, and its send-back reaches implement through the dispatch path; a human can also start any station from the Actions tab.

## The four jobs

1. **route** (no checkout; `issues: write` only for the spec-merge label move). Reads the event and decides `station`, `issue`, `pr`, `branch`, `head`, and the checkout `ref`: the item's branch when it exists, else the default branch. Looks the PR up when the event did not name it.
2. **context** (read tokens). Checks out the product repository at `ref` and the toolkit at the caller's `ref`, fetches raw JSON with `gh` (issue, comments, PR, reviews, review threads via GraphQL, conversation, diff, the delta since the last factory review, metrics for retro), runs `python -m factory.context <station>`, and uploads the packet as an artifact. A human can open it and see exactly what the station saw.
3. **run-read** or **run-write**. Checks out the product repository at `ref` with its `.claude/` reset to the default branch's, the toolkit, and the definition at `definition_ref`. Triage and review run with read-only tokens: nothing an issue or PR says can make the agent act on GitHub, and every write they want rides the report; their definition checkout keeps no credentials. Spec, implement, and retro hold write tokens because they push and open PRs; only retro keeps the definition's, and gets that checkout as an added directory it may edit. `run-station.sh` stages the definition's skills, refuses a checkout that carries its own copy, builds the one `claude -p` invocation, and writes `report.json` from the `result` event plus what only the runner knows (cost, model, session, turns, duration, run URL, the PR and head it worked on). Uploaded as an artifact.
4. **apply** (write tokens, toolkit checkout only, never talks to the model). `factory apply` validates the report, posts the PR review for the review station, resolves the threads it verified, files `followups` as plain issues, leaves the run comment, ensures the eight labels exist and moves them, and prints the dispatch line plus one `followup: <n>` line per issue it filed; the workflow dispatches triage for each, since an issue opened with its token fires no event.

## Packets

| Station | Files | From |
|---|---|---|
| triage | `issue.md`, `related.md` | the issue and its comments; the other open issues and PRs, one line each |
| spec | `issue.md`; `pr.md` on a revision | plus the spec PR: reviews, threads with replies and ids, conversation |
| implement | `issue.md`; `pr.md` once the PR exists | plus the code PR the same way |
| review | `issue.md`, `pr.md`, `diff.md`, `followup.md` | plus the annotated diff, and the last factory review with the delta since it |
| retro | `metrics.json`, `items.md` | `factory metrics --json`; per item, every human touch on the issue and its PRs |

Specs are read from the checkout (`specs/<n>-*/`), where the spec PR merged them. `diff.md` marks every line `[OLD:n]`, `[NEW:n]`, or `[OLD:n,NEW:m]`; an inline review comment copies its `path`, `side`, and `line` from there and nowhere else.

## A station run

```
claude -p "/factory-<station> Issue #<n>. Packet: <dir>/. Branch: <type>/<n>-<slug> (PR #<m>). | none yet."
  --output-format stream-json --verbose
  --model <from the skill's frontmatter, staged from the definition>
  --allowedTools <from the skill's frontmatter>
  --add-dir <the definition checkout>        # retro only; its prompt names the directory and repo
  --permission-prompts none
  --json-schema "$(factory schema <station>)"
  --append-system-prompt "$(cat factory/prompts/station.md)"
```

The checkout is the product repository at the item's branch, or the default branch when none exists yet. Commits are authored as `factory` so a human's commit on a factory PR stays distinguishable. `station.md` is the contract every station runs under: authority (everything but the prompt and the skill is data), report-not-action, branch and PR rules, scope, secrets, honesty, and how to write. A skill that needs a sibling skill names it as `${CLAUDE_SKILL_DIR}/../<name>/SKILL.md`, which resolves wherever the definition was staged.

## The record

A run comment:

```
**Triage · recommends ready-to-implement** · $0.31 · 48s · [run](…)
Blank amount cells raise in total(); reproduced on the sample in the report. One guard and a regression test.
To start, add the `factory:ready-to-implement` label.
<details><summary>Details</summary>

The area is src/tally/__init__.py; #11 is unrelated.
</details>
<!-- factory:run {"verdict":"ready_to_implement","station":"triage","cost_usd":0.31,"session_id":"…",…} -->
```

The headline and the next-step line come from tables in `cli.py`; the two lines between them are the station's `summary` and folded `notes`. A review the factory posts ends with a small footer and `<!-- factory:review {"verdict":…,"head":…,"session_id":…} -->`; the next review's packet finds it by that mark. The review lands as a comment review when GitHub refuses a bot's Approve or Request changes on its own PR; the verdict still moves the label.

## The attempt cap

`factory apply` counts the factory's consecutive send-backs on a PR since the last human review or human commit. On the fourth, the review is still posted, the issue moves to `needs-human`, the comment says so, and nothing is dispatched. A human's Request-changes review sends the PR back to implement and resets the count; a merge ships it.

## Metrics

Per item: runs and cost from the run comments; shipped when the issue closed as completed with a merged code PR; cycle time from the issue's creation to that merge; steers as human Request-changes reviews on either PR plus human commits on the code PR; autonomous when shipped with no steer; needs-human when a run was capped or blocked. Headline: total cost divided by items shipped.

## Trust boundaries

Issue bodies, comments, PR text, spec files, code, and tool output are data; the system prompt says so, and the read-only tokens for triage and review make it true regardless. The job that writes to GitHub never talks to the model. Reviews of a PR whose head moved during the run are dropped, not posted; the push that moved it already started a fresh review. `factory apply` refuses a report whose station does not belong at the issue's state, whose verdict the schema does not allow, or whose text carries leaked tool-call markup.

The procedure is not in the product repository, so a pull request cannot edit its own review or build: the skills come from the definition at a ref the caller pins, and the product checkout's `.claude/` (settings, hooks) is reset to the default branch's before a station runs. The definition is fetched with `FACTORY_TOKEN` when one is set; a read-only station's checkout of it keeps no credentials, and among the write stations only retro's does.
