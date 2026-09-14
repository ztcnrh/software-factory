#!/usr/bin/env python3
"""Build the review packet: `issue.md`, `pr.md`, `diff.md`, and `followup.md`.

    build_context.py select <raw-dir>            print the head the last factory review saw
    build_context.py build  <raw-dir> <out-dir>  write the packet

Reads `issue.json`, `comments.json`, `pr.json`, `reviews.json` (REST), `threads.json` (GraphQL
reviewThreads nodes), `pr_comments.json` (the PR's conversation), `diff.patch` (the whole PR),
and `delta.patch` (the compare from the last factory review's head to this one, fetched by the
caller after `select`). No network access.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from annotate_diff import annotate

REVIEW_MARK = "<!-- factory:review"


def load(raw: Path, name: str, default=None):
    path = raw / name
    return json.loads(path.read_text()) if path.exists() else default


def strip(text: str | None) -> str:
    """Drop hidden records and footers other factory runs left behind."""
    return re.sub(r"<!--.*?-->|<sub>.*?</sub>", "", text or "", flags=re.S).strip()


def who(entry: dict) -> str:
    user = entry.get("user") or {}
    if user.get("type") == "Bot":
        return f"{user.get('login')} (bot)"
    return f"{user.get('login')} ({entry.get('author_association', 'NONE')})"


def when(ts: str | None) -> str:
    return (ts or "")[:16].replace("T", " ")


def issue_md(issue: dict, comments: list[dict]) -> str:
    labels = ", ".join(lb["name"] for lb in issue.get("labels") or []) or "none"
    out = [
        f"# Issue #{issue['number']}: {issue['title']}",
        f"Opened by {who(issue)} on {when(issue.get('created_at'))} · state {issue.get('state')}"
        f" · labels: {labels}",
        "",
        strip(issue.get("body")) or "_(no body)_",
    ]
    if comments:
        out += ["", "## Comments"]
        for c in comments:
            out += ["", f"### {who(c)} · {when(c.get('created_at'))}", "", strip(c.get("body"))]
    return "\n".join(out) + "\n"


def factory_reviews(reviews: list[dict]) -> list[dict]:
    """The factory's own reviews, oldest first. A reply the implementer posted inside a thread
    also shows up as an empty review; the hidden record is what marks a real review."""
    mine = [r for r in reviews
            if (r.get("user") or {}).get("type") == "Bot" and REVIEW_MARK in (r.get("body") or "")]
    return sorted(mine, key=lambda r: (r.get("submitted_at") or "", r.get("id") or 0))


def pr_md(pr: dict, reviews: list[dict], talk: list[dict]) -> str:
    head, base = pr.get("head") or {}, pr.get("base") or {}
    out = [f"# PR #{pr['number']}: {pr.get('title', '')}",
           f"By {who(pr)} · `{head.get('ref')}` at {(head.get('sha') or '')[:12]} → "
           f"`{base.get('ref')}`{' · draft' if pr.get('draft') else ''} · {pr.get('html_url', '')}",
           "", "## Description", "", strip(pr.get("body")) or "_(no description)_"]
    humans = [r for r in reviews
              if (r.get("user") or {}).get("type") != "Bot" and strip(r.get("body"))]
    if humans:
        out += ["", "## Human reviews", "",
                "A bar stated here binds like the spec. Check the change meets it."]
        for r in sorted(humans, key=lambda r: r.get("submitted_at") or ""):
            out += ["", f"### {who(r)} · {r.get('state', '').lower().replace('_', ' ')} · "
                        f"{when(r.get('submitted_at'))}", "", strip(r["body"])]
    if talk:
        out += ["", "## Conversation", "",
                "A human's unanchored note belongs to no line; an unanswered one is a finding."]
        for c in sorted(talk, key=lambda c: c.get("created_at") or ""):
            out += ["", f"### {who(c)} · {when(c.get('created_at'))}", "", strip(c.get("body"))]
    return "\n".join(out) + "\n"


def threads_md(threads: list[dict]) -> list[str]:
    out: list[str] = []
    for t in sorted(threads, key=lambda t: (t["isResolved"], t.get("path") or "")):
        nodes = t["comments"]["nodes"]
        state = "resolved" if t["isResolved"] else "open"
        out += ["", f"### `{t.get('path')}:{t.get('line') or '?'}` · {state} · thread `{t['id']}`"]
        for c in nodes:
            out += ["", f"**{c['author']['login']}** · {when(c.get('createdAt'))}", "",
                    strip(c["body"])]
    return out


def followup_md(reviews: list[dict], threads: list[dict], head: str,
                delta: str | None) -> str:
    mine = factory_reviews(reviews)
    if not mine:
        return "No earlier factory review on this PR: this is the first review.\n"
    last = mine[-1]
    prev = last.get("commit_id") or ""
    out = [f"# Follow-up: the factory last reviewed this PR at {prev[:12]}", "",
           "Judge whether each earlier finding is fixed, still open, or declined with a reason. "
           "List the ids of threads you verified fixed in `resolve`.", "",
           f"## Last review · {when(last.get('submitted_at'))}", "", strip(last.get("body"))]
    if threads:
        out += ["", "## Threads", *threads_md(threads)]
    out += ["", f"## Changes since {prev[:12]} (to {head[:12]})", ""]
    if prev == head:
        out.append("No code changes since the last review.")
    elif delta is None:
        out.append("Delta unavailable; use diff.md.")
    elif not delta.strip():
        out.append("No code changes since the last review.")
    else:
        out += ["```diff", annotate(delta), "```"]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> None:
    if len(argv) == 3 and argv[1] == "select":
        mine = factory_reviews(load(Path(argv[2]), "reviews.json", []))
        print(mine[-1].get("commit_id") or "" if mine else "")
        return
    if len(argv) != 4 or argv[1] != "build":
        raise SystemExit(__doc__)
    raw, out = Path(argv[2]), Path(argv[3])
    out.mkdir(parents=True, exist_ok=True)
    pr = load(raw, "pr.json")
    reviews = load(raw, "reviews.json", [])
    if issue := load(raw, "issue.json"):
        (out / "issue.md").write_text(issue_md(issue, load(raw, "comments.json", [])))
    (out / "pr.md").write_text(pr_md(pr, reviews, load(raw, "pr_comments.json", [])))
    diff = (raw / "diff.patch").read_text() if (raw / "diff.patch").exists() else ""
    (out / "diff.md").write_text(
        "# Annotated diff\n\n`[OLD:n]` removed (LEFT n) · `[NEW:n]` added (RIGHT n) · "
        "`[OLD:n,NEW:m]` context (RIGHT m). Copy path, side, and line from here for every "
        "inline comment.\n\n```diff\n" + annotate(diff) + "\n```\n")
    delta_path = raw / "delta.patch"
    (out / "followup.md").write_text(followup_md(
        reviews, load(raw, "threads.json", []), (pr.get("head") or {}).get("sha", ""),
        delta_path.read_text() if delta_path.exists() else None))
    print("\n".join(str(p) for p in sorted(out.iterdir())))


if __name__ == "__main__":
    main(sys.argv)
