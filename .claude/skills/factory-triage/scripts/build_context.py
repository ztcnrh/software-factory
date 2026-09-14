#!/usr/bin/env python3
"""Build the triage packet: `issue.md` and `related.md` from raw GitHub JSON.

    build_context.py <raw-dir> <out-dir>

Reads `issue.json` (the issue), `comments.json` (its comments), `open_issues.json` and
`open_prs.json` (what else is open in the repo). No network access.
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


def related_md(n: int, issues: list[dict], prs: list[dict]) -> str:
    out = ["# Open work in this repository", "",
           "One line each; judge duplicates and dependencies from here, then read what matters.",
           "", "## Issues"]
    others = [i for i in issues if i["number"] != n]
    out += [f"- #{i['number']} {i['title']}"
            + (f" [{', '.join(lb['name'] for lb in i.get('labels') or [])}]"
               if i.get("labels") else "") for i in others] or ["- none"]
    out += ["", "## Pull requests"]
    out += [f"- #{p['number']} {p['title']} (`{p.get('headRefName', '')}`)" for p in prs] or [
        "- none"]
    return "\n".join(out) + "\n"


def main(raw: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    issue = load(raw, "issue.json")
    (out / "issue.md").write_text(issue_md(issue, load(raw, "comments.json", [])))
    (out / "related.md").write_text(related_md(
        issue["number"], load(raw, "open_issues.json", []), load(raw, "open_prs.json", [])))
    print("\n".join(str(p) for p in sorted(out.iterdir())))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
