"""The read side of "the pull request is the review surface".

``factory feedback <id>`` prints, verbatim, what people said on a work item's
pull requests: unresolved inline review threads, conversation comments, and
review summaries. Threads filter on *unresolved* because resolution is the
done-signal — whoever raised a thread resolves it when satisfied, and until
then it stays in every station's view; no bookkeeping field can drift from
that. Comments the factory itself posts end with an invisible
``<!-- factory:<station> -->`` marker and are labeled here, so a station never
mistakes its own output for a human's words. Nothing is filtered out or
summarized: the engine packages, the reader interprets.
"""

from __future__ import annotations

import json
import re

from .adapters import github
from .model import WorkItem

# Machine-posted bodies end with this (invisible in the GitHub UI). Anchored to
# the end on purpose: a human quote-replying to a machine post carries the marker
# mid-body, and mislabeling their words as machine chatter is the failure that
# would eat a real send-back.
MARKER_RE = re.compile(r"<!--\s*factory:([a-z-]+)\s*-->\s*$")

# Module-level seam: every gh invocation goes through this name so tests can
# stub the one place the network is touched.
_gh = github._run

_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      title
      url
      reviewThreads(first: 100) {
        pageInfo { hasNextPage }
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first: 50) {
            pageInfo { hasNextPage }
            nodes { author { login } body createdAt }
          }
        }
      }
    }
  }
}
"""


def pr_numbers(item: WorkItem) -> tuple[list[str], list[str]]:
    """``(numbers, unparseable_refs)``: every PR recorded on the item as a bare
    number, feature PR first, no duplicates. Accepts the forms stations actually
    record — ``#58``, ``58``, or a URL (matched on its ``/pull/N`` segment, so a
    ``/files`` suffix or a ``#discussion_…`` fragment can't shift the number). A
    ref that parses as nothing is returned, not dropped: the caller must report
    it, because a recorded PR silently skipped reads as "no feedback"."""
    out: list[str] = []
    bad: list[str] = []
    for ref in [item.pr, *(cp.pr for cp in item.change_passes)]:
        if not ref:
            continue
        text = str(ref).strip()
        m = re.search(r"/pull/(\d+)", text) if "/" in text else re.fullmatch(r"#?(\d+)", text)
        if m is None:
            bad.append(text)
        elif m.group(1) not in out:
            out.append(m.group(1))
    return out, bad


def author_label(login: str, body: str) -> str:
    """How a comment is attributed in the render: the marker outranks the
    login, because station posts go out under the operator's own token —
    the author field can't tell a machine from its human."""
    m = MARKER_RE.search(body or "")
    return f"{login} [factory:{m.group(1)}]" if m else login


def repo_slug() -> tuple[int, str]:
    rc, out, err = _gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    return rc, (out.strip() if rc == 0 else (err.strip() or out.strip()))


def _paginated(path: str) -> tuple[int, list[dict], str]:
    """A REST list endpoint, all pages. ``--slurp`` wraps each page's array in
    an outer array (concatenated bare arrays wouldn't parse as one document),
    so flattening one level yields the full list."""
    rc, out, err = _gh(["api", path, "--paginate", "--slurp"])
    if rc != 0:
        return rc, [], (err.strip() or out.strip())
    try:
        return 0, [row for page in json.loads(out or "[]") for row in page], ""
    except (json.JSONDecodeError, TypeError):
        return 1, [], f"unparseable gh output: {out[:200]!r}"


def fetch_pr(slug: str, number: str) -> tuple[dict | None, str]:
    """Everything said on one PR: ``(data, "")`` or ``(None, why)``. One
    failing call fails the PR — a partial picture presented as whole would
    read as feedback that isn't there."""
    owner, name = slug.split("/", 1)
    rc, out, err = _gh(
        [
            "api", "graphql",
            "-f", f"query={_THREADS_QUERY}",
            # -f, not -F, for the two strings: -F magic-coerces an all-numeric
            # owner/repo name to an Int and the String! variables reject it.
            "-f", f"owner={owner}",
            "-f", f"name={name}",
            "-F", f"number={number}",
        ]
    )
    if rc != 0:
        return None, (err.strip() or out.strip())
    try:
        pr = json.loads(out)["data"]["repository"]["pullRequest"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None, f"unparseable graphql output: {out[:200]!r}"
    if pr is None:
        return None, f"PR #{number} not found in {slug}"
    threads = pr.get("reviewThreads") or {}
    rc, comments, why = _paginated(f"repos/{slug}/issues/{number}/comments")
    if rc != 0:
        return None, why
    rc, reviews, why = _paginated(f"repos/{slug}/pulls/{number}/reviews")
    if rc != 0:
        return None, why
    return {
        "number": number,
        "title": pr.get("title") or "",
        "url": pr.get("url") or "",
        "threads": [t for t in threads.get("nodes") or [] if t and not t.get("isResolved")],
        "threads_truncated": bool((threads.get("pageInfo") or {}).get("hasNextPage")),
        "comments": comments,
        "reviews": [r for r in reviews if (r.get("body") or "").strip()],
    }, ""


def render(item_id: str, prs: list[dict], failures: list[tuple[str, str]]) -> str:
    """The verbatim packet. Failures render inline and loudly: feedback on a
    PR we couldn't read is unknown, not absent, and a station must see the
    difference."""
    lines = [f"# PR feedback — {item_id}", ""]
    for number, why in failures:
        lines += [f"⚠ couldn't fetch PR #{number} ({why}) — feedback there is unknown, not absent."]
    if failures:
        lines.append("")
    for pr in prs:
        lines += [f"## PR #{pr['number']} — {pr['title']} ({pr['url']})", ""]
        threads = pr["threads"]
        if pr["threads_truncated"]:
            lines += ["⚠ more than 100 review threads — only the first 100 are shown.", ""]
        lines.append(f"### Unresolved review threads ({len(threads)})")
        for t in threads:
            where = f"{t.get('path')}:{t.get('line')}" if t.get("line") else str(t.get("path"))
            outdated = " · outdated (the line moved since)" if t.get("isOutdated") else ""
            lines += ["", f"**{where}** — thread `{t.get('id')}`{outdated}"]
            if ((t.get("comments") or {}).get("pageInfo") or {}).get("hasNextPage"):
                lines.append("⚠ thread longer than 50 comments — only the earliest 50 are shown.")
            for c in (t.get("comments") or {}).get("nodes") or []:
                login = (c.get("author") or {}).get("login") or "unknown"
                lines += [
                    "",
                    f"@{author_label(login, c.get('body') or '')} ({c.get('createdAt')}):",
                    c.get("body") or "",
                ]
        if not threads:
            lines += ["", "_(none)_"]
        if pr["reviews"]:
            lines += ["", "### Review summaries"]
            for r in pr["reviews"]:
                login = (r.get("user") or {}).get("login") or "unknown"
                lines += [
                    "",
                    f"@{author_label(login, r['body'])} ({r.get('state')}, "
                    f"{r.get('submitted_at')}):",
                    r["body"],
                ]
        if pr["comments"]:
            lines += ["", "### Conversation"]
            for c in pr["comments"]:
                login = (c.get("user") or {}).get("login") or "unknown"
                body = c.get("body") or ""
                lines += ["", f"@{author_label(login, body)} ({c.get('created_at')}):", body]
        lines.append("")
    lines += [
        "---",
        "Answer a thread in place: gh api graphql -f query='mutation($t:ID!,$b:String!)"
        "{addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$t,body:$b})"
        "{comment{url}}}' -F t=<thread-id> -f b='<reply>'",
        "Resolve one (only if you raised it): gh api graphql -f query='mutation($t:ID!)"
        "{resolveReviewThread(input:{threadId:$t}){thread{isResolved}}}' -F t=<thread-id>",
        "A `[factory:<station>]` label means a machine wrote it; everything else is a human.",
    ]
    return "\n".join(lines)
