"""Tests for the per-station packet builders, on raw JSON captured from the sandbox (issue #6 and
its PR #13: a needs-info round, one send-back with a thread and a reply, an approval)."""

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SKILLS = ROOT / ".claude" / "skills"


def script(station: str):
    folder = SKILLS / f"factory-{station}" / "scripts"
    sys.path.insert(0, str(folder))
    spec = importlib.util.spec_from_file_location(f"ctx_{station}", folder / "build_context.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def raw(tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "raw")
    return tmp_path / "raw"


def test_triage_packet_renders_the_thread_and_the_open_work(raw, tmp_path):
    """Triage reads the whole issue thread with who said what, minus the hidden records other
    runs left, and a one-line list of the other open work to spot duplicates."""
    script("triage").main(raw, tmp_path / "out")
    issue = (tmp_path / "out" / "issue.md").read_text()
    assert issue.startswith("# Issue #6: tally total is wrong\nOpened by tianchi-fetch (OWNER)")
    assert "### tianchi-fetch (OWNER) · 2026-09-13 03:16" in issue
    assert "### github-actions[bot] (bot)" in issue
    assert "<!--" not in issue
    related = (tmp_path / "out" / "related.md").read_text()
    assert "- #11 README's `uv run tally` fails" in related and "#6 " not in related


def test_implement_packet_makes_open_threads_the_worklist(raw, tmp_path):
    """A loop-back needs every open thread with its replies and the comment id to reply to;
    resolved threads shrink to one line, and a human's conversation comment is included."""
    threads = json.loads((raw / "threads.json").read_text())
    threads.append({"id": "PRRT_open", "isResolved": False, "path": "README.md", "line": 4,
                    "comments": {"nodes": [
                        {"databaseId": 42, "author": {"login": "github-actions"},
                         "body": "💡 [SUGGESTION] mention the flag",
                         "createdAt": "2026-09-13T15:20:00Z",
                         "pullRequestReview": {"databaseId": 1}}]}})
    (raw / "threads.json").write_text(json.dumps(threads))
    (raw / "pr_comments.json").write_text(json.dumps([{
        "user": {"login": "tianchi-fetch", "type": "User"}, "author_association": "OWNER",
        "created_at": "2026-09-13T15:30:00Z", "body": "Keep the error message wording as is."}]))
    script("implement").main(raw, tmp_path / "out")
    review = (tmp_path / "out" / "review.md").read_text()
    assert review.startswith("# PR #13: #6: tally total is wrong\n`feature/6-parse-currency")
    assert "### `README.md:4` · open · thread `PRRT_open` · reply to comment `42`" in review
    assert "- `src/tally/__init__.py:?` · resolved · ⚠️ [IMPORTANT]" in review
    assert "## Conversation" in review and "Keep the error message wording as is." in review
    assert review.index("· open ·") < review.index("· resolved ·")


def test_spec_packet_has_no_review_file_before_a_pr_exists(raw, tmp_path):
    """A first spec pass has nothing to revise; the packet is the issue alone."""
    for name in ("pr.json", "reviews.json", "threads.json"):
        (raw / name).unlink()
    script("spec").main(raw, tmp_path / "out")
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["issue.md"]


def test_review_select_names_the_last_factory_reviews_head(raw):
    """The delta is fetched from the head the factory last reviewed; the implementer's in-thread
    reply also appears as an empty review and must not be mistaken for one."""
    mod = script("review")
    reviews = json.loads((raw / "reviews.json").read_text())
    mine = mod.factory_reviews(reviews)
    assert [r["id"] for r in mine] == [5191097557, 5191110281]
    assert mine[-1]["commit_id"] == "159c8292ab9e0dadd2b0bfd90473b83b0e8bc832"


def test_review_packet_pins_the_follow_up_shape(raw, tmp_path):
    """A follow-up review gets the last factory review, every thread with its replies and
    resolved state, and the annotated delta since that review; the full diff stays separate."""
    mod = script("review")
    (raw / "pr_comments.json").write_text(json.dumps([{
        "user": {"login": "tianchi-fetch", "type": "User"}, "author_association": "OWNER",
        "created_at": "2026-09-13T15:30:00Z", "body": "Also handle parentheses."}]))
    mod.main(["x", "build", str(raw), str(tmp_path / "out")])
    out = tmp_path / "out"
    assert sorted(p.name for p in out.iterdir()) == ["diff.md", "followup.md", "issue.md", "pr.md"]
    followup = (out / "followup.md").read_text()
    assert followup.startswith("# Follow-up: the factory last reviewed this PR at 159c8292ab9e")
    assert "## Last review · 2026-09-13 15:11" in followup
    assert "### `src/tally/__init__.py:?` · resolved · thread `PRRT_kwDOUYQzws6h5ngE`" in followup
    assert "**github-actions** · 2026-09-13 15:08" in followup  # the implementer's reply
    assert "## Changes since 159c8292ab9e (to 159c8292ab9e)" in followup
    assert "No code changes since the last review." in followup
    diff = (out / "diff.md").read_text()
    assert "[NEW:" in diff and "[OLD:" in diff and diff.count("```diff") == 1
    pr = (out / "pr.md").read_text()
    assert "## Conversation" in pr and "Also handle parentheses." in pr
    assert "## Human reviews" not in pr


def test_review_packet_annotates_the_delta_when_the_head_moved(raw, tmp_path):
    """When the head moved since the last review, the delta is what the reviewer reads first."""
    mod = script("review")
    pr = json.loads((raw / "pr.json").read_text())
    pr["head"]["sha"] = "f" * 40
    (raw / "pr.json").write_text(json.dumps(pr))
    mod.main(["x", "build", str(raw), str(tmp_path / "out")])
    followup = (tmp_path / "out" / "followup.md").read_text()
    assert "## Changes since 159c8292ab9e (to ffffffffffff)" in followup
    assert "[NEW:" in followup.split("## Changes since")[1]
    (raw / "delta.patch").unlink()
    mod.main(["x", "build", str(raw), str(tmp_path / "out2")])
    assert "Delta unavailable; use diff.md." in (tmp_path / "out2" / "followup.md").read_text()


def test_review_packet_first_review_says_so(raw, tmp_path):
    """With no earlier factory review there is nothing to follow up; the file says exactly that
    so the station does not go looking."""
    (raw / "reviews.json").write_text("[]")
    script("review").main(["x", "build", str(raw), str(tmp_path / "out")])
    assert (tmp_path / "out" / "followup.md").read_text() == (
        "No earlier factory review on this PR: this is the first review.\n")


def test_retro_packet_lists_only_human_touches_per_item(raw, tmp_path):
    """Retro learns from what humans had to add; factory lines shrink to their headline and
    bot activity on the PR is left out."""
    metrics = {"since_days": 30, "summary": {"items": 1, "shipped": 1, "cost_per_shipped_usd": 3.2,
                                             "steers_per_shipped": 1.0, "needs_human": 0},
               "items": [{"issue": 6, "prs": [13], "runs": 5, "cost_usd": 3.2, "shipped": True,
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
        "user": {"login": "tianchi-fetch", "type": "User"}, "body": "Nice, but keep it terser."}]))
    script("retro").main(raw, tmp_path / "out")
    items = (tmp_path / "out" / "items.md").read_text()
    assert "## #6 · shipped · $3.20 · 5 runs · 1 steers" in items
    assert "- **factory · triage → automatable**" in items
    assert "- tianchi-fetch · 2026-09-13 03:16: **factory · triage → needs_info**" in items
    assert "- human conversation comment · tianchi-fetch: Nice, but keep it terser." in items
    assert "human review" not in items and "human commit" not in items
    assert json.loads((tmp_path / "out" / "metrics.json").read_text())["items"][0]["issue"] == 6
