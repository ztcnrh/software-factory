"""The feedback packet: PR review threads and comments become station input."""

from pathlib import Path

from factory import feedback
from factory.adapters import github
from factory.cli import main
from factory.dispatch import Dispatcher
from factory.model import ChangePass, WorkItem


def _item(**kw) -> WorkItem:
    return WorkItem(id="WI-0001", title="t", **kw)


def test_pr_numbers_normalizes_every_recorded_form():
    """Stations record PRs as '#N', a bare number, or a URL — the fetch layer
    must land on the same bare number for all three, deduplicated."""
    item = _item(
        pr="#58",
        change_passes=[
            ChangePass(branch="a", pr="https://github.com/o/r/pull/58"),
            ChangePass(branch="b", pr="61"),
            ChangePass(branch="c", pr=None),
        ],
    )
    assert feedback.pr_numbers(item) == (["58", "61"], [])


def test_pr_numbers_reads_urls_by_their_pull_segment_and_reports_duds():
    """A '/files' suffix must not make a recorded URL vanish (silence reads as
    'no feedback'), and a '#discussion_r…' fragment must not shift the number —
    that would present another PR's feedback as this item's. URLs parse on
    '/pull/N' alone; a ref that parses as nothing comes back to be reported."""
    item = _item(
        pr="https://github.com/o/r/pull/58/files",
        change_passes=[
            ChangePass(branch="a", pr="https://github.com/o/r/pull/58#discussion_r123456"),
            ChangePass(branch="b", pr="feature/oops-a-branch"),
        ],
    )
    assert feedback.pr_numbers(item) == (["58"], ["feature/oops-a-branch"])


def test_author_label_flags_machine_posts():
    """Station posts go out under the operator's own token, so the login can't
    tell a machine from its human — only the body marker can."""
    assert feedback.author_label("tz", "fix this") == "tz"
    marked = "done\n<!-- factory:implement -->"
    assert feedback.author_label("tz", marked) == "tz [factory:implement]"


def test_author_label_keeps_a_quote_reply_human():
    """GitHub quote-replies copy raw markdown, marker included — a human answering
    under a quoted machine post must stay labeled human, or their send-back reads
    as machine chatter. Only a marker ending the body (where stations put it)
    may label."""
    quoted = "> done in abc123\n> <!-- factory:implement -->\n\nNo, this is still broken."
    assert feedback.author_label("tz", quoted) == "tz"


def test_render_is_verbatim_and_self_describing():
    """A station reads only this render: bodies must arrive untouched, threads
    must carry the id needed to reply/resolve, and machine posts must be
    labeled so a station never eats its own output as human feedback."""
    pr = {
        "number": "7",
        "title": "spec",
        "url": "https://x/pull/7",
        "threads": [
            {
                "id": "PRRT_abc",
                "isResolved": False,
                "isOutdated": True,
                "path": "specs/PRODUCT.md",
                "line": 12,
                "comments": {
                    "nodes": [
                        {"author": {"login": "tz"}, "body": "tighten *this*", "createdAt": "t1"},
                        {
                            "author": {"login": "tz"},
                            "body": "done in abc123\n<!-- factory:spec -->",
                            "createdAt": "t2",
                        },
                    ]
                },
            }
        ],
        "threads_truncated": False,
        "comments": [{"user": {"login": "tz"}, "body": "overall: solid", "created_at": "t3"}],
        "reviews": [],
    }
    out = feedback.render("WI-0001", [pr], failures=[])
    assert "specs/PRODUCT.md:12" in out and "PRRT_abc" in out and "outdated" in out
    assert "tighten *this*" in out  # verbatim, markdown intact
    assert "@tz [factory:spec]" in out and "overall: solid" in out
    assert "resolveReviewThread" in out  # the footer teaches reply/resolve in place


def test_render_marks_unfetchable_prs_loudly():
    """'Couldn't look' must never read as 'no feedback' — an unreadable PR is
    named in the packet itself, where the station will actually see it."""
    out = feedback.render("WI-0001", [], failures=[("9", "boom")])
    assert "couldn't fetch PR #9" in out and "unknown, not absent" in out


def test_fetch_pr_filters_resolved_threads_and_empty_reviews(monkeypatch):
    """Resolution is the done-signal: a resolved thread is finished business and
    must leave the packet, as must review rows with nothing said in them."""
    graphql = {
        "data": {
            "repository": {
                "pullRequest": {
                    "title": "t",
                    "url": "u",
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False},
                        "nodes": [
                            {"id": "a", "isResolved": True, "comments": {"nodes": []}},
                            {"id": "b", "isResolved": False, "comments": {"nodes": []}},
                        ],
                    },
                }
            }
        }
    }
    # REST pages arrive --slurp'ed: an array of per-page arrays.
    pages = {"issues": '[[{"body": "hi", "user": {"login": "tz"}}]]',
             "reviews": '[[{"body": ""}, {"body": "real", "user": {"login": "tz"}}]]'}

    def fake_gh(args):
        if args[1] == "graphql":
            import json
            return 0, json.dumps(graphql), ""
        return (0, pages["issues"], "") if "/issues/" in args[1] else (0, pages["reviews"], "")

    monkeypatch.setattr(feedback, "_gh", fake_gh)
    data, why = feedback.fetch_pr("o/r", "7")
    assert why == ""
    assert [t["id"] for t in data["threads"]] == ["b"]
    assert [r["body"] for r in data["reviews"]] == ["real"]
    assert data["comments"][0]["body"] == "hi"


def test_fetch_pr_reports_a_missing_pr_plainly(monkeypatch):
    """A deleted or nonexistent PR must be named plainly — reporting it as
    'unparseable graphql output' would be a lie about output that parsed fine."""
    import json

    payload = json.dumps({"data": {"repository": {"pullRequest": None}}})
    monkeypatch.setattr(feedback, "_gh", lambda a: (0, payload, ""))
    data, why = feedback.fetch_pr("o/r", "7")
    assert data is None and why == "PR #7 not found in o/r"


def test_paginated_flattens_multiple_slurped_pages(monkeypatch):
    """--slurp wraps each page's array in an outer array; two pages must come
    back as one flat list or everything past page one silently disappears."""
    monkeypatch.setattr(feedback, "_gh", lambda a: (0, '[[{"n": 1}], [{"n": 2}]]', ""))
    rc, rows, why = feedback._paginated("repos/o/r/issues/7/comments")
    assert (rc, why) == (0, "") and [r["n"] for r in rows] == [1, 2]


def test_feedback_without_prs_is_a_clean_noop(factory_root: Path, monkeypatch):
    """An item that never opened a PR (no remote, early states) must answer
    calmly with rc 0 and never touch the network — feedback is optional plumbing,
    not a dependency."""
    calls = []
    monkeypatch.setattr(feedback, "_gh", lambda a: calls.append(a) or (1, "", "no"))
    main(["--root", str(factory_root), "new", "quiet item"])
    item_id = Dispatcher(factory_root).store.list_items()[0].id
    assert main(["--root", str(factory_root), "feedback", item_id]) == 0
    assert calls == []


def test_feedback_partial_failure_stays_usable(factory_root, monkeypatch, capsys):
    """One readable PR plus one unreadable must exit 0 with the failure named
    loudly in the packet — rc 1 would make a station distrust the good half,
    and a silent skip would make the bad half read as 'no feedback'."""
    main(["--root", str(factory_root), "new", "two prs"])
    d = Dispatcher(factory_root)
    item = d.store.list_items()[0]
    item.pr = "#7"
    item.open_change_pass(branch="c", pr="#9")
    d.store.save(item)
    ok = {"number": "7", "title": "t", "url": "u", "threads": [],
          "threads_truncated": False, "comments": [], "reviews": []}
    monkeypatch.setattr(github, "available", lambda: True)
    monkeypatch.setattr(feedback, "repo_slug", lambda: (0, "o/r"))
    monkeypatch.setattr(
        feedback, "fetch_pr", lambda slug, n: (ok, "") if n == "7" else (None, "api down")
    )
    assert main(["--root", str(factory_root), "feedback", item.id]) == 0
    out = capsys.readouterr().out
    assert "couldn't fetch PR #9" in out and "PR #7" in out


def test_feedback_distinguishes_cannot_look_from_nothing_there(factory_root, monkeypatch, capsys):
    """When every fetch fails, exiting 0 would let a station mistake an outage
    for an empty review — the command must fail loudly instead."""
    main(["--root", str(factory_root), "new", "item with pr"])
    d = Dispatcher(factory_root)
    item = d.store.list_items()[0]
    item.pr = "#7"
    d.store.save(item)
    monkeypatch.setattr(github, "available", lambda: True)
    monkeypatch.setattr(feedback, "repo_slug", lambda: (0, "o/r"))
    monkeypatch.setattr(feedback, "fetch_pr", lambda slug, n: (None, "api down"))
    assert main(["--root", str(factory_root), "feedback", item.id]) == 1
    err = capsys.readouterr().err
    assert "unknown, not absent" in err
