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
| review    | issue.md, pr.md, diff.txt, followup.md       |
| retro     | metrics.json, items.md                       |

A page is curated for the model that reads it, which sees only the page and not this code, so
every page holds to the same few habits: it opens by saying what it is, and a page that gathers
other items says it is a snapshot of this run; it names a field unless the notation is
self-evident, as `#70` is; a missing value is printed as a named null rather than dropped, so
the shape never changes with the data; a list heading carries its count and its order; and every
human-authored body is fenced, so its Markdown is data inside the page rather than structure of
it. Judge a change here by reading the rendered
page as the station will, not by reading the code. `diff.txt` is the one file that is not a page:
the annotated diff alone, its tags defined once in the review skill.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RUN_MARK, REVIEW_MARK = "<!-- factory:run", "<!-- factory:review"
BOT_EMAIL = "factory@users.noreply.github.com"
HUNK_HEADER = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


# ----------------------------------------------------------------------------- pieces


def load(raw: Path, name: str, default=None):
    path = raw / name
    return json.loads(path.read_text()) if path.exists() else default


def strip(text: str | None) -> str:
    """Drop the hidden records and footers other factory runs left behind."""
    return re.sub(r"<!--.*?-->|<sub>.*?</sub>", "", text or "", flags=re.S).strip()


def fenced(text: str, lang: str) -> str:
    """`text` in a fenced block whose fence is longer than any backtick run inside it, so a code
    block in the text cannot close it early."""
    fence = "`" * max(3, max((len(m) for m in re.findall(r"`+", text)), default=0) + 1)
    return f"{fence}{lang}\n{text}\n{fence}"


def quote(text: str | None, empty: str = "_(no text)_") -> str:
    """A human-authored body as a fenced block, so its headings and any `### login` line it
    might forge are data inside the packet rather than structure of it."""
    body = strip(text)
    return fenced(body, "text") if body else empty


def first_line(text: str | None, width: int = 200) -> str:
    body = strip(text)
    line = (body.splitlines()[0] if body else "")[:width]
    return line + (" …" if len(body) > len(line) else "")


def is_bot(entry: dict) -> bool:
    return (entry.get("user") or {}).get("type") == "Bot"


def who(entry: dict) -> str:
    """`login (bot)` or `login (author_association: ROLE)`, so a station can tell a maintainer's
    word from a drive-by. GitHub reports NONE for a user with no relationship to the repository."""
    login = (entry.get("user") or {}).get("login")
    if is_bot(entry):
        return f"{login} (bot)"
    return f"{login} (author_association: {entry.get('author_association') or 'NONE'})"


def when(ts: str | None) -> str:
    """GitHub's timestamp as given. A missing field is named rather than left blank, so a header
    never reads as if a word fell out of it."""
    return ts or "(no timestamp)"


def annotate(patch: str) -> str:
    """Prefix each diff line with its side and number: `[OLD:n]` removed (LEFT n), `[NEW:n]`
    added (RIGHT n), `[OLD:n,NEW:m]` context (RIGHT m). Inline review comments cite these."""
    lines: list[str] = []
    old_line: int | None = None
    new_line: int | None = None
    for raw_line in patch.splitlines():
        # A multi-file diff starts each file with `diff --git`. Reset the counters there so the
        # file's `---` / `+++` headers pass through the not-in-hunk branch. Do not special-case
        # `---` / `+++` themselves: a deleted content line whose text begins with `-- ` is also
        # written as `--- ...` and must still be annotated when inside a hunk.
        if raw_line.startswith("diff --git ") or raw_line.startswith("Binary files "):
            old_line = None
            new_line = None
            lines.append(raw_line)
            continue
        header_match = HUNK_HEADER.match(raw_line)
        if header_match:
            old_line = int(header_match.group("old_start"))
            new_line = int(header_match.group("new_start"))
            lines.append(raw_line)
            continue
        # Outside a hunk, or the `\ No newline at end of file` marker: pass through unchanged.
        if old_line is None or new_line is None or raw_line.startswith("\\"):
            lines.append(raw_line)
            continue
        marker = raw_line[:1]
        text = raw_line[1:]
        if marker == "-":
            lines.append(f"[OLD:{old_line}] {text}")
            old_line += 1
        elif marker == "+":
            lines.append(f"[NEW:{new_line}] {text}")
            new_line += 1
        elif marker == " ":
            lines.append(f"[OLD:{old_line},NEW:{new_line}] {text}")
            old_line += 1
            new_line += 1
        else:
            lines.append(raw_line)
    return "\n".join(lines)


def factory_reviews(reviews: list[dict]) -> list[dict]:
    """The factory's own reviews, oldest first. A reply the implementer posts inside a thread also
    shows up as an empty review; the hidden record is what marks a real one."""
    mine = [r for r in reviews if is_bot(r) and REVIEW_MARK in (r.get("body") or "")]
    return sorted(mine, key=lambda r: (r.get("submitted_at") or "", r.get("id") or 0))


def verdict_of(review: dict) -> str:
    """A review's verdict in plain words. The factory posts every review as a comment, since
    GitHub refuses approve or request-changes from a PR's author, so its real verdict lives in
    the hidden record; a human's verdict is the review state."""
    m = re.search(re.escape(REVIEW_MARK) + r" (\{.*?\}) -->", review.get("body") or "")
    if m:
        try:
            recorded = json.loads(m.group(1)).get("verdict")
        except json.JSONDecodeError:
            recorded = None
        if recorded:
            return recorded.replace("_", " ")
    return (review.get("state") or "unknown").lower().replace("_", " ")


# ----------------------------------------------------------------------------- files


def issue_md(issue: dict, comments: list[dict]) -> str:
    """The issue as it stands at this run: header, body, then every comment oldest first, with
    the factory's own run records marked so they are not mistaken for a person's words."""
    labels = ", ".join(f"`{lb['name']}`" for lb in issue.get("labels") or []) or "none"
    out = [f"# Issue #{issue['number']}: {issue['title']}",
           f"Opened by {who(issue)} on {when(issue.get('created_at'))} · state: "
           f"{issue.get('state')} · labels: {labels}", "",
           quote(issue.get("body"), "_(no body)_"),
           "", f"## Comments ({len(comments)}, oldest first)"]
    for c in comments:
        kind = " · factory run record" if RUN_MARK in (c.get("body") or "") else ""
        out += ["", f"### {who(c)}{kind} · {when(c.get('created_at'))}", "", quote(c.get("body"))]
    if not comments:
        out.append("_(none)_")
    return "\n".join(out) + "\n"


def related_md(n: int, issues: list[dict], prs: list[dict]) -> str:
    """Triage's view of the other open work: every open issue except this one, and every open
    PR, one line each, so duplicates and dependencies can be judged before reading further."""
    others = [i for i in issues if i["number"] != n]
    out = ["# Other open work in this repository",
           f"Every open issue except #{n}, and every open pull request, one line each, as of "
           "this run. Spot duplicates, dependencies, and nearby in-flight work here; read an "
           "item in full with `gh issue view <n>` or `gh pr view <n>` only when it matters.",
           "", f"## Open issues ({len(others)})"]
    for i in others:
        labels = ", ".join(f"`{lb['name']}`" for lb in i.get("labels") or []) or "none"
        out.append(f"- #{i['number']}: {i['title']} · labels: {labels}")
    if not others:
        out.append("_(none)_")
    out += ["", f"## Open pull requests ({len(prs)})"]
    out += [f"- #{p['number']}: {p['title']} · branch: {p.get('headRefName') or 'unknown'}"
            for p in prs] or ["_(none)_"]
    return "\n".join(out) + "\n"


def threads_md(threads: list[dict]) -> list[str]:
    """Open threads first and in full, each naming the thread id to resolve and the comment id
    to reply to; resolved threads after, one line each."""
    out: list[str] = []
    for t in sorted(threads, key=lambda t: (t["isResolved"], t.get("path") or "")):
        nodes = t["comments"]["nodes"]
        where = f"`{t.get('path')}:{t.get('line') or 'unknown'}`"
        if t["isResolved"]:
            gist = first_line(nodes[0]["body"], 100) if nodes else "_(no text)_"
            out.append(f"- {where} · resolved · first comment: {gist}")
            continue
        head = f"### {where} · open · thread id: `{t['id']}`"
        if nodes:
            head += f" · reply to comment id: `{nodes[0]['databaseId']}`"
        out += ["", head]
        for c in nodes:
            out += ["", f"**{login(c)}** · {when(c.get('createdAt'))}", "", quote(c["body"])]
    return out


def login(node: dict) -> str:
    """A thread comment's author; GraphQL returns null for a deleted account."""
    return (node.get("author") or {}).get("login") or "ghost"


def pr_md(pr: dict, reviews: list[dict], threads: list[dict], talk: list[dict]) -> str:
    """Everything said on a PR as it stands at this run: description, every review with a body,
    every thread, and the conversation. Open threads and human comments are what the next pass
    must answer."""
    head, base = pr.get("head") or {}, pr.get("base") or {}
    mergeable = {True: "yes", False: "CONFLICTS with base", None: "unknown"}[pr.get("mergeable")]
    out = [f"# PR #{pr['number']}: {pr.get('title', '')}",
           f"By {who(pr)} · head: `{head.get('ref')}` @ {(head.get('sha') or '')[:12]} → base: "
           f"`{base.get('ref')}` · state: {pr.get('state')} · draft: "
           f"{'yes' if pr.get('draft') else 'no'} · mergeable: {mergeable} · "
           f"{pr.get('html_url', '')}",
           "", "## Description", "", quote(pr.get("body"), "_(no description)_")]
    # A human's review counts even with no body: the verdict itself is the message. A bot's
    # bodyless review is the artifact of a reply posted inside a thread.
    spoken = sorted((r for r in reviews if strip(r.get("body")) or not is_bot(r)),
                    key=lambda r: r.get("submitted_at") or "")
    out += ["", f"## Reviews ({len(spoken)}, oldest first)", "",
            "A bar a human states here binds like the spec."]
    for r in spoken:
        out += ["", f"### {who(r)} · verdict: {verdict_of(r)} · at commit: "
                    f"{(r.get('commit_id') or '')[:12]} · {when(r.get('submitted_at'))}",
                "", quote(r.get("body"))]
    if not spoken:
        out.append("_(none)_")
    resolved = sum(1 for t in threads if t["isResolved"])
    out += ["", f"## Threads ({len(threads) - resolved} open, {resolved} resolved)", "",
            "Open threads are the worklist; whoever raised one closes it.", *threads_md(threads)]
    if not threads:
        out.append("_(none)_")
    talk = sorted(talk, key=lambda c: c.get("created_at") or "")
    out += ["", f"## Conversation ({len(talk)}, oldest first)", "",
            "A human's note here belongs to no line; an unanswered one is a finding."]
    for c in talk:
        out += ["", f"### {who(c)} · {when(c.get('created_at'))}", "", quote(c.get("body"))]
    if not talk:
        out.append("_(none)_")
    return "\n".join(out) + "\n"


def diff_txt(patch: str) -> str:
    """The PR's full diff against its base, annotated, as plain text. Not a page: it carries no
    header or fence, because the review skill defines the tags and a fence would break on a diff
    that itself contains one."""
    return (annotate(patch) if patch.strip() else "(empty diff)") + "\n"


def followup_md(reviews: list[dict], head: str, delta: str | None) -> str:
    """The last factory review and what changed since it; `pr.md` carries the threads."""
    mine = factory_reviews(reviews)
    if not mine:
        return ("# Follow-up\nNo earlier factory review on this PR: this is the first review, so "
                "there is nothing to re-judge.\n")
    last = mine[-1]
    prev = last.get("commit_id") or ""
    out = [f"# Follow-up: the factory last reviewed this PR at {prev[:12]}",
           "Judge whether each earlier finding is fixed, still open, or declined with a reason; "
           "the threads are in pr.md. List the ids of threads you verified fixed in `resolve`.",
           "", f"## Last review · verdict: {verdict_of(last)} · "
           f"{when(last.get('submitted_at'))}", "",
           quote(last.get("body")),
           "", f"## Changes since {prev[:12]} (to {head[:12]})", ""]
    if prev == head or (delta is not None and not delta.strip()):
        out.append("_(no code changes since the last review)_")
    elif delta is None:
        out.append("_(delta unavailable; use diff.txt)_")
    else:
        out.append(fenced(annotate(delta), "diff"))
    return "\n".join(out) + "\n"


def items_md(metrics: dict, raw: Path) -> str:
    """The retro's record: per item, one line per factory run and one per human touch."""
    s = metrics.get("summary", {})
    items = metrics.get("items", [])
    money = lambda v: "n/a" if v is None else f"${v:.2f}"  # noqa: E731
    num = lambda v, unit="": "n/a" if v is None else f"{v}{unit}"  # noqa: E731
    out = ["# The record",
           f"Every item the factory touched in the last {metrics.get('since_days', '?')} days: "
           "per item, one line per factory run and one per human touch, oldest first. A factory "
           "line is what the run said; a human line is what a person had to add, correct, or "
           "decide.", "",
           "", f"## Summary · items: {s.get('items', 0)} · shipped: {s.get('shipped', 0)} · total "
           f"cost: {money(s.get('total_cost_usd'))}"]
    if s.get("shipped"):
        out += ["", "Per shipped item, averages over the items that shipped:",
                f"- cost: {money(s.get('cost_per_shipped_usd'))} · the North Star metric",
                f"- factory time: {num(s.get('factory_minutes_per_shipped'), 'm')} · minutes the "
                "stations ran on the item, across all its runs",
                f"- runs: {num(s.get('runs_per_shipped'))} station runs on the item · three is the "
                "floor (triage, implement, review); spec and send-backs add",
                f"- steers: {num(s.get('steers_per_shipped'))} human Request-changes reviews and "
                "commits",
                f"- needs-human: {num(s.get('needs_human_per_shipped'))} · share that got stuck: "
                "a station was blocked or the review cap was hit",
                "", "Across shipped items:",
                f"- autonomy: {num(s.get('autonomy_pct'), '%')} shipped with no human steer"]
    else:
        out += ["", "Nothing shipped yet, so no per-shipped figures."]
    if not items:
        out += ["", "_(no items in the window)_"]
    for item in items:
        n = item["issue"]
        folder = raw / "items" / str(n)
        state = "shipped" if item.get("shipped") else "parked" if item.get("parked") else "open"
        out += ["", f"## Issue #{n} · state: {state} · cost: {money(item.get('cost_usd', 0))} · "
                    f"runs: {item.get('runs', 0)} · factory time: "
                    f"{item.get('factory_minutes', 0)}m · steers: {item.get('steers', 0)} · "
                    f"needs-human: {'yes' if item.get('needs_human') else 'no'}"]
        for c in load(folder, "comments.json", []):
            record = is_bot(c) or RUN_MARK in (c.get("body") or "")
            author = (c.get("user") or {}).get("login")
            label = "factory run" if record else f"human comment · {author}"
            out.append(f"- {label} · {when(c.get('created_at'))}: {first_line(c.get('body'))}")
        for m in item.get("prs") or []:
            out += ["", f"### PR #{m}"]
            touches = []
            for r in load(folder, f"reviews-{m}.json", []):
                if not is_bot(r) and strip(r.get("body")):
                    touches.append(f"- human review · verdict: {verdict_of(r)} · "
                                   f"{(r.get('user') or {}).get('login')} · "
                                   f"{when(r.get('submitted_at'))}: {first_line(r['body'])}")
            for t in load(folder, f"threads-{m}.json", []):
                humans = [c for c in t["comments"]["nodes"] if login(c) != "github-actions"]
                if humans:
                    state = "resolved" if t["isResolved"] else "open"
                    where = f"`{t.get('path')}:{t.get('line') or 'unknown'}`"
                    n = len(humans)
                    count = f"{n} human comment{'s' if n != 1 else ''}"
                    first = humans[0]
                    touches.append(f"- human thread on {where} ({state} · {count}) · "
                                   f"{login(first)} · {when(first.get('createdAt'))}: "
                                   f"{first_line(first['body'])}")
            for c in load(folder, f"pr_comments-{m}.json", []):
                if not is_bot(c):
                    touches.append(f"- human conversation comment · "
                                   f"{(c.get('user') or {}).get('login')} · "
                                   f"{when(c.get('created_at'))}: {first_line(c.get('body'))}")
            for c in load(folder, f"commits-{m}.json", []):
                author = c["commit"]["author"] or {}
                if author.get("email") != BOT_EMAIL:
                    touches.append(f"- human commit `{c['sha'][:8]}` by {author.get('name')}: "
                                   f"{first_line(c['commit']['message'])}")
            out += touches or ["_(no human touches)_"]
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
            files["diff.txt"] = diff_txt(diff.read_text() if diff.exists() else "")
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
