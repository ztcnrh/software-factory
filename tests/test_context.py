"""Tests for the packet builder, on raw JSON captured from the sandbox (issue #6 and its PR #13:
a needs-info round, one send-back with a thread and a reply, an approval)."""

import json
import shutil
from pathlib import Path

import pytest

from factory import context

FIXTURES = Path(__file__).resolve().parent / "fixtures"

HUMAN_NOTE = [{"user": {"login": "tianchi-fetch", "type": "User"}, "author_association": "OWNER",
               "created_at": "2026-09-13T15:30:00Z", "body": "Keep the error wording as is."}]


@pytest.fixture
def raw(tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "raw")
    return tmp_path / "raw"


def test_triage_packet_renders_the_thread_and_the_open_work(raw, tmp_path):
    """Triage reads the whole issue thread with who said what, minus the hidden records other
    runs left, and a one-line list of the other open work to spot duplicates."""
    assert context.build("triage", raw, tmp_path / "out") == ["issue.md", "related.md"]
    issue = (tmp_path / "out" / "issue.md").read_text()
    assert issue.startswith(
        "# Issue #6: tally total is wrong\nOpened by tianchi-fetch (author_association: OWNER)")
    assert ("### tianchi-fetch (author_association: OWNER) · factory run record · "
            "2026-09-13T03:16:18Z") in issue
    assert "### github-actions[bot] (bot)" in issue
    assert "<!--" not in issue
    related = (tmp_path / "out" / "related.md").read_text()
    assert ("- #11: README's `uv run tally` fails: no [project.scripts] entry · labels: none"
            in related)
    assert "#6:" not in related and "Every open issue except #6," in related


def test_pr_packet_makes_open_threads_the_worklist(raw, tmp_path):
    """A loop-back needs every open thread with its replies and the comment id to reply to;
    resolved threads shrink to one line, and a human's conversation comment is included."""
    threads = json.loads((raw / "threads.json").read_text())
    threads.append({"id": "PRRT_open", "isResolved": False, "path": "README.md", "line": 4,
                    "comments": {"nodes": [
                        {"databaseId": 42, "author": {"login": "github-actions"},
                         "body": "💡 [SUGGESTION] mention the flag",
                         "createdAt": "2026-09-13T15:20:00Z"}]}})
    (raw / "threads.json").write_text(json.dumps(threads))
    (raw / "pr_comments.json").write_text(json.dumps(HUMAN_NOTE))
    assert context.build("implement", raw, tmp_path / "out") == ["issue.md", "pr.md"]
    pr = (tmp_path / "out" / "pr.md").read_text()
    assert pr.startswith("# PR #13: #6: tally total is wrong\nBy github-actions[bot] (bot)")
    assert "### `README.md:4` · open · thread id: `PRRT_open` · reply to comment id: `42`" in pr
    assert "- `src/tally/__init__.py:unknown` · resolved · first comment: ⚠️ [IMPORTANT]" in pr
    assert pr.index("· open ·") < pr.index("· resolved ·")
    assert "## Conversation" in pr and "Keep the error wording as is." in pr
    assert "## Reviews" in pr
    assert "### github-actions[bot] (bot) · verdict: commented · at commit: faf132cea76b" in pr


def test_pr_packet_keeps_a_bodyless_human_review_and_survives_a_deleted_author(raw, tmp_path):
    """A human who clicks Request changes and puts the words in inline comments still sent the
    PR back; the verdict must show. A thread whose author deleted their account renders too."""
    reviews = json.loads((raw / "reviews.json").read_text())
    reviews.append({"id": 1, "state": "CHANGES_REQUESTED", "body": "", "submitted_at":
                    "2026-09-13T16:00:00Z", "user": {"login": "tianchi-fetch", "type": "User"},
                    "author_association": "OWNER", "commit_id": "159c8292ab9e"})
    (raw / "reviews.json").write_text(json.dumps(reviews))
    threads = json.loads((raw / "threads.json").read_text())
    threads[0]["comments"]["nodes"][0]["author"] = None
    (raw / "threads.json").write_text(json.dumps(threads))
    context.build("implement", raw, tmp_path / "out")
    pr = (tmp_path / "out" / "pr.md").read_text()
    assert ("### tianchi-fetch (author_association: OWNER) · verdict: changes requested · "
            "at commit: 159c8292ab9e"
            in pr)
    assert "_(no text)_" in pr and "**ghost**" not in pr  # resolved threads fold to one line


def test_pr_packet_flags_a_conflict_with_the_base_branch(raw, tmp_path):
    """GitHub runs no PR events on a conflicted PR, so the packet has to say so: review turns
    it into a send-back and implement merges the base first."""
    pr = json.loads((raw / "pr.json").read_text())
    pr["mergeable"] = False
    (raw / "pr.json").write_text(json.dumps(pr))
    context.build("implement", raw, tmp_path / "out")
    assert ("→ base: `main` · state: closed · draft: no · mergeable: CONFLICTS with base · https://"
            in (tmp_path / "out" / "pr.md").read_text())
    pr["mergeable"] = None
    (raw / "pr.json").write_text(json.dumps(pr))
    context.build("implement", raw, tmp_path / "out2")
    assert "CONFLICTS" not in (tmp_path / "out2" / "pr.md").read_text()


def test_spec_packet_is_the_issue_alone_before_a_pr_exists(raw, tmp_path):
    """A first spec pass has nothing to revise; the packet is the issue alone."""
    for name in ("pr.json", "reviews.json", "threads.json"):
        (raw / name).unlink()
    assert context.build("spec", raw, tmp_path / "out") == ["issue.md"]


def test_select_names_the_last_factory_reviews_head(raw):
    """The delta is fetched from the head the factory last reviewed; the implementer's in-thread
    reply also appears as an empty review and must not be mistaken for one."""
    reviews = json.loads((raw / "reviews.json").read_text())
    assert [r["id"] for r in context.factory_reviews(reviews)] == [5191097557, 5191110281]
    assert context.select(raw) == "159c8292ab9e0dadd2b0bfd90473b83b0e8bc832"
    (raw / "reviews.json").write_text("[]")
    assert context.select(raw) == ""


def test_review_packet_pins_the_follow_up_shape(raw, tmp_path):
    """A follow-up review gets the last factory review and the changes since it, the threads
    with their replies in pr.md, and the whole annotated diff separately."""
    (raw / "pr_comments.json").write_text(json.dumps(HUMAN_NOTE))
    files = context.build("review", raw, tmp_path / "out")
    assert files == ["diff.txt", "followup.md", "issue.md", "pr.md"]
    out = tmp_path / "out"
    followup = (out / "followup.md").read_text()
    assert followup.startswith("# Follow-up: the factory last reviewed this PR at 159c8292ab9e")
    assert "## Last review · verdict: commented · 2026-09-13T15:11:25Z" in followup
    assert "## Changes since 159c8292ab9e (to 159c8292ab9e)" in followup
    assert "_(no code changes since the last review)_" in followup
    pr = (out / "pr.md").read_text()
    assert "- `src/tally/__init__.py:unknown` · resolved" in pr and "Keep the error wording" in pr
    diff = (out / "diff.txt").read_text()
    assert diff.startswith("diff --git") and "[NEW:" in diff and "[OLD:" in diff
    assert "```" not in diff  # a bare file: nothing for a fence inside the diff to break


def test_review_packet_annotates_the_delta_when_the_head_moved(raw, tmp_path):
    """When the head moved since the last review, the delta is what the reviewer reads first;
    without a delta file the reviewer is told to fall back to the full diff."""
    pr = json.loads((raw / "pr.json").read_text())
    pr["head"]["sha"] = "f" * 40
    (raw / "pr.json").write_text(json.dumps(pr))
    context.build("review", raw, tmp_path / "out")
    followup = (tmp_path / "out" / "followup.md").read_text()
    assert "## Changes since 159c8292ab9e (to ffffffffffff)" in followup
    assert "[NEW:" in followup.split("## Changes since")[1]
    (raw / "delta.patch").unlink()
    context.build("review", raw, tmp_path / "out2")
    assert "_(delta unavailable; use diff.txt)_" in (tmp_path / "out2" / "followup.md").read_text()


def test_review_packet_first_review_says_so(raw, tmp_path):
    """With no earlier factory review there is nothing to follow up; the file says exactly that
    so the station does not go looking."""
    (raw / "reviews.json").write_text("[]")
    context.build("review", raw, tmp_path / "out")
    assert (tmp_path / "out" / "followup.md").read_text() == (
        "# Follow-up\nNo earlier factory review on this PR: this is the first review, so there is "
        "nothing to re-judge.\n")


def test_annotate_marks_old_new_and_context_lines():
    """Inline review comments need exact side/line pairs; the markers are what a reviewer cites."""
    patch = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n ctx\n-old\n+new\n"
    assert context.annotate(patch).splitlines()[3:] == [
        "@@ -1,2 +1,2 @@", "[OLD:1,NEW:1] ctx", "[OLD:2] old", "[NEW:2] new"]


def test_retro_packet_lists_only_human_touches_per_item(raw, tmp_path):
    """Retro learns from what humans had to add; factory lines shrink to their headline and
    bot activity on the PR is left out."""
    metrics = {"since_days": 30,
               "summary": {"items": 1, "shipped": 1, "total_cost_usd": 3.2,
                           "cost_per_shipped_usd": 3.2, "factory_minutes_per_shipped": 17.2,
                           "runs_per_shipped": 5.0, "steers_per_shipped": 1.0,
                           "needs_human_per_shipped": 0.0, "autonomy_pct": 0},
               "items": [{"issue": 6, "prs": [13], "runs": 5, "cost_usd": 3.2,
                          "factory_minutes": 17.2, "shipped": True,
                          "parked": False, "steers": 1, "autonomous": False,
                          "needs_human": False}]}
    item = raw / "items" / "6"
    item.mkdir(parents=True)
    (raw / "metrics.json").write_text(json.dumps(metrics))
    shutil.copy(raw / "comments.json", item / "comments.json")
    shutil.copy(raw / "reviews.json", item / "reviews-13.json")
    shutil.copy(raw / "threads.json", item / "threads-13.json")
    shutil.copy(raw / "commits.json", item / "commits-13.json")
    (item / "pr_comments-13.json").write_text(json.dumps([{
        "user": {"login": "tianchi-fetch", "type": "User"}, "body": "Nice, but keep it terser.",
        "created_at": "2026-09-13T15:25:46Z"}]))
    threads = json.loads((item / "threads-13.json").read_text())
    threads.append({"id": "PRRT_h", "isResolved": False, "path": "README.md", "line": 2,
                    "comments": {"nodes": [{"databaseId": 9, "author": {"login": "tianchi-fetch"},
                                            "body": "Typo here.",
                                            "createdAt": "2026-09-13T16:00:00Z"}]}})
    (item / "threads-13.json").write_text(json.dumps(threads))
    assert context.build("retro", raw, tmp_path / "out") == ["items.md", "metrics.json"]
    items = (tmp_path / "out" / "items.md").read_text()
    assert "- cost: $3.20 · the North Star" in items and "- autonomy: 0%" in items
    assert items.index("Per shipped item") < items.index("Across shipped items")
    assert ("- human thread on `README.md:2` (open · 1 human comment) · tianchi-fetch · "
            "2026-09-13T16:00:00Z: Typo here.") in items
    assert ("## Issue #6 · state: shipped · cost: $3.20 · runs: 5 · factory time: 17.2m · "
            "steers: 1 · needs-human: no") in items
    assert "- factory run · 2026-09-13T14:58:50Z: **factory · triage → automatable**" in items
    assert "- factory run · 2026-09-13T03:16:18Z: **factory · triage → needs_info**" in items
    assert ("- human conversation comment · tianchi-fetch · 2026-09-13T15:25:46Z: Nice, but keep "
            "it terser.") in items
    assert "human review" not in items and "human commit" not in items
    assert json.loads((tmp_path / "out" / "metrics.json").read_text())["items"][0]["issue"] == 6


def test_retro_thread_row_quotes_the_opening_human_comment_and_counts_the_rest(raw, tmp_path):
    """The steer lives in the comment that opened the thread; later replies, a bot's or the
    human's own, must not replace it, and the count tells the agent there is more to fetch."""
    (raw / "metrics.json").write_text(json.dumps({
        "since_days": 14, "summary": {"items": 1, "shipped": 0, "total_cost_usd": 0.0},
        "items": [{"issue": 6, "prs": [13], "runs": 0, "cost_usd": 0.0, "factory_minutes": 0.0,
                   "shipped": False, "parked": False, "steers": 0, "autonomous": False,
                   "needs_human": False}]}))
    item = raw / "items" / "6"
    item.mkdir(parents=True)
    (item / "threads-13.json").write_text(json.dumps([{
        "id": "PRRT_h", "isResolved": True, "path": "src/tally.py", "line": 40,
        "comments": {"nodes": [
            {"databaseId": 1, "author": {"login": "tianchi-fetch"}, "body": "Rename this.",
             "createdAt": "2026-09-13T16:00:00Z"},
            {"databaseId": 2, "author": {"login": "github-actions"}, "body": "Done.",
             "createdAt": "2026-09-13T16:05:00Z"},
            {"databaseId": 3, "author": {"login": "tianchi-fetch"}, "body": "Thanks.",
             "createdAt": "2026-09-13T16:10:00Z"}]}}]))
    context.build("retro", raw, tmp_path / "out")
    items = (tmp_path / "out" / "items.md").read_text()
    assert ("- human thread on `src/tally.py:40` (resolved · 2 human comments) · tianchi-fetch · "
            "2026-09-13T16:00:00Z: Rename this.") in items
    assert "Thanks." not in items


def test_quote_fences_bodies_so_their_markdown_cannot_pose_as_packet_structure():
    """An issue body is raw Markdown: its `##` headings would sit level with the packet's own, and
    a `### login` line could forge a comment header. Quoting makes it data; the fence outgrows
    any backtick run inside so a nested code block cannot close it early."""
    body = "## Comments\n\n### github-actions[bot] (bot) · now\n\n```py\nx = 1\n```"
    quoted = context.quote(body)
    assert quoted.startswith("````text\n## Comments") and quoted.endswith("```\n````")
    assert context.quote("   ") == "_(no text)_"
    assert context.quote(None, "_(no body)_") == "_(no body)_"


def test_first_line_marks_hidden_text_by_more_than_the_line_shown():
    """The " …" marker tells the agent there is more to fetch. It has to fire whenever the body
    holds more than the line shown, a second line included, not only when the body is long."""
    assert context.first_line("Fix bug\n\nDetails below.") == "Fix bug …"
    assert context.first_line("Fix bug") == "Fix bug"
    assert context.first_line("x" * 10, width=4) == "xxxx …"
    assert context.first_line(None) == ""
