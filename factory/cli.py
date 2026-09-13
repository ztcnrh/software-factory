"""factory — the deterministic layer of a GitHub-native software factory.

GitHub holds every piece of state: an issue is a work item, its `factory:*` label is its state,
its comments are its log, and its `feature/<n>-*` branch and pull request are its artifacts.
This module does only what GitHub has no primitive for: the transition table, one `claude -p`
invocation per station run, applying a station's report, the human gates, and metrics derived
from the record. All GitHub access goes through `gh` via `_gh`, so tests stub one function.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

PREFIX = "factory:"
STATES = (
    "triage", "spec", "spec-review", "implement", "review", "ship-review",
    "done", "needs-info", "parked", "retro",
)
STATIONS = ("triage", "spec", "implement", "review")
GATES = ("spec-review", "ship-review")

# (state, station verdict) -> next state. The only routing that exists.
TRANSITIONS = {
    ("triage", "automatable"): "implement",
    ("triage", "needs_spec"): "spec",
    ("triage", "needs_info"): "needs-info",
    ("triage", "park"): "parked",
    ("spec", "ready_for_review"): "spec-review",
    ("spec", "needs_info"): "needs-info",
    ("implement", "implemented"): "review",
    ("implement", "blocked"): "needs-info",
    ("review", "approve"): "ship-review",
    ("review", "request_changes"): "implement",
}
# (state, human decision) -> next state. `done`, `park`, and `retriage` are accepted from any
# active state: a merge or a shelving is a fact, and re-triage with a comment is how a human
# overrides a station's routing without labeling by hand.
GATE_MOVES = {
    ("spec-review", "approve"): "implement",
    ("spec-review", "request_changes"): "spec",
    ("ship-review", "request_changes"): "implement",
}
DECISIONS = ("approve", "request_changes", "park", "done", "retriage")

LABEL_COLORS = {
    "triage": "FBCA04", "spec": "1D76DB", "spec-review": "5319E7", "implement": "0E8A16",
    "review": "006B75", "ship-review": "5319E7", "done": "BFDADC", "needs-info": "D93F0B",
    "parked": "CCCCCC", "retro": "C5DEF5",
}
BUDGET_USD = {"triage": 2.0, "spec": 6.0, "implement": 12.0, "review": 6.0, "retro": 6.0}
BOT_NAME, BOT_EMAIL = "factory", "factory@users.noreply.github.com"
RUN_MARK, GATE_MARK = "<!-- factory:run ", "<!-- factory:gate "
REVIEW_MARK = "<!-- factory:review -->"


def fail(msg: str) -> None:
    raise SystemExit(f"factory: {msg}")


# ----------------------------------------------------------------------------- GitHub access


def _gh(*args: str, input: str | None = None) -> str:
    proc = subprocess.run(["gh", *args], input=input, capture_output=True, text=True)
    if proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, proc.args, proc.stdout, proc.stderr)
    return proc.stdout


def _gh_json(*args: str):
    return json.loads(_gh(*args) or "null")


@functools.cache
def _repo() -> str:
    return os.environ.get("GITHUB_REPOSITORY") or _gh(
        "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"
    ).strip()


@functools.cache
def _default_branch() -> str:
    return _gh("repo", "view", "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name").strip()


def _issue(n: int) -> dict:
    return _gh_json("issue", "view", str(n), "--json", "number,title,labels,state")


def _states(issue: dict) -> list[str]:
    names = [lb["name"] for lb in issue.get("labels", [])]
    return [s[len(PREFIX):] for s in names if s.startswith(PREFIX)]


def _set_state(n: int, state: str, current: list[str]) -> None:
    args = ["issue", "edit", str(n), "--add-label", PREFIX + state]
    for old in current:
        if old != state:
            args += ["--remove-label", PREFIX + old]
    _gh(*args)


def _item_branch(n: int) -> str | None:
    out = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", f"feature/{n}-*"], capture_output=True, text=True
    ).stdout
    refs = sorted(line.split("refs/heads/")[-1] for line in out.splitlines() if line.strip())
    return refs[0] if refs else None


def _item_pr(n: int, branch: str | None = None) -> dict | None:
    branch = branch or _item_branch(n)
    if not branch:
        return None
    prs = _gh_json(
        "pr", "list", "--head", branch, "--state", "all", "--limit", "10",
        "--json", "number,url,state,isDraft,mergedAt,headRefOid,createdAt",
    )
    prs.sort(key=lambda p: (p["state"] != "OPEN", -_parse_ts(p["createdAt"]).timestamp()))
    return prs[0] if prs else None


def _paginated(endpoint: str) -> list:
    return [x for page in _gh_json("api", "--paginate", "--slurp", endpoint) for x in page]


def _comments(n: int) -> list[dict]:
    return _paginated(f"repos/{_repo()}/issues/{n}/comments")


# ----------------------------------------------------------------------------- report contract


def schema(station: str) -> dict:
    if station == "retro":
        verdicts = ["proposed", "nothing_to_learn"]
    else:
        verdicts = sorted(v for (s, v) in TRANSITIONS if s == station)
    if not verdicts:
        fail(f"unknown station {station!r}")
    props: dict = {
        "verdict": {"type": "string", "enum": verdicts},
        "summary": {
            "type": "string",
            "description": "At most two short sentences, under 60 words, read on the issue by a "
            "human: the verdict and its why. Details belong in notes or the PR. For needs_info "
            "or blocked, the concrete questions whose answers unblock it.",
        },
        "notes": {
            "type": "string",
            "description": "What the next station or the human must know that the summary and the "
            "artifacts do not carry. Omit when there is nothing.",
        },
    }
    required = ["verdict", "summary"]
    if station == "review":
        props["body"] = {
            "type": "string",
            "description": "The GitHub review body: findings by severity, then "
            "'Found: X critical, Y important, Z suggestions' and the disposition.",
        }
        props["comments"] = {
            "type": "array",
            "description": "Inline findings. path/line/side must come from the annotated diff.",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "side": {"type": "string", "enum": ["LEFT", "RIGHT"]},
                    "start_line": {"type": "integer"},
                    "body": {"type": "string"},
                },
                "required": ["path", "line", "side", "body"],
                "additionalProperties": False,
            },
        }
        props["resolve"] = {
            "type": "array",
            "description": "Thread ids from `factory threads` whose fix you verified; the runner "
            "resolves them.",
            "items": {"type": "string"},
        }
        required += ["body", "comments"]
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}


# A structured-output call that went wrong leaks the tool-call envelope into a string field.
MALFORMED = re.compile(r"<parameter name=|</(summary|notes|body|verdict)>")
RUNNER_KEYS = {"station", "model", "cost_usd", "session_id", "turns", "duration_ms", "run_url",
               "ts", "head"}


def validate(report: dict, station: str) -> None:
    """Refuse a report the station schema would not have produced. Keeps apply data-in."""
    sch = schema(station)
    allowed = set(sch["properties"]) | RUNNER_KEYS
    if unknown := set(report) - allowed:
        fail(f"report has unknown keys {sorted(unknown)}")
    if missing := [k for k in sch["required"] if k not in report]:
        fail(f"report is missing {missing}")
    if report["verdict"] not in sch["properties"]["verdict"]["enum"]:
        fail(f"verdict {report['verdict']!r} is not one of {sch['properties']['verdict']['enum']}")
    for key in ("summary", "notes", "body"):
        if MALFORMED.search(report.get(key) or ""):
            fail(f"{key} carries tool-call markup; the structured output was malformed, rerun")
    for i, c in enumerate(report.get("comments", [])):
        item = sch["properties"]["comments"]["items"]
        if set(c) - set(item["properties"]) or [k for k in item["required"] if k not in c]:
            fail(f"comments[{i}] does not match the review schema")


# ----------------------------------------------------------------------------- run comment


def run_comment(report: dict) -> str:
    ms = report.get("duration_ms") or 0
    took = f"{ms / 60000:.0f}m" if ms >= 60000 else f"{ms / 1000:.0f}s"
    head = (
        f"**factory · {report['station']} → {report['verdict']}** · {report.get('model', '?')}"
        f" · ${report.get('cost_usd', 0):.2f} · {took}"
    )
    if report.get("run_url"):
        head += f" · [run]({report['run_url']})"
    body = [head, report["summary"]]
    if report.get("notes"):
        body += ["", report["notes"]]
    record = {k: report.get(k) for k in ("verdict", *RUNNER_KEYS)}
    body += [f"{RUN_MARK}{json.dumps(record, separators=(',', ':'))} -->"]
    return "\n".join(body)


def parse_marks(text: str, mark: str) -> list[dict]:
    pattern = re.escape(mark) + r"(\{.*?\}) -->"
    return [json.loads(m) for m in re.findall(pattern, text, flags=re.S)]


# ----------------------------------------------------------------------------- station runs


def skill_meta(station: str, root: Path = Path(".")) -> dict:
    """model and allowed-tools from the station skill's frontmatter."""
    text = (root / ".claude" / "skills" / f"factory-{station}" / "SKILL.md").read_text()
    front = text.split("---", 2)[1] if text.startswith("---") else ""
    meta = {}
    for line in front.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    if "model" not in meta:
        fail(f"factory-{station}/SKILL.md has no model: in its frontmatter")
    return {"model": meta["model"], "tools": meta.get("allowed-tools", "").split()}


def build_prompt(station: str, repo: str, n: int | None, branch: str | None,
                 pr: dict | None) -> str:
    if station == "retro":
        return f"/factory-retro Repository {repo}."
    where = "Branch: none yet." if not branch else f"Branch: {branch}"
    if branch and pr:
        where += f" (PR #{pr['number']}{', draft' if pr.get('isDraft') else ''})"
    elif branch:
        where += " (no PR)"
    return f"/factory-{station} Issue #{n} in {repo}. {where}"


def build_argv(station: str, prompt: str, meta: dict, budget: float, system: str) -> list[str]:
    return [
        "claude", "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--model", meta["model"],
        *(["--allowedTools", *meta["tools"]] if meta["tools"] else []),
        "--permission-prompts", "none",
        "--max-budget-usd", f"{budget:g}",
        "--json-schema", json.dumps(schema(station), separators=(",", ":")),
        "--append-system-prompt", system,
    ]


@contextmanager
def worktree(n: int | str, branch: str | None) -> Iterator[Path]:
    """A throwaway checkout per run: the item branch when it exists, else the default branch tip.

    Keeps a station's checkouts and edits out of the caller's working tree, and makes local and
    Actions runs start from the same place.
    """
    git = lambda *a: subprocess.run(["git", *a], check=True, capture_output=True, text=True)  # noqa: E731
    common = Path(git("rev-parse", "--git-common-dir").stdout.strip()).resolve()
    path = common / "factory-worktrees" / str(n)
    git("fetch", "--quiet", "--prune", "origin")
    if path.exists():
        git("worktree", "remove", "--force", str(path))
    if branch:
        git("worktree", "add", "--quiet", "-B", branch, str(path), f"origin/{branch}")
    else:
        git("worktree", "add", "--quiet", "--detach", str(path), f"origin/{_default_branch()}")
    try:
        yield path
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(path)], capture_output=True)


def _progress(event: dict) -> str | None:
    if event.get("type") != "assistant":
        return None
    out = []
    for block in event.get("message", {}).get("content", []):
        if block.get("type") == "tool_use":
            arg = block.get("input", {})
            hint = arg.get("command") or arg.get("file_path") or arg.get("pattern") or arg.get(
                "description") or ""
            out.append(f"  ▸ {block['name']} {str(hint)[:110]}")
        elif block.get("type") == "text" and block["text"].strip():
            out.append(f"  · {block['text'].strip()[:200]}")
    return "\n".join(out) or None


def cmd_run(target: str, out: str | None, budget: float | None) -> None:
    repo = _repo()
    if target == "retro":
        station, n, branch, pr = "retro", None, None, None
    else:
        n = int(target)
        states = _states(_issue(n))
        active = [s for s in states if s in STATIONS]
        if len(active) != 1:
            fail(f"#{n} is at {states or ['no factory label']}; nothing for a station to run")
        station = active[0]
        branch = _item_branch(n)
        pr = _item_pr(n, branch)
    meta = skill_meta(station)
    system = (Path(__file__).parent / "prompts" / "station.md").read_text()
    prompt = build_prompt(station, repo, n, branch, pr)
    argv = build_argv(station, prompt, meta, budget or BUDGET_USD[station], system)
    env = os.environ | {
        "GIT_AUTHOR_NAME": BOT_NAME, "GIT_AUTHOR_EMAIL": BOT_EMAIL,
        "GIT_COMMITTER_NAME": BOT_NAME, "GIT_COMMITTER_EMAIL": BOT_EMAIL,
    }
    print(f"factory: {prompt}  [{meta['model']}, ≤${budget or BUDGET_USD[station]:g}]",
          file=sys.stderr)
    if os.environ.get("ANTHROPIC_API_KEY") is not None:
        print("factory: ANTHROPIC_API_KEY is set, so this run bills that key rather than a Claude "
              "subscription (it outranks CLAUDE_CODE_OAUTH_TOKEN and /login even when empty)",
              file=sys.stderr)
    result = None
    with worktree(n or "retro", branch) as cwd:
        with subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, text=True) as proc:
            for line in proc.stdout:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "result":
                    result = event
                elif msg := _progress(event):
                    print(msg, file=sys.stderr)
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    if not result:
        fail("claude produced no result event")
    structured = result.get("structured_output")
    if not isinstance(structured, dict):
        sys.stderr.write(json.dumps(result, indent=2) + "\n")
        fail(f"no station report came back ({result.get('subtype')})")
    usage = result.get("modelUsage") or {}
    model = max(usage, key=lambda m: usage[m].get("costUSD", 0)) if usage else meta["model"]
    report = structured | {
        "station": station,
        "model": model,
        "cost_usd": round(result.get("total_cost_usd") or 0, 4),
        "session_id": result.get("session_id"),
        "turns": result.get("num_turns"),
        "duration_ms": result.get("duration_ms"),
        "run_url": _run_url(),
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": pr["headRefOid"] if pr else None,
    }
    text = json.dumps(report, indent=2)
    if out:
        Path(out).write_text(text + "\n")
    else:
        print(text)
    print(
        f"factory: {station} → {report['verdict']} · ${report['cost_usd']:.2f} · "
        f"{report['turns']} turns · transcript "
        f"~/.claude/projects/{slug}/{report['session_id']}.jsonl",
        file=sys.stderr,
    )


def _run_url() -> str | None:
    if run_id := os.environ.get("GITHUB_RUN_ID"):
        return f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/" \
               f"{os.environ['GITHUB_REPOSITORY']}/actions/runs/{run_id}"
    return None


# ----------------------------------------------------------------------------- apply and gate


def cmd_apply(n: int, report_path: str) -> None:
    report = json.loads(Path(report_path).read_text())
    station, verdict = report.get("station"), report.get("verdict")
    if station not in STATIONS:
        fail(f"report station {station!r} is not one of {STATIONS}")
    validate(report, station)
    states = _states(_issue(n))
    if station not in states:
        fail(f"#{n} is at {states}, not {station}; refusing to apply a {station} report")
    target = TRANSITIONS.get((station, verdict))
    if not target:
        fail(f"{station} cannot report {verdict!r}")
    pr = _item_pr(n)
    if verdict in ("ready_for_review", "implemented") and not (pr and pr["state"] == "OPEN"):
        fail(f"{verdict} reported but #{n} has no open PR from a feature/{n}-* branch")
    if station == "review" and not pr:
        fail(f"review reported but #{n} has no PR")
    already = any(
        r.get("session_id") == report.get("session_id")
        for c in _comments(n) for r in parse_marks(c["body"], RUN_MARK)
    )
    if already:
        print(f"factory: run {report.get('session_id')} already recorded on #{n}", file=sys.stderr)
    else:
        if station == "review":
            _post_review(pr, report)
            for thread in report.get("resolve") or []:
                _gh("api", "graphql", "-f", "query=mutation($id:ID!){resolveReviewThread("
                    "input:{threadId:$id}){thread{isResolved}}}", "-f", f"id={thread}")
        _gh("issue", "comment", str(n), "--body", run_comment(report))
    _set_state(n, target, states)
    link = f" · {pr['url']}" if pr else ""
    print(f"#{n}: {station} → {verdict} → {PREFIX}{target}{link}")


def _post_review(pr: dict, report: dict) -> None:
    """Post the station's review; degrade the anchor or the event before ever dropping a finding."""
    event = "APPROVE" if report["verdict"] == "approve" else "REQUEST_CHANGES"
    head = report.get("head") or pr["headRefOid"]
    text = report["body"].strip().removesuffix(REVIEW_MARK).strip()
    text = re.sub(r"\A[Rr]eviewed at [0-9a-f]{7,40}\s*", "", text)
    body = f"Reviewed at {head[:12]}\n\n{text}\n\n{REVIEW_MARK}"
    comments = [
        {**c, "body": f"{c['body'].strip().removesuffix(REVIEW_MARK).strip()}\n\n{REVIEW_MARK}"}
        for c in report["comments"]
    ]
    payload = {"event": event, "body": body, "comments": comments, "commit_id": head}
    endpoint = f"repos/{_repo()}/pulls/{pr['number']}/reviews"
    for _ in range(3):
        try:
            _gh("api", "--method", "POST", endpoint, "--input", "-", input=json.dumps(payload))
            return
        except subprocess.CalledProcessError as e:
            err = (e.stdout + e.stderr).lower()
            if payload["comments"] and ("line" in err or "path" in err or "position" in err):
                folded = "\n".join(
                    f"- `{c['path']}:{c['line']}` — {c['body'].replace(REVIEW_MARK, '').strip()}"
                    for c in payload["comments"]
                )
                payload["body"] = body.replace(REVIEW_MARK, f"Findings:\n{folded}\n\n{REVIEW_MARK}")
                payload["comments"] = []
            elif payload["event"] != "COMMENT" and ("approve" in err or "own pull" in err
                                                   or "not permitted" in err):
                payload["event"] = "COMMENT"
            else:
                sys.stderr.write(e.stdout + e.stderr)
                fail("posting the PR review failed")
    fail("posting the PR review failed after fallbacks")


def cmd_gate(n: int, decision: str, why: str | None) -> None:
    states = _states(_issue(n))
    if len(states) != 1:
        fail(f"#{n} carries {states or 'no factory label'}; fix the labels first")
    state = states[0]
    if decision == "done" and state != "done":
        target = "done"
    elif decision == "park" and state not in ("done", "parked"):
        target = "parked"
    elif decision == "retriage" and state not in ("done", "triage"):
        target = "triage"
    else:
        target = GATE_MOVES.get((state, decision))
    if not target:
        hint = " (merge the PR instead)" if (state, decision) == ("ship-review", "approve") else ""
        fail(f"{decision!r} is not a decision at {state}{hint}")
    record = {"decision": decision, "from": state, "to": target,
              "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    body = f"**factory · gate → {decision}**"
    if why:
        body += f"\n{why}"
    body += f"\n{GATE_MARK}{json.dumps(record, separators=(',', ':'))} -->"
    _gh("issue", "comment", str(n), "--body", body)
    _set_state(n, target, states)
    print(f"#{n}: {state} → {decision} → {PREFIX}{target}")


# ----------------------------------------------------------------------------- reading the record


def cmd_labels() -> None:
    for state, color in LABEL_COLORS.items():
        _gh("label", "create", PREFIX + state, "--color", color, "--force",
            "--description", f"factory: {state}")
    print(f"{len(LABEL_COLORS)} labels ensured on {_repo()}")


def cmd_board() -> None:
    issues = _gh_json("issue", "list", "--state", "open", "--limit", "200",
                      "--json", "number,title,labels")
    by_state: dict[str, list] = {s: [] for s in STATES}
    for issue in issues:
        for s in _states(issue):
            by_state.setdefault(s, []).append(issue)
    for state in by_state:
        if not by_state[state]:
            continue
        tag = " (human)" if state in GATES else ""
        print(f"{PREFIX}{state}{tag}")
        for i in by_state[state]:
            print(f"  #{i['number']}  {i['title']}")


def cmd_threads(n: int) -> None:
    pr = _item_pr(n)
    if not pr:
        fail(f"#{n} has no PR")
    owner, name = _repo().split("/")
    query = """query($owner:String!,$name:String!,$pr:Int!){ repository(owner:$owner,name:$name){
      pullRequest(number:$pr){ reviewThreads(first:100){ nodes{ id isResolved path line
        comments(first:50){ nodes{ databaseId author{login} body } } } } } } }"""
    data = _gh_json("api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}",
                    "-f", f"name={name}", "-F", f"pr={pr['number']}")
    threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    open_threads = [t for t in threads if not t["isResolved"]]
    print(f"PR #{pr['number']}: {len(open_threads)} unresolved thread(s)")
    for t in open_threads:
        root = t["comments"]["nodes"][0]["databaseId"]
        print(f"\n{t['path']}:{t['line']}  thread {t['id']}  comment {root}")
        for c in t["comments"]["nodes"]:
            print(f"  @{c['author']['login']}: {c['body'].replace(REVIEW_MARK, '').strip()}")
    if open_threads:
        repo = _repo()
        print(f"\nreply:   gh api -X POST repos/{repo}/pulls/{pr['number']}/comments/<comment>"
              "/replies -f body='...'")
        print("resolve: gh api graphql -f query='mutation{resolveReviewThread("
              "input:{threadId:\"<thread>\"}){thread{isResolved}}}'")


HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def annotate(patch: str) -> str:
    """Prefix each diff line with its side and number so inline review comments can cite it."""
    out, old, new = [], None, None
    for line in patch.splitlines():
        if line.startswith(("diff --git ", "Binary files ")):
            old = new = None
        elif m := HUNK.match(line):
            old, new = int(m[1]), int(m[2])
        elif old is not None and line[:1] == "-":
            out.append(f"[OLD:{old}] {line[1:]}")
            old += 1
            continue
        elif old is not None and line[:1] == "+":
            out.append(f"[NEW:{new}] {line[1:]}")
            new += 1
            continue
        elif old is not None and line[:1] == " ":
            out.append(f"[OLD:{old},NEW:{new}] {line[1:]}")
            old, new = old + 1, new + 1
            continue
        out.append(line)
    return "\n".join(out)


def cmd_diff(n: int) -> None:
    pr = _item_pr(n)
    if not pr:
        fail(f"#{n} has no PR")
    print(annotate(_gh("pr", "diff", str(pr["number"]))))


# ----------------------------------------------------------------------------- metrics


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def item_metrics(n: int, comments: list[dict], timeline: list[dict], pr: dict | None,
                 commits: list[dict]) -> dict:
    runs = [r for c in comments for r in parse_marks(c["body"], RUN_MARK)]
    gates = [g for c in comments for g in parse_marks(c["body"], GATE_MARK)]
    started = min((e["created_at"] for e in timeline
                   if e.get("event") == "labeled" and e["label"]["name"] == PREFIX + "triage"),
                  default=None)
    merged = pr.get("mergedAt") if pr else None
    human_commits = [c for c in commits if (c["commit"]["author"] or {}).get("email") != BOT_EMAIL]
    return {
        "issue": n,
        "pr": pr.get("number") if pr else None,
        "runs": len(runs),
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in runs), 4),
        "shipped": bool(merged),
        "cycle_hours": round((_parse_ts(merged) - _parse_ts(started)).total_seconds() / 3600, 1)
        if merged and started else None,
        "steers": sum(g["decision"] == "request_changes" for g in gates) + len(human_commits),
        "autonomous": bool(merged) and not human_commits,
    }


def aggregate(items: list[dict]) -> dict:
    shipped = [i for i in items if i["shipped"]]
    total = round(sum(i["cost_usd"] for i in items), 2)
    cycles = sorted(i["cycle_hours"] for i in shipped if i["cycle_hours"] is not None)
    return {
        "items": len(items),
        "shipped": len(shipped),
        "total_cost_usd": total,
        "cost_per_shipped_usd": round(total / len(shipped), 2) if shipped else None,
        "median_cycle_hours": cycles[len(cycles) // 2] if cycles else None,
        "autonomy_pct": round(100 * sum(i["autonomous"] for i in shipped) / len(shipped))
        if shipped else None,
        "steers_per_shipped": round(sum(i["steers"] for i in shipped) / len(shipped), 2)
        if shipped else None,
        "runs": sum(i["runs"] for i in items),
    }


def cmd_metrics(since: str, as_json: bool) -> None:
    days = int(since.rstrip("d"))
    cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
    repo = _repo()
    issues = _gh_json("issue", "list", "--state", "all", "--limit", "500",
                      "--search", f"updated:>={cutoff}", "--json", "number,labels")
    items = []
    for issue in issues:
        if not set(_states(issue)) & set(STATIONS + GATES + ("done", "needs-info", "parked")):
            continue
        n = issue["number"]
        pr = _item_pr(n)
        commits = _paginated(f"repos/{repo}/pulls/{pr['number']}/commits") if pr else []
        timeline = _paginated(f"repos/{repo}/issues/{n}/timeline")
        items.append(item_metrics(n, _comments(n), timeline, pr, commits))
    summary = aggregate(items)
    if as_json:
        print(json.dumps({"since_days": days, "summary": summary, "items": items}, indent=2))
        return
    s = summary
    print(f"factory metrics · last {days}d · {s['items']} items · {s['shipped']} shipped · "
          f"{s['runs']} runs")
    print(f"  cost per shipped item  ${s['cost_per_shipped_usd']}" if s["shipped"]
          else "  cost per shipped item  — (nothing shipped yet)")
    print(f"  total cost             ${s['total_cost_usd']}  (Claude Code list-price estimate)")
    print(f"  median cycle           {s['median_cycle_hours']} h")
    print(f"  autonomy               {s['autonomy_pct']}% of shipped PRs had no human commit")
    print(f"  steers per shipped     {s['steers_per_shipped']}")
    for i in items:
        flag = "✓" if i["shipped"] else " "
        print(f"  {flag} #{i['issue']:<5} ${i['cost_usd']:<7.2f} {i['runs']} runs  "
              f"{i['steers']} steers")


# ----------------------------------------------------------------------------- entry point


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="factory", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("labels", help="create or update the factory:* labels on this repo")
    sub.add_parser("board", help="open issues grouped by factory:* label")
    s = sub.add_parser("run", help="run the station an issue's label names (or `retro`)")
    s.add_argument("issue", help="issue number, or `retro`")
    s.add_argument("--out", help="write the report JSON here instead of stdout")
    s.add_argument("--budget", type=float, help="USD cap for the run (default per station)")
    s = sub.add_parser("apply", help="record a station report: run comment + label move")
    s.add_argument("issue", type=int)
    s.add_argument("report", help="path to the report JSON `factory run` wrote")
    s = sub.add_parser("gate", help="record a human decision at a gate")
    s.add_argument("issue", type=int)
    s.add_argument("decision", choices=DECISIONS)
    s.add_argument("--why", help="the reason; this is what retro reads")
    s = sub.add_parser("threads", help="unresolved review threads on the item's PR")
    s.add_argument("issue", type=int)
    s = sub.add_parser("diff", help="the item's PR diff with [OLD:n]/[NEW:n] line markers")
    s.add_argument("issue", type=int)
    s = sub.add_parser("metrics", help="cost per shipped item, cycle time, autonomy, steers")
    s.add_argument("--since", default="30d", help="window, e.g. 30d")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("schema", help="the report JSON schema for a station")
    s.add_argument("station", choices=(*STATIONS, "retro"))
    a = p.parse_args(argv)
    try:
        match a.cmd:
            case "labels":
                cmd_labels()
            case "board":
                cmd_board()
            case "run":
                cmd_run(a.issue, a.out, a.budget)
            case "apply":
                cmd_apply(a.issue, a.report)
            case "gate":
                cmd_gate(a.issue, a.decision, a.why)
            case "threads":
                cmd_threads(a.issue)
            case "diff":
                cmd_diff(a.issue)
            case "metrics":
                cmd_metrics(a.since, a.json)
            case "schema":
                print(json.dumps(schema(a.station), indent=2))
    except subprocess.CalledProcessError as e:
        sys.stderr.write(e.stderr or e.stdout or "")
        fail(f"`{' '.join(e.cmd)}` failed")
