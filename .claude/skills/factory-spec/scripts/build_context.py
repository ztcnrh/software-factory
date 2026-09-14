#!/usr/bin/env python3
"""Build the spec packet: `issue.md`, and `review.md` when the spec PR exists (a revision).

    build_context.py <raw-dir> <out-dir>

Reads `issue.json` and `comments.json`; when present, `pr.json`, `reviews.json` (REST),
`threads.json` (GraphQL reviewThreads nodes), and `pr_comments.json` (the PR's conversation).
No network access.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


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


def threads_md(threads: list[dict]) -> list[str]:
    """Open threads in full (each is a worklist item), resolved ones as one line."""
    out: list[str] = []
    for t in sorted(threads, key=lambda t: (t["isResolved"], t.get("path") or "")):
        nodes = t["comments"]["nodes"]
        where = f"`{t.get('path')}:{t.get('line') or '?'}`"
        if t["isResolved"]:
            first = strip(nodes[0]["body"]).splitlines()[0] if nodes else ""
            out.append(f"- {where} · resolved · {first[:100]}")
            continue
        out += ["", f"### {where} · open · thread `{t['id']}` · reply to comment "
                    f"`{nodes[0]['databaseId']}`" if nodes else f"### {where} · open"]
        for c in nodes:
            out += ["", f"**{c['author']['login']}** · {when(c.get('createdAt'))}", "",
                    strip(c["body"])]
    return out


def review_md(pr: dict, reviews: list[dict], threads: list[dict], talk: list[dict]) -> str:
    head = (pr.get("head") or {}).get("sha", "")
    out = [f"# PR #{pr['number']}: {pr.get('title', '')}",
           f"`{(pr.get('head') or {}).get('ref')}` at {head[:12]} → "
           f"`{(pr.get('base') or {}).get('ref')}` · {pr.get('html_url', '')}", "",
           "Everything said on the PR so far. Open threads and human comments are the worklist; "
           "answer each in place."]
    spoken = [r for r in reviews if strip(r.get("body"))]
    if spoken:
        out += ["", "## Reviews"]
        for r in sorted(spoken, key=lambda r: r.get("submitted_at") or ""):
            out += ["", f"### {who(r)} · {r.get('state', '').lower().replace('_', ' ')} · at "
                        f"{(r.get('commit_id') or '')[:12]} · {when(r.get('submitted_at'))}", "",
                    strip(r["body"])]
    if threads:
        out += ["", "## Threads", *threads_md(threads)]
    if talk:
        out += ["", "## Conversation"]
        for c in sorted(talk, key=lambda c: c.get("created_at") or ""):
            out += ["", f"### {who(c)} · {when(c.get('created_at'))}", "", strip(c.get("body"))]
    return "\n".join(out) + "\n"


def main(raw: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "issue.md").write_text(issue_md(load(raw, "issue.json"), load(raw, "comments.json", [])))
    if pr := load(raw, "pr.json"):
        (out / "review.md").write_text(review_md(
            pr, load(raw, "reviews.json", []), load(raw, "threads.json", []),
            load(raw, "pr_comments.json", [])))
    print("\n".join(str(p) for p in sorted(out.iterdir())))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
