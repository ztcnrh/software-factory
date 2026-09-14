#!/usr/bin/env python3
"""Build the retro packet: `metrics.json` and `items.md`, the record of every human touch.

    build_context.py <raw-dir> <out-dir>

Reads `metrics.json` (the output of `factory metrics --json`) and, per item,
`items/<n>/comments.json` plus, per PR `<m>` of that item, `items/<n>/reviews-<m>.json`,
`items/<n>/threads-<m>.json`, `items/<n>/pr_comments-<m>.json`, `items/<n>/commits-<m>.json`.
No network access.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BOT_EMAIL = "factory@users.noreply.github.com"


def load(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def strip(text: str | None) -> str:
    return re.sub(r"<!--.*?-->|<sub>.*?</sub>", "", text or "", flags=re.S).strip()


def is_bot(entry: dict) -> bool:
    return (entry.get("user") or {}).get("type") == "Bot"


def when(ts: str | None) -> str:
    return (ts or "")[:16].replace("T", " ")


def item_md(item: dict, folder: Path) -> list[str]:
    n = item["issue"]
    state = "shipped" if item.get("shipped") else "parked" if item.get("parked") else "open"
    flag = " · needs-human" if item.get("needs_human") else ""
    out = [f"## #{n} · {state} · ${item.get('cost_usd', 0):.2f} · {item.get('runs', 0)} runs · "
           f"{item.get('steers', 0)} steers{flag}"]
    factory_lines, human_comments = [], []
    for c in load(folder / "comments.json", []):
        body = strip(c.get("body"))
        if is_bot(c):
            factory_lines.append(body.splitlines()[0] if body else "")
        else:
            human_comments.append(c)
    if factory_lines:
        out += ["", "Factory runs, one line each:", *[f"- {line}" for line in factory_lines]]
    if human_comments:
        out += ["", "Human comments on the issue:"]
        for c in human_comments:
            out += [f"- {(c.get('user') or {}).get('login')} · {when(c.get('created_at'))}: "
                    f"{body_line(c)}"]
    for m in item.get("prs") or []:
        out += ["", f"### PR #{m}"]
        for r in load(folder / f"reviews-{m}.json", []):
            if is_bot(r) or not strip(r.get("body")):
                continue
            out += [f"- human review · {r.get('state', '').lower().replace('_', ' ')} · "
                    f"{(r.get('user') or {}).get('login')}: {body_line(r)}"]
        for t in load(folder / f"threads-{m}.json", []):
            nodes = t["comments"]["nodes"]
            humans = [c for c in nodes[1:] if c["author"]["login"] != "github-actions"]
            if humans:
                out += [f"- human reply on `{t.get('path')}:{t.get('line') or '?'}` "
                        f"({'resolved' if t['isResolved'] else 'open'}): "
                        f"{strip(humans[-1]['body']).splitlines()[0][:200]}"]
        for c in load(folder / f"pr_comments-{m}.json", []):
            if not is_bot(c):
                out += [f"- human conversation comment · {(c.get('user') or {}).get('login')}: "
                        f"{body_line(c)}"]
        for c in load(folder / f"commits-{m}.json", []):
            author = c["commit"]["author"] or {}
            if author.get("email") != BOT_EMAIL:
                out += [f"- human commit `{c['sha'][:8]}` by {author.get('name')}: "
                        f"{c['commit']['message'].splitlines()[0][:120]}"]
    return out


def body_line(entry: dict) -> str:
    body = strip(entry.get("body"))
    return (body.splitlines()[0][:200] + (" …" if len(body) > 200 else "")) if body else ""


def main(raw: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    metrics = load(raw / "metrics.json", {"summary": {}, "items": []})
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    s = metrics.get("summary", {})
    lines = ["# The record", "",
             f"{s.get('items', 0)} items · {s.get('shipped', 0)} shipped · cost per shipped item "
             f"${s.get('cost_per_shipped_usd')} · {s.get('steers_per_shipped')} steers per "
             f"shipped · {s.get('needs_human', 0)} needs-human", "",
             "Every human touch, per item. A factory line is what the run said; a human line is "
             "what a person had to add, correct, or decide."]
    for item in metrics.get("items", []):
        lines += ["", *item_md(item, raw / "items" / str(item["issue"]))]
    (out / "items.md").write_text("\n".join(lines) + "\n")
    print("\n".join(str(p) for p in sorted(out.iterdir())))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
