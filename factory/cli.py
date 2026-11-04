"""factory — the deterministic layer of a software factory that runs inside GitHub Actions.

GitHub holds every piece of state: an issue is a work item, its `factory:*` labels are its state,
its comments are its log, and its `<type>/<n>-<slug>` branches and pull requests are its
artifacts. The workflow decides when a station runs and packages what it reads; this module does
only what must be shared across stations and right once: the label set, the report schema each
station answers, applying a report (validation, the PR review, the run comment, the label move,
the attempt cap, the dispatch decision), and metrics derived from the record. All GitHub access
goes through `gh` via `_gh`, so tests stub one function.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

PREFIX = "factory:"
# Three vocabularies, told apart by shape: a station is one word (`implement`), a label is a
# kebab-case GitHub label name shown with the prefix (`factory:ready-to-implement`), a verdict is
# a snake_case enum value in a station's JSON report (`ready_to_implement`).
#
# name -> (color, description). Yellow marks every label that waits on a human.
LABELS = {
    "triaged": (
        "5319E7",
        "The factory has assessed this issue; stays for the life of the item",
    ),
    "needs-info": (
        "FBCA04",
        "Triage has questions; answer, then remove this label to triage again",
    ),
    "ready-to-spec": (
        "1D76DB",
        "Go-ahead from a human: the factory writes a spec PR",
    ),
    "spec-review": (
        "FBCA04",
        "A spec PR is waiting: merge it to start implementation, or request changes",
    ),
    "ready-to-implement": (
        "0E8A16",
        "Go-ahead from a human: the factory builds the change on a PR",
    ),
    "in-review": (
        "006B75",
        "The factory is implementing or reviewing the code PR",
    ),
    "ship-review": (
        "FBCA04",
        "The factory approved the code PR: merge it to ship, or request changes",
    ),
    "needs-human": (
        "FBCA04",
        "Stuck: a station was blocked or the review cap was hit; look at the PR",
    ),
}
# `triaged` stays for the life of the issue; the rest are states, at most one at a time.
STATES = tuple(name for name in LABELS if name != "triaged")
STATIONS = ("triage", "spec", "implement", "review")
MAX_SENDBACKS = 3

# What a verdict does to the state: (station, verdict) -> the label apply sets, replacing whatever
# state was there. None: the state is left alone, because that verdict is a recommendation a human
# acts on by applying a label themselves. The only routing that exists.
TRANSITIONS = {
    ("triage", "ready_to_implement"): None,
    ("triage", "ready_to_spec"): None,
    ("triage", "needs_info"): "needs-info",
    ("triage", "park"): None,
    ("spec", "ready_for_review"): "spec-review",
    ("spec", "blocked"): "needs-human",
    ("implement", "implemented"): "in-review",
    ("implement", "blocked"): "needs-human",
    ("review", "approve"): "ship-review",
    ("review", "request_changes"): "in-review",
}
# (station, verdict) -> the station the workflow runs next. Everything else waits on a human or
# on an event GitHub fires by itself.
DISPATCH = {("implement", "implemented"): "review", ("review", "request_changes"): "implement"}
# The states an issue may be in when a station's report lands; from anywhere else the report is
# stale or misrouted and refused. The station was picked from an event minutes earlier and labels
# can move in between. Triage is absent: a new issue has no state, a reopened one may have any.
# `needs-human` is in both sets because a human un-sticks a parked item from its PR (Request
# changes, ready for review, dispatch), which starts the station before any label moves.
RUNS_AT = {
    "spec": {"ready-to-spec", "spec-review"},
    "implement": {"ready-to-implement", "in-review", "ship-review", "needs-human"},
    "review": {"in-review", "ship-review", "needs-human"},
}

HEADLINE = {
    ("triage", "ready_to_implement"): "Triage · recommends ready-to-implement",
    ("triage", "ready_to_spec"): "Triage · recommends ready-to-spec",
    ("triage", "needs_info"): "Triage · needs info",
    ("triage", "park"): "Triage · recommends closing",
    ("spec", "ready_for_review"): "Spec · ready for your review",
    ("spec", "blocked"): "Spec · blocked",
    ("implement", "implemented"): "Implement · PR ready for review",
    ("implement", "blocked"): "Implement · blocked",
    ("review", "approve"): "Review · approved",
    ("review", "request_changes"): "Review · changes requested",
}
NEXT_STEP = {
    ("triage", "ready_to_implement"): "To start, add the `factory:ready-to-implement` label.",
    ("triage", "ready_to_spec"): "To start, add the `factory:ready-to-spec` label.",
    ("triage", "needs_info"): "Answer here, then remove the `factory:needs-info` label to triage "
    "again.",
    ("triage", "park"): "If you agree, close this issue as not planned. To go ahead anyway, add "
    "a ready label.",
    ("spec", "ready_for_review"): "Merge the spec PR to start implementation, or request changes "
    "on it.",
    ("spec", "blocked"): "Answer here, then add the `factory:ready-to-spec` label again.",
    ("implement", "implemented"): "The factory is reviewing the PR.",
    ("implement", "blocked"): "Answer here and add `factory:ready-to-implement` again, or answer "
    "in a Request changes review on the PR.",
    ("review", "approve"): "Merge the PR to ship, or request changes on it.",
    ("review", "request_changes"): "The factory is addressing the review.",
}
CAPPED_STEP = (
    f"{MAX_SENDBACKS} review rounds without a human. Take a look at the PR: merge it if it is "
    "good, or request changes and the factory picks it up again."
)

BOT_EMAIL = "factory@users.noreply.github.com"
RUN_MARK, REVIEW_MARK = "<!-- factory:run ", "<!-- factory:review "
BRANCH = re.compile(r"^([a-z]+)/(\d+)-")


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


def _paginated(endpoint: str) -> list:
    return [x for page in _gh_json("api", "--paginate", "--slurp", endpoint) or [] for x in page]


def _issue(n: int) -> dict:
    return _gh_json("issue", "view", str(n), "--json", "number,title,labels,state")


def _labels(issue: dict) -> list[str]:
    names = [lb["name"] for lb in issue.get("labels", [])]
    return [s[len(PREFIX):] for s in names if s.startswith(PREFIX)]


def _edit_labels(n: int, add: list[str], remove: list[str]) -> None:
    args = ["issue", "edit", str(n)]
    for name in add:
        args += ["--add-label", PREFIX + name]
    for name in remove:
        args += ["--remove-label", PREFIX + name]
    if len(args) > 3:
        _gh(*args)


def branch_issue(head: str) -> tuple[str, int] | None:
    """(type, issue) from a `<type>/<n>-<slug>` branch name, or None for any other branch."""
    m = BRANCH.match(head)
    return (m[1], int(m[2])) if m else None


def _open_pr(n: int, spec: bool) -> dict | None:
    """The item's open PR of one kind: from `spec/<n>-*` when spec, else from any other
    `<type>/<n>-*` branch. Oldest first when there are several."""
    prs = _gh_json("pr", "list", "--state", "open", "--limit", "100",
                   "--json", "number,url,headRefName,headRefOid,isDraft")
    mine = []
    for p in prs:
        kind = branch_issue(p["headRefName"])
        if kind and kind[1] == n and (kind[0] == "spec") == spec:
            mine.append(p)
    mine.sort(key=lambda p: p["number"])
    return mine[0] if mine else None


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
            "description": "One or two plain sentences a colleague skims on the issue: the "
            "outcome and its why, in everyday words (no internal vocabulary such as station, "
            "verdict, packet, or invariant numbers). For needs_info or blocked: the concrete "
            "questions whose answers unblock the work, one line each.",
        },
        "notes": {
            "type": "string",
            "description": "What the next reader must know that the summary and the artifacts do "
            "not carry: a fork you settled and why, a limit, a spec you changed. Rendered "
            "collapsed under the summary. Omit when there is nothing.",
        },
        "followups": {
            "type": "array",
            "description": "Real defects or gaps you found outside this item's scope. Each is "
            "filed as a plain issue for a human to triage. Omit when there are none.",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
                "required": ["title", "body"],
                "additionalProperties": False,
            },
        },
    }
    if station == "retro":
        del props["followups"]
    required = ["verdict", "summary"]
    if station == "review":
        props["body"] = {
            "type": "string",
            "description": "The review body, in this shape: `## TL;DR` 1-2 sentences; "
            "`## Concerns` up to five bullets, each starting with its severity tag and naming a "
            "file:line, at most two sentences each, or one line saying there are none; "
            "`## Verdict` `Found: X critical, Y important, Z suggestions · Approve` or "
            "`· Request changes`. "
            "When a spec exists, a `<details>` block with one line per numbered rule and its "
            "status. Do not include change summaries, praise, or a restatement of the diff.",
        }
        props["comments"] = {
            "type": "array",
            "description": "Inline findings. path, line, and side are copied from the annotated "
            "diff; anything without an annotation goes in body instead.",
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
            "description": "Ids of earlier review threads whose fix you verified on this head; "
            "they are resolved for you.",
            "items": {"type": "string"},
        }
        required += ["body", "comments"]
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}


# What the workflow's run step adds to the station's structured output.
RUNNER_KEYS = {"station", "model", "cost_usd", "session_id", "turns", "duration_ms", "run_url",
               "ts", "head", "pr"}


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
    for i, c in enumerate(report.get("comments", [])):
        item = sch["properties"]["comments"]["items"]
        if set(c) - set(item["properties"]) or [k for k in item["required"] if k not in c]:
            fail(f"comments[{i}] does not match the review schema")


# ----------------------------------------------------------------------------- the record


def run_comment(report: dict, capped: bool = False) -> str:
    """The issue comment that records one station run: headline, outcome, next step, folded
    notes, and the hidden JSON that metrics and retro read back."""
    ms = report.get("duration_ms") or 0
    took = f"{ms / 60000:.0f}m" if ms >= 60000 else f"{ms / 1000:.0f}s"
    key = (report["station"], report["verdict"])
    head = f"**{HEADLINE[key]}** · ${report.get('cost_usd') or 0:.2f} · {took}"
    if report.get("run_url"):
        head += f" · [run]({report['run_url']})"
    body = [head, report["summary"].strip(), CAPPED_STEP if capped else NEXT_STEP[key]]
    if report.get("notes"):
        body += ["<details><summary>Details</summary>", "", report["notes"].strip(), "",
                 "</details>"]
    record = {k: report.get(k) for k in ("verdict", *RUNNER_KEYS)}
    if capped:
        record["capped"] = True
    body += [f"{RUN_MARK}{json.dumps(record, separators=(',', ':'))} -->"]
    return "\n".join(body)


def parse_marks(text: str, mark: str) -> list[dict]:
    pattern = re.escape(mark) + r"(\{.*?\}) -->"
    return [json.loads(m) for m in re.findall(pattern, text, flags=re.S)]


def _factory_reviews(reviews: list[dict]) -> list[tuple[dict, dict]]:
    """(review, its hidden record) for each review the factory posted."""
    out = []
    for r in reviews:
        if (r.get("user") or {}).get("type") == "Bot":
            marks = parse_marks(r.get("body") or "", REVIEW_MARK)
            if marks:
                out.append((r, marks[0]))
    return out


TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}


def sendbacks(reviews: list[dict], commits: list[dict], session_id: str | None = None) -> int:
    """Consecutive factory send-backs on a PR since the last review by a maintainer or commit by a
    human. The review from `session_id` is left out so a retried apply counts the same as the
    first. Commits count by committer date: a rebase keeps the author date of the original."""
    events: list[tuple[str, str]] = []
    for r in reviews:
        if (r.get("user") or {}).get("type") != "Bot" and r.get("author_association") in TRUSTED:
            events.append((r.get("submitted_at") or "", "human"))
    for r, rec in _factory_reviews(reviews):
        if rec.get("verdict") == "request_changes" and rec.get("session_id") != session_id:
            events.append((r.get("submitted_at") or "", "sendback"))
    for c in commits:
        if (c["commit"]["author"] or {}).get("email") != BOT_EMAIL:
            events.append(((c["commit"]["committer"] or {}).get("date") or "", "human"))
    count = 0
    for _, kind in sorted(events, reverse=True):
        if kind == "human":
            break
        count += 1
    return count


# ----------------------------------------------------------------------------- apply


def cmd_apply(n: int, report_path: str) -> None:
    report = json.loads(Path(report_path).read_text())
    station, verdict = report.get("station"), report.get("verdict")
    if station not in STATIONS:
        fail(f"report station {station!r} is not one of {STATIONS}")
    validate(report, station)
    issue = _issue(n)
    if issue["state"] != "OPEN":
        fail(f"#{n} is closed; nothing to apply")
    states = [s for s in _labels(issue) if s in STATES]
    if station in RUNS_AT and not set(states) & RUNS_AT[station]:
        fail(f"#{n} is at {states or ['no state']}, where no {station} run belongs")
    target = TRANSITIONS[(station, verdict)]
    pr = None
    if station == "spec":
        pr = _open_pr(n, spec=True)
    elif station in ("implement", "review"):
        pr = _open_pr(n, spec=False)
    if verdict in ("ready_for_review", "implemented"):
        if not pr:
            fail(f"{verdict} reported but #{n} has no open PR from a "
                 f"{'spec' if station == 'spec' else '<type>'}/{n}-* branch")
        if pr.get("isDraft"):
            fail(f"{verdict} reported but PR #{pr['number']} is still a draft")
    if station == "review":
        if not pr:
            fail(f"review reported but #{n} has no open PR")
        if report.get("head") and report["head"] != pr["headRefOid"]:
            print(f"factory: PR #{pr['number']} moved to {pr['headRefOid'][:12]} since this "
                  f"review of {report['head'][:12]}; reviewing the new head instead")
            print("next: review")
            return
    capped = False
    if (station, verdict) == ("review", "request_changes"):
        repo = _repo()
        reviews = _paginated(f"repos/{repo}/pulls/{pr['number']}/reviews")
        commits = _paginated(f"repos/{repo}/pulls/{pr['number']}/commits")
        capped = sendbacks(reviews, commits, report.get("session_id")) >= MAX_SENDBACKS
        if capped:
            target = "needs-human"
    already = any(
        r.get("session_id") == report.get("session_id")
        for c in _paginated(f"repos/{_repo()}/issues/{n}/comments")
        for r in parse_marks(c["body"], RUN_MARK)
    )
    if already:
        print(f"factory: run {report.get('session_id')} already recorded on #{n}", file=sys.stderr)
    else:
        if station == "review":
            _post_review(pr, report)
            for thread in report.get("resolve") or []:
                try:
                    _gh("api", "graphql", "-f", "query=mutation($id:ID!){resolveReviewThread("
                        "input:{threadId:$id}){thread{isResolved}}}", "-f", f"id={thread}")
                except subprocess.CalledProcessError as e:
                    print(f"factory: could not resolve thread {thread}; resolve it by hand: "
                          f"{(e.stderr or '').strip()}", file=sys.stderr)
        for f in report.get("followups") or []:
            body = f"{f['body'].strip()}\n\nFound by the factory while working on #{n}."
            try:
                url = _gh("issue", "create", "--title", f["title"], "--body", body).strip()
            except subprocess.CalledProcessError:
                print(f"factory: could not file follow-up {f['title']!r}", file=sys.stderr)
                continue
            # An issue opened with the workflow's token fires no event; the workflow triages it
            # from this line.
            print(f"followup: {url.rsplit('/', 1)[-1]}")
        _gh("issue", "comment", str(n), "--body", run_comment(report, capped))
    if station == "triage" and not target:
        _edit_labels(n, ["triaged"], [])
    else:
        add = ["triaged", target] if station == "triage" else [target]
        _edit_labels(n, add, [s for s in states if s != target])
    link = f" · {pr['url']}" if pr else ""
    print(f"#{n}: {HEADLINE[(station, verdict)]}{' · capped' if capped else ''}{link}")
    print(f"next: {'none' if capped else DISPATCH.get((station, verdict), 'none')}")


def _post_review(pr: dict, report: dict) -> None:
    """Post the station's review as one call: body, inline findings, and the hidden record.
    The event is always COMMENT: GitHub refuses APPROVE and REQUEST_CHANGES from the account
    that authored the PR, and the factory authors every PR it reviews, so the verdict lives in
    the record and the label. A rejected inline anchor degrades to findings in the body rather
    than a dropped finding."""
    head = report.get("head") or pr["headRefOid"]
    record = {"verdict": report["verdict"], "head": head, "session_id": report.get("session_id")}
    footer = f"<sub>factory review · [run]({report['run_url']})</sub>" if report.get(
        "run_url") else "<sub>factory review</sub>"
    mark = f"{REVIEW_MARK}{json.dumps(record, separators=(',', ':'))} -->"
    body = f"{report['body'].strip()}\n\n{footer}\n{mark}"
    posted = _paginated(f"repos/{_repo()}/pulls/{pr['number']}/reviews")
    if any(rec.get("head") == head for _, rec in _factory_reviews(posted)):
        print(f"factory: review at {head[:12]} already on PR #{pr['number']}", file=sys.stderr)
        return
    payload = {"event": "COMMENT", "body": body, "comments": list(report["comments"]),
               "commit_id": head}
    endpoint = f"repos/{_repo()}/pulls/{pr['number']}/reviews"
    try:
        _gh("api", "--method", "POST", endpoint, "--input", "-", input=json.dumps(payload))
        return
    except subprocess.CalledProcessError as e:
        err = (e.stdout + e.stderr).lower()
        if not payload["comments"] or not ("line" in err or "path" in err or "position" in err):
            sys.stderr.write(e.stdout + e.stderr)
            fail("posting the PR review failed")
    folded = "\n".join(f"- `{c['path']}:{c['line']}` — {c['body'].strip()}"
                       for c in payload["comments"])
    payload["body"] = body.replace(footer, f"Findings:\n{folded}\n\n{footer}")
    payload["comments"] = []
    try:
        _gh("api", "--method", "POST", endpoint, "--input", "-", input=json.dumps(payload))
    except subprocess.CalledProcessError as e:
        sys.stderr.write(e.stdout + e.stderr)
        fail("posting the PR review failed after folding the findings into the body")


# ----------------------------------------------------------------------------- labels


def cmd_labels() -> None:
    for name, (color, description) in LABELS.items():
        _gh("label", "create", PREFIX + name, "--color", color, "--force",
            "--description", description)
    existing = _gh_json("label", "list", "--limit", "200", "--json", "name") or []
    stale = [lb["name"] for lb in existing
             if lb["name"].startswith(PREFIX) and lb["name"][len(PREFIX):] not in LABELS]
    for name in stale:
        _gh("label", "delete", name, "--yes")
    print(f"{len(LABELS)} labels ensured on {_repo()}"
          + (f", {len(stale)} stale removed" if stale else ""))


# ----------------------------------------------------------------------------- metrics


def item_metrics(issue: dict, comments: list[dict], prs: list[dict], reviews: list[dict],
                 commits: list[dict]) -> dict:
    """One item's row from its comments, its PRs, the reviews on them, and the code PR's commits."""
    runs = [r for c in comments for r in parse_marks(c["body"], RUN_MARK)]
    code = [p for p in prs if branch_issue(p["headRefName"])[0] != "spec"]
    merged = next((p["mergedAt"] for p in code if p.get("mergedAt")), None)
    shipped = issue["state"] == "CLOSED" and issue.get("stateReason") == "COMPLETED" and bool(
        merged)
    human_commits = [c for c in commits if (c["commit"]["author"] or {}).get("email") != BOT_EMAIL]
    human_sendbacks = [r for r in reviews if (r.get("user") or {}).get("type") != "Bot"
                       and r.get("state") == "CHANGES_REQUESTED"]
    steers = len(human_sendbacks) + len(human_commits)
    return {
        "issue": issue["number"],
        "prs": [p["number"] for p in prs],
        "runs": len(runs),
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in runs), 2),
        # Station wall-clock only; the hours a human took to respond are not the factory's to move.
        "factory_minutes": round(sum(r.get("duration_ms") or 0 for r in runs) / 60000, 1),
        "shipped": shipped,
        "parked": issue["state"] == "CLOSED" and issue.get("stateReason") == "NOT_PLANNED",
        "steers": steers,
        "autonomous": shipped and steers == 0,
        "needs_human": any(r.get("verdict") == "blocked" or r.get("capped") for r in runs),
    }


def aggregate(items: list[dict]) -> dict:
    """Every per-shipped figure is an average over the items that shipped: what one shipped item
    cost, took, and needed. Spend on items that never shipped appears only in the total."""
    shipped = [i for i in items if i["shipped"]]
    n = len(shipped)

    def per_shipped(key: str, digits: int = 2):
        return round(sum(i[key] for i in shipped) / n, digits) if n else None

    return {
        "items": len(items),
        "shipped": n,
        "total_cost_usd": round(sum(i["cost_usd"] for i in items), 2),
        "cost_per_shipped_usd": per_shipped("cost_usd"),
        "factory_minutes_per_shipped": per_shipped("factory_minutes", 1),
        "runs_per_shipped": per_shipped("runs", 1),
        "steers_per_shipped": per_shipped("steers"),
        "needs_human_per_shipped": per_shipped("needs_human"),
        "autonomy_pct": round(100 * sum(i["autonomous"] for i in shipped) / n) if n else None,
    }


def cmd_metrics(since: str, as_json: bool) -> None:
    days = int(since.rstrip("d"))
    cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
    repo = _repo()
    issues = _gh_json("issue", "list", "--state", "all", "--limit", "500",
                      "--search", f"updated:>={cutoff}",
                      "--json", "number,labels,state,stateReason,createdAt")
    prs = _gh_json("pr", "list", "--state", "all", "--limit", "500",
                   "--search", f"updated:>={cutoff}", "--json", "number,headRefName,mergedAt")
    by_issue: dict[int, list[dict]] = {}
    for p in prs:
        if kind := branch_issue(p["headRefName"]):
            by_issue.setdefault(kind[1], []).append(p)
    items = []
    for issue in issues:
        if "triaged" not in _labels(issue):
            continue
        n = issue["number"]
        mine = sorted(by_issue.get(n, []), key=lambda p: p["number"])
        reviews = [r for p in mine
                   for r in _paginated(f"repos/{repo}/pulls/{p['number']}/reviews")]
        code = [p for p in mine if branch_issue(p["headRefName"])[0] != "spec"]
        commits = [c for p in code
                   for c in _paginated(f"repos/{repo}/pulls/{p['number']}/commits")]
        comments = _paginated(f"repos/{repo}/issues/{n}/comments")
        items.append(item_metrics(issue, comments, mine, reviews, commits))
    summary = aggregate(items)
    if as_json:
        print(json.dumps({"since_days": days, "summary": summary, "items": items}, indent=2))
        return
    s = summary
    print(f"Factory metrics · last {days} days")
    print(f"  Items: {s['items']} · Shipped: {s['shipped']} · Total cost: ${s['total_cost_usd']} "
          "(Claude Code list-price estimate)")
    print()
    print("Per shipped item: averages over the items that shipped")
    if s["shipped"]:
        row = "  {:<15} {:<10} {}".format
        print(row("Cost:", f"${s['cost_per_shipped_usd']}", "The North Star metric."))
        print(row("Factory time:", f"{s['factory_minutes_per_shipped']} min",
                  "Minutes the stations ran on the item, across all its runs."))
        print(row("Runs:", s["runs_per_shipped"], "Station runs on the item. Three is the floor "
                  "(triage, implement, review); spec and send-backs add."))
        print(row("Steers:", s["steers_per_shipped"], "Human Request-changes reviews and commits."))
        print(row("Needs-human:", s["needs_human_per_shipped"],
                  "Share that got stuck: a station was blocked or the review cap was hit."))
        print()
        print("Across shipped items:")
        print(row("Autonomy:", f"{s['autonomy_pct']}%", "Share shipped with no human steer."))
    else:
        print("  Nothing shipped yet, so no per-shipped figures.")
    print()
    print("Items (✓ shipped · × parked · blank open)")
    for i in items:
        flag = "✓" if i["shipped"] else ("×" if i["parked"] else " ")
        print(f"  {flag} #{i['issue']:<5} ${i['cost_usd']:<7.2f} {i['runs']} runs  "
              f"{i['factory_minutes']}m factory  {i['steers']} steers")


# ----------------------------------------------------------------------------- entry point


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="factory", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("labels", help="create the factory:* labels on this repo; remove stale ones")
    s = sub.add_parser("schema", help="the report JSON schema for a station")
    s.add_argument("station", choices=(*STATIONS, "retro"))
    s = sub.add_parser("apply", help="record a station report: review, run comment, labels, next")
    s.add_argument("issue", type=int)
    s.add_argument("report", help="path to the report JSON the run step wrote")
    s = sub.add_parser("metrics", help="cost, factory time, runs, steers, and stuck items "
                       "per shipped item; autonomy")
    s.add_argument("--since", default="14d", help="window, e.g. 14d")
    s.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        match a.cmd:
            case "labels":
                cmd_labels()
            case "schema":
                print(json.dumps(schema(a.station), indent=2))
            case "apply":
                cmd_apply(a.issue, a.report)
            case "metrics":
                cmd_metrics(a.since, a.json)
    except subprocess.CalledProcessError as e:
        sys.stderr.write(e.stderr or e.stdout or "")
        fail(f"`{' '.join(e.cmd)}` failed")


if __name__ == "__main__":
    main()
