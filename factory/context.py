"""Packets: the Markdown a station reads, rendered from raw GitHub JSON the workflow fetched.

    python -m factory.context <station> <raw-dir> <out-dir>
    python -m factory.context select <raw-dir>        the head the last factory review saw

No network access happens here. The workflow fetches JSON into the raw directory (issue,
comments, PR, reviews, threads, conversation, diff, delta, metrics), this module turns it into a
few files a station can read top to bottom, and the workflow uploads the result as an artifact so
a human can see exactly what the station saw.

| station   | files                                        |
|-----------|----------------------------------------------|
| triage    | issue.md, related.md                         |
| spec      | issue.md, pr.md when the spec PR exists      |
| implement | issue.md, pr.md when the code PR exists      |
| review    | issue.md, pr.md, diff.md, followup.md        |
| retro     | metrics.json, items.md                       |
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REVIEW_MARK = "<!-- factory:review"
BOT_EMAIL = "factory@users.noreply.github.com"
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


# ----------------------------------------------------------------------------- pieces


def load(raw: Path, name: str, default=None):
    path = raw / name
    return json.loads(path.read_text()) if path.exists() else default


def strip(text: str | None) -> str:
    """Drop the hidden records and footers other factory runs left behind."""
    return re.sub(r"<!--.*?-->|<sub>.*?</sub>", "", text or "", flags=re.S).strip()


def first_line(text: str | None, width: int = 200) -> str:
    body = strip(text)
    line = body.splitlines()[0] if body else ""
    return line[:width] + (" …" if len(body) > width else "")


def is_bot(entry: dict) -> bool:
    return (entry.get("user") or {}).get("type") == "Bot"


def who(entry: dict) -> str:
    login = (entry.get("user") or {}).get("login")
    if is_bot(entry):
        return f"{login} (bot)"
    return f"{login} ({entry.get('author_association', 'NONE')})"


def when(ts: str | None) -> str:
    return (ts or "")[:16].replace("T", " ")


def annotate(patch: str) -> str:
    """Prefix each diff line with its side and number: `[OLD:n]` removed (LEFT n), `[NEW:n]`
    added (RIGHT n), `[OLD:n,NEW:m]` context (RIGHT m). Inline review comments cite these."""
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


def factory_reviews(reviews: list[dict]) -> list[dict]:
    """The factory's own reviews, oldest first. A reply the implementer posts inside a thread also
    shows up as an empty review; the hidden record is what marks a real one."""
    mine = [r for r in reviews if is_bot(r) and REVIEW_MARK in (r.get("body") or "")]
    return sorted(mine, key=lambda r: (r.get("submitted_at") or "", r.get("id") or 0))


# ----------------------------------------------------------------------------- files


def issue_md(issue: dict, comments: list[dict]) -> str:
    labels = ", ".join(lb["name"] for lb in issue.get("labels") or []) or "none"
    out = [f"# Issue #{issue['number']}: {issue['title']}",
           f"Opened by {who(issue)} on {when(issue.get('created_at'))} · state "
           f"{issue.get('state')} · labels: {labels}", "",
           strip(issue.get("body")) or "_(no body)_"]
    if comments:
        out += ["", "## Comments"]
        for c in comments:
            out += ["", f"### {who(c)} · {when(c.get('created_at'))}", "", strip(c.get("body"))]
    return "\n".join(out) + "\n"


def related_md(n: int, issues: list[dict], prs: list[dict]) -> str:
    out = ["# Open work in this repository", "",
           "One line each; judge duplicates and dependencies from here, then read what matters.",
           "", "## Issues"]
    for i in issues:
        if i["number"] != n:
            labels = ", ".join(lb["name"] for lb in i.get("labels") or [])
            out.append(f"- #{i['number']} {i['title']}" + (f" [{labels}]" if labels else ""))
    if out[-1] == "## Issues":
        out.append("- none")
    out += ["", "## Pull requests"]
    out += [f"- #{p['number']} {p['title']} (`{p.get('headRefName', '')}`)" for p in prs] or [
        "- none"]
    return "\n".join(out) + "\n"


def threads_md(threads: list[dict]) -> list[str]:
    """Open threads in full, each with the id to resolve and the comment id to reply to; resolved
    threads as one line."""
    out: list[str] = []
    for t in sorted(threads, key=lambda t: (t["isResolved"], t.get("path") or "")):
        nodes = t["comments"]["nodes"]
        where = f"`{t.get('path')}:{t.get('line') or '?'}`"
        if t["isResolved"]:
            gist = first_line(nodes[0]["body"], 100) if nodes else ""
            out.append(f"- {where} · resolved · {gist}")
            continue
        head = f"### {where} · open · thread `{t['id']}`"
        if nodes:
            head += f" · reply to comment `{nodes[0]['databaseId']}`"
        out += ["", head]
        for c in nodes:
            out += ["", f"**{login(c)}** · {when(c.get('createdAt'))}", "", strip(c["body"])]
    return out


def login(node: dict) -> str:
    """A thread comment's author; GraphQL returns null for a deleted account."""
    return (node.get("author") or {}).get("login") or "ghost"


def pr_md(pr: dict, reviews: list[dict], threads: list[dict], talk: list[dict]) -> str:
    """Everything said on a PR: description, every review with a body, every thread, and the
    conversation. Open threads and human comments are what the next pass must answer."""
    head, base = pr.get("head") or {}, pr.get("base") or {}
    out = [f"# PR #{pr['number']}: {pr.get('title', '')}",
           f"By {who(pr)} · `{head.get('ref')}` at {(head.get('sha') or '')[:12]} → "
           f"`{base.get('ref')}`{' · draft' if pr.get('draft') else ''} · {pr.get('html_url', '')}",
           "", "## Description", "", strip(pr.get("body")) or "_(no description)_"]
    # A human's review counts even with no body: the verdict itself is the message. A bot's
    # bodyless review is the artifact of a reply posted inside a thread.
    spoken = [r for r in reviews if strip(r.get("body")) or not is_bot(r)]
    if spoken:
        out += ["", "## Reviews", "",
                "A bar a human states here binds like the spec."]
        for r in sorted(spoken, key=lambda r: r.get("submitted_at") or ""):
            state = (r.get("state") or "").lower().replace("_", " ")
            out += ["", f"### {who(r)} · {state} · at {(r.get('commit_id') or '')[:12]} · "
                        f"{when(r.get('submitted_at'))}", "", strip(r.get("body")) or "_(no text)_"]
    if threads:
        out += ["", "## Threads", "",
                "Open threads are the worklist; whoever raised one closes it.",
                *threads_md(threads)]
    if talk:
        out += ["", "## Conversation", "",
                "A human's note here belongs to no line; an unanswered one is a finding."]
        for c in sorted(talk, key=lambda c: c.get("created_at") or ""):
            out += ["", f"### {who(c)} · {when(c.get('created_at'))}", "", strip(c.get("body"))]
    return "\n".join(out) + "\n"


def diff_md(patch: str) -> str:
    return ("# Annotated diff\n\n`[OLD:n]` removed (LEFT n) · `[NEW:n]` added (RIGHT n) · "
            "`[OLD:n,NEW:m]` context (RIGHT m). Copy path, side, and line from here for every "
            f"inline comment.\n\n```diff\n{annotate(patch)}\n```\n")


def followup_md(reviews: list[dict], head: str, delta: str | None) -> str:
    """The last factory review and what changed since it; `pr.md` carries the threads."""
    mine = factory_reviews(reviews)
    if not mine:
        return "No earlier factory review on this PR: this is the first review.\n"
    last = mine[-1]
    prev = last.get("commit_id") or ""
    out = [f"# Follow-up: the factory last reviewed this PR at {prev[:12]}", "",
           "Judge whether each earlier finding is fixed, still open, or declined with a reason; "
           "the threads are in pr.md. List the ids of threads you verified fixed in `resolve`.",
           "", f"## Last review · {when(last.get('submitted_at'))}", "", strip(last.get("body")),
           "", f"## Changes since {prev[:12]} (to {head[:12]})", ""]
    if prev == head or (delta is not None and not delta.strip()):
        out.append("No code changes since the last review.")
    elif delta is None:
        out.append("Delta unavailable; use diff.md.")
    else:
        out += ["```diff", annotate(delta), "```"]
    return "\n".join(out) + "\n"


def items_md(metrics: dict, raw: Path) -> str:
    """The retro's record: per item, one line per factory run and every human touch."""
    s = metrics.get("summary", {})
    out = ["# The record", "",
           f"{s.get('items', 0)} items · {s.get('shipped', 0)} shipped · cost per shipped item "
           f"${s.get('cost_per_shipped_usd')} · {s.get('steers_per_shipped')} steers per shipped "
           f"· {s.get('needs_human', 0)} needs-human", "",
           "A factory line is what the run said; a human line is what a person had to add, "
           "correct, or decide."]
    for item in metrics.get("items", []):
        n = item["issue"]
        folder = raw / "items" / str(n)
        state = "shipped" if item.get("shipped") else "parked" if item.get("parked") else "open"
        flag = " · needs-human" if item.get("needs_human") else ""
        out += ["", f"## #{n} · {state} · ${item.get('cost_usd', 0):.2f} · {item.get('runs', 0)} "
                    f"runs · {item.get('steers', 0)} steers{flag}"]
        for c in load(folder, "comments.json", []):
            label = "factory" if is_bot(c) else f"{(c.get('user') or {}).get('login')} · " \
                                                f"{when(c.get('created_at'))}"
            out.append(f"- {label}: {first_line(c.get('body'))}")
        for m in item.get("prs") or []:
            out += ["", f"### PR #{m}"]
            for r in load(folder, f"reviews-{m}.json", []):
                if not is_bot(r) and strip(r.get("body")):
                    state = (r.get("state") or "").lower().replace("_", " ")
                    out.append(f"- human review · {state} · {(r.get('user') or {}).get('login')}: "
                               f"{first_line(r['body'])}")
            for t in load(folder, f"threads-{m}.json", []):
                humans = [c for c in t["comments"]["nodes"] if login(c) != "github-actions"]
                if humans:
                    state = "resolved" if t["isResolved"] else "open"
                    out.append(f"- human reply on `{t.get('path')}:{t.get('line') or '?'}` "
                               f"({state}): {first_line(humans[-1]['body'])}")
            for c in load(folder, f"pr_comments-{m}.json", []):
                if not is_bot(c):
                    out.append(f"- human conversation comment · "
                               f"{(c.get('user') or {}).get('login')}: {first_line(c.get('body'))}")
            for c in load(folder, f"commits-{m}.json", []):
                author = c["commit"]["author"] or {}
                if author.get("email") != BOT_EMAIL:
                    out.append(f"- human commit `{c['sha'][:8]}` by {author.get('name')}: "
                               f"{c['commit']['message'].splitlines()[0][:120]}")
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------------------- packets


def build(station: str, raw: Path, out: Path) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    if station == "retro":
        metrics = load(raw, "metrics.json", {"summary": {}, "items": []})
        files["metrics.json"] = json.dumps(metrics, indent=2) + "\n"
        files["items.md"] = items_md(metrics, raw)
    else:
        issue = load(raw, "issue.json")
        if issue:
            files["issue.md"] = issue_md(issue, load(raw, "comments.json", []))
        pr = load(raw, "pr.json") if station != "triage" else None
        if pr:
            reviews = load(raw, "reviews.json", [])
            files["pr.md"] = pr_md(pr, reviews, load(raw, "threads.json", []),
                                   load(raw, "pr_comments.json", []))
        if station == "triage":
            files["related.md"] = related_md(issue["number"], load(raw, "open_issues.json", []),
                                             load(raw, "open_prs.json", []))
        if station == "review":
            if not pr:
                raise SystemExit("factory.context: review needs pr.json")
            diff = raw / "diff.patch"
            files["diff.md"] = diff_md(diff.read_text() if diff.exists() else "")
            delta = raw / "delta.patch"
            files["followup.md"] = followup_md(
                reviews, (pr.get("head") or {}).get("sha", ""),
                delta.read_text() if delta.exists() else None)
    for name, text in files.items():
        (out / name).write_text(text)
    return sorted(files)


def select(raw: Path) -> str:
    mine = factory_reviews(load(raw, "reviews.json", []))
    return (mine[-1].get("commit_id") or "") if mine else ""


def main(argv: list[str]) -> None:
    if len(argv) == 3 and argv[1] == "select":
        print(select(Path(argv[2])))
    elif len(argv) == 4 and argv[1] in ("triage", "spec", "implement", "review", "retro"):
        for name in build(argv[1], Path(argv[2]), Path(argv[3])):
            print(name)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
