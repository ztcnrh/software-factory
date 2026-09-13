"""Tests for the deterministic layer. GitHub is stubbed at `_gh`; claude is never invoked."""

import json
import subprocess

import pytest

from factory import cli


class GH:
    """Stub for `_gh`: canned stdout keyed by argv prefix (longest match wins), calls recorded."""

    def __init__(self, **responses):
        self.responses = {tuple(k.split()): v for k, v in responses.items()}
        self.calls = []

    def __call__(self, *args, input=None):
        self.calls.append((args, input))
        for n in range(len(args), 0, -1):
            hit = self.responses.get(tuple(args[:n]))
            if hit is not None:
                if isinstance(hit, Exception):
                    raise hit
                return hit(args, input) if callable(hit) else hit
        return ""

    def argv(self, *prefix):
        return [(a, i) for a, i in self.calls if a[: len(prefix)] == prefix]


def issue_json(*states):
    return json.dumps({"number": 7, "title": "t", "state": "OPEN",
                       "labels": [{"name": f"factory:{s}"} for s in states]})


def pr_json(state="OPEN", merged=None, draft=False):
    return json.dumps([{"number": 12, "url": "https://x/pr/12", "state": state, "isDraft": draft,
                        "mergedAt": merged, "headRefOid": "a" * 40, "createdAt": "2026-01-01"}])


@pytest.fixture
def gh(monkeypatch):
    stub = GH(**{"repo view": "o/r\n"})
    monkeypatch.setattr(cli, "_gh", stub)
    monkeypatch.setattr(cli, "_item_branch", lambda n: "feature/7-x")
    return stub


def report(station="triage", verdict="automatable", **extra):
    base = {"station": station, "verdict": verdict, "summary": "why", "model": "m",
            "cost_usd": 0.1, "session_id": "s1", "turns": 3, "duration_ms": 1000,
            "run_url": None, "ts": "2026-01-01T00:00:00Z"}
    if station == "review":
        base |= {"body": "b", "comments": []}
    return base | extra


# --------------------------------------------------------------------------- contract


def test_schema_verdicts_are_exactly_the_transition_table():
    """The schema is derived from TRANSITIONS, so a verdict the runner cannot route cannot be
    produced, and a new transition needs no second edit."""
    for station in cli.STATIONS:
        expected = sorted(v for (s, v) in cli.TRANSITIONS if s == station)
        assert cli.schema(station)["properties"]["verdict"]["enum"] == expected
        assert cli.schema(station)["additionalProperties"] is False


def test_validate_refuses_unknown_key_missing_field_and_bad_verdict():
    """apply is data-in: anything the schema would not have produced is refused, not ignored."""
    with pytest.raises(SystemExit, match="unknown keys"):
        cli.validate(report(extra=1), "triage")
    with pytest.raises(SystemExit, match="missing"):
        r = report()
        del r["summary"]
        cli.validate(r, "triage")
    with pytest.raises(SystemExit, match="not one of"):
        cli.validate(report(verdict="implemented"), "triage")


def test_validate_refuses_a_summary_carrying_tool_call_markup():
    """A malformed structured-output call leaks `</summary><parameter name="notes">` into the
    string; posting that as the run comment would put garbage in the record."""
    bad = report(summary='why</summary>\n<parameter name="notes">area: x')
    with pytest.raises(SystemExit, match="malformed"):
        cli.validate(bad, "triage")


def test_validate_checks_review_comment_shape():
    """A malformed inline comment would 422 the whole PR review at post time; catch it first."""
    bad = report("review", "approve", comments=[{"path": "a.py", "body": "x"}])
    with pytest.raises(SystemExit, match="comments\\[0\\]"):
        cli.validate(bad, "review")


def test_run_comment_round_trips_through_parse_marks():
    """The hidden JSON in a run comment is the only machine record of a run; metrics and retro
    must get back exactly what apply wrote."""
    r = report(notes="n", cost_usd=0.0731, duration_ms=118000)
    text = cli.run_comment(r)
    assert text.startswith("**factory · triage → automatable** · m · $0.07 · 2m")
    assert "\nwhy\n\nn\n" in text
    [rec] = cli.parse_marks(text, cli.RUN_MARK)
    assert (rec["cost_usd"], rec["session_id"], rec["verdict"]) == (0.0731, "s1", "automatable")


# --------------------------------------------------------------------------- run


def test_build_prompt_carries_branch_and_pr_facts():
    """The one deterministic fact the runner adds is the branch/PR state, so a station never
    invents a second branch or PR for an item."""
    assert cli.build_prompt("triage", "o/r", 7, None, None) == \
        "/factory-triage Issue #7 in o/r. Branch: none yet."
    assert cli.build_prompt("implement", "o/r", 7, "feature/7-x", None) == \
        "/factory-implement Issue #7 in o/r. Branch: feature/7-x (no PR)"
    pr = {"number": 12, "isDraft": True}
    assert cli.build_prompt("review", "o/r", 7, "feature/7-x", pr).endswith("(PR #12, draft)")
    assert cli.build_prompt("retro", "o/r", None, None, None) == "/factory-retro Repository o/r."


def test_build_argv_is_the_exact_claude_invocation():
    """Local and Actions runs must be the same command; pin every flag."""
    meta = {"model": "sonnet", "tools": ["Bash", "Read"]}
    argv = cli.build_argv("triage", "P", meta, 2.0, "SYS")
    assert argv == [
        "claude", "-p", "P", "--output-format", "stream-json", "--verbose", "--model", "sonnet",
        "--allowedTools", "Bash", "Read", "--permission-prompts", "none", "--max-budget-usd", "2",
        "--json-schema", json.dumps(cli.schema("triage"), separators=(",", ":")),
        "--append-system-prompt", "SYS",
    ]


def test_skill_meta_reads_model_and_tools_from_frontmatter(tmp_path):
    """The skill file is the single place a station's model and tool set are declared."""
    d = tmp_path / ".claude" / "skills" / "factory-spec"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: factory-spec\nmodel: opus\nallowed-tools: Bash Read\n---\nbody")
    assert cli.skill_meta("spec", tmp_path) == {"model": "opus", "tools": ["Bash", "Read"]}
    (d / "SKILL.md").write_text("---\nname: x\n---\n")
    with pytest.raises(SystemExit, match="no model"):
        cli.skill_meta("spec", tmp_path)


# --------------------------------------------------------------------------- apply


def write(tmp_path, r):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(r))
    return str(p)


def test_apply_refuses_when_issue_is_not_at_the_reports_station(gh, tmp_path):
    """No driving backwards: a stale or replayed report cannot move an item that has moved on."""
    gh.responses[("issue", "view")] = issue_json("review")
    with pytest.raises(SystemExit, match="not triage"):
        cli.cmd_apply(7, write(tmp_path, report()))
    assert not gh.argv("issue", "edit")


def test_apply_refuses_implemented_without_an_open_pr(gh, tmp_path):
    """`implemented` with no PR is the most common way a build run lies; the PR is the artifact."""
    gh.responses[("issue", "view")] = issue_json("implement")
    gh.responses[("pr", "list")] = "[]"
    with pytest.raises(SystemExit, match="no open PR"):
        cli.cmd_apply(7, write(tmp_path, report("implement", "implemented")))


def test_apply_comments_then_swaps_label_and_is_idempotent_on_session_id(gh, tmp_path):
    """A retried apply (Actions re-run, flaky network) must not duplicate the run comment, but
    must still leave the label correct."""
    gh.responses[("issue", "view")] = issue_json("triage")
    gh.responses[("pr", "list")] = "[]"
    gh.responses[("api", "--paginate", "--slurp")] = "[[]]"
    cli.cmd_apply(7, write(tmp_path, report()))
    [(comment_args, _)] = gh.argv("issue", "comment")
    assert cli.RUN_MARK in comment_args[-1]
    [(edit_args, _)] = gh.argv("issue", "edit")
    assert edit_args == ("issue", "edit", "7", "--add-label", "factory:implement",
                         "--remove-label", "factory:triage")
    gh.calls.clear()
    existing = json.dumps([[{"body": cli.run_comment(report())}]])
    gh.responses[("api", "--paginate", "--slurp")] = existing
    cli.cmd_apply(7, write(tmp_path, report()))
    assert not gh.argv("issue", "comment") and gh.argv("issue", "edit")


def test_item_pr_prefers_open_then_newest(gh):
    """An item whose branch has had several PRs must resolve to the live one, then the most
    recent closed one, never the oldest."""
    gh.responses[("pr", "list")] = json.dumps([
        {"number": 1, "state": "CLOSED", "createdAt": "2026-01-01T00:00:00Z"},
        {"number": 3, "state": "CLOSED", "createdAt": "2026-03-01T00:00:00Z"},
        {"number": 2, "state": "OPEN", "createdAt": "2026-02-01T00:00:00Z"}])
    assert cli._item_pr(7)["number"] == 2
    gh.responses[("pr", "list")] = json.dumps([
        {"number": 1, "state": "CLOSED", "createdAt": "2026-01-01T00:00:00Z"},
        {"number": 3, "state": "MERGED", "createdAt": "2026-03-01T00:00:00Z"}])
    assert cli._item_pr(7)["number"] == 3


def test_apply_review_resolves_threads_and_skips_the_post_on_a_retry(gh, tmp_path):
    """The review's thread resolutions ride the report so the station never needs a write token,
    and a retried apply must not post the review twice."""
    gh.responses[("issue", "view")] = issue_json("review")
    gh.responses[("pr", "list")] = pr_json()
    gh.responses[("api", "--paginate", "--slurp")] = "[[]]"
    r = report("review", "approve", body="ok", comments=[], resolve=["PRRT_1"])
    cli.cmd_apply(7, write(tmp_path, r))
    assert len(gh.argv("api", "--method", "POST")) == 1
    [(mut, _)] = gh.argv("api", "graphql")
    assert "resolveReviewThread" in mut[3] and mut[-1] == "id=PRRT_1"
    gh.calls.clear()
    gh.responses[("api", "--paginate", "--slurp")] = json.dumps([[{"body": cli.run_comment(r)}]])
    cli.cmd_apply(7, write(tmp_path, r))
    assert not gh.argv("api", "--method", "POST") and gh.argv("issue", "edit")


def test_apply_files_followups_as_plain_issues(gh, tmp_path):
    """An out-of-scope defect a station finds must land somewhere durable; a plain, unlabeled
    issue leaves the decision to run the factory on it with a human."""
    gh.responses[("issue", "view")] = issue_json("triage")
    gh.responses[("pr", "list")] = "[]"
    gh.responses[("api", "--paginate", "--slurp")] = "[[]]"
    r = report(followups=[{"title": "README invocation fails", "body": "no [project.scripts]"}])
    cli.cmd_apply(7, write(tmp_path, r))
    [(create, _)] = gh.argv("issue", "create")
    assert create[3] == "README invocation fails" and "triage run on #7" in create[5]


def test_post_review_skips_a_head_already_reviewed_and_survives_a_failed_resolve(gh, tmp_path):
    """A retry after a partial apply (review posted, comment not yet) must not post the review
    again, and a token that cannot resolve threads must not fail the whole apply."""
    gh.responses[("issue", "view")] = issue_json("review")
    gh.responses[("pr", "list")] = pr_json()
    gh.responses[("api", "--paginate", "--slurp", "repos/o/r/pulls/12/reviews")] = json.dumps(
        [[{"body": f"Reviewed at {'a' * 12}\n\nold\n\n{cli.REVIEW_MARK}"}]])
    gh.responses[("api", "--paginate", "--slurp", "repos/o/r/issues/7/comments")] = "[[]]"
    gh.responses[("api", "graphql")] = subprocess.CalledProcessError(1, ["gh"], "", "denied")
    r = report("review", "approve", body="ok", comments=[], resolve=["PRRT_1"])
    cli.cmd_apply(7, write(tmp_path, r))
    assert not gh.argv("api", "--method", "POST")
    assert gh.argv("issue", "comment") and gh.argv("issue", "edit")


def test_apply_review_posts_pr_review_before_moving_the_label(gh, tmp_path):
    """The review must land on the PR first: if the label moved and the post failed, implement
    would run with no worklist."""
    gh.responses[("issue", "view")] = issue_json("review")
    gh.responses[("pr", "list")] = pr_json()
    gh.responses[("api", "--paginate", "--slurp")] = "[[]]"
    r = report("review", "request_changes", body="Findings", comments=[
        {"path": "a.py", "line": 3, "side": "RIGHT", "body": "⚠️ [IMPORTANT] x"}])
    r["head"] = "b" * 40
    cli.cmd_apply(7, write(tmp_path, r))
    [(post, payload)] = gh.argv("api", "--method", "POST")
    sent = json.loads(payload)
    assert sent["event"] == "REQUEST_CHANGES" and sent["commit_id"] == "b" * 40
    assert sent["body"].startswith("Reviewed at bbbbbbbbbbbb") and cli.REVIEW_MARK in sent["body"]
    assert sent["comments"][0]["path"] == "a.py" and cli.REVIEW_MARK in sent["comments"][0]["body"]
    order = [a[:2] for a, _ in gh.calls]
    assert order.index(("api", "--method")) < order.index(("issue", "edit"))


def test_post_review_does_not_duplicate_the_sha_line_or_marker(gh):
    """A station that copies the Reviewed-at line and marker into its body (the skill documents
    them) must not produce a review with two of each."""
    posted = []
    gh.responses[("api", "--method", "POST")] = lambda a, i: posted.append(json.loads(i)) or ""
    pr = json.loads(pr_json())[0]
    body = "Reviewed at abcdef123456\n\nFindings\n\n" + cli.REVIEW_MARK
    cli._post_review(pr, report("review", "approve", body=body, comments=[
        {"path": "a.py", "line": 1, "side": "RIGHT", "body": "x\n" + cli.REVIEW_MARK}]))
    assert posted[0]["body"] == f"Reviewed at {'a' * 12}\n\nFindings\n\n{cli.REVIEW_MARK}"
    assert posted[0]["comments"][0]["body"] == f"x\n\n{cli.REVIEW_MARK}"


def test_post_review_degrades_anchor_then_event_but_never_drops_findings(gh):
    """GitHub rejects bad inline anchors (422) and self-approval; both fall back and keep the
    findings in the body."""
    attempts = []

    def post(args, payload):
        attempts.append(json.loads(payload))
        if len(attempts) == 1:
            raise subprocess.CalledProcessError(1, args, "", "Unprocessable: line is invalid")
        if len(attempts) == 2:
            raise subprocess.CalledProcessError(
                1, args, "", "Can not request changes on your own pull request")
        return ""

    gh.responses[("api", "--method", "POST")] = post
    pr = json.loads(pr_json())[0]
    cli._post_review(pr, report("review", "request_changes", body="B", comments=[
        {"path": "a.py", "line": 3, "side": "RIGHT", "body": "finding"}]))
    assert attempts[1]["comments"] == [] and "`a.py:3` — finding" in attempts[1]["body"]
    assert attempts[2]["event"] == "COMMENT"


# --------------------------------------------------------------------------- gate


def test_gate_approve_moves_spec_review_to_implement_with_a_gate_comment(gh):
    """A human decision is recorded as a comment (the steer text retro reads) and a label move."""
    gh.responses[("issue", "view")] = issue_json("spec-review")
    cli.cmd_gate(7, "approve", "looks right")
    [(c, _)] = gh.argv("issue", "comment")
    assert "looks right" in c[-1] and cli.parse_marks(c[-1], cli.GATE_MARK)[0]["to"] == "implement"
    assert gh.argv("issue", "edit")[0][0][3:5] == ("--add-label", "factory:implement")


def test_gate_refuses_approve_at_ship_review_and_moves_from_non_gate_states(gh):
    """Merging is the ship approval, so `approve` at ship-review is a mistake to name; `done`,
    `park`, and `retriage` are moves a human can make from any active state."""
    gh.responses[("issue", "view")] = issue_json("ship-review")
    with pytest.raises(SystemExit, match="merge the PR"):
        cli.cmd_gate(7, "approve", None)
    gh.responses[("issue", "view")] = issue_json("implement")
    with pytest.raises(SystemExit, match="not a decision"):
        cli.cmd_gate(7, "approve", None)
    cli.cmd_gate(7, "done", None)
    gh.responses[("issue", "view")] = issue_json("needs-info")
    cli.cmd_gate(7, "retriage", None)
    gh.responses[("issue", "view")] = issue_json("implement")
    cli.cmd_gate(7, "retriage", "this needs a spec: the JSON shape is a contract")
    assert [a[0][4] for a in gh.argv("issue", "edit")] == [
        "factory:done", "factory:triage", "factory:triage"]


def test_gate_refuses_an_issue_with_two_factory_labels(gh):
    """Two states means the record is ambiguous; a human fixes the labels before deciding."""
    gh.responses[("issue", "view")] = issue_json("spec-review", "implement")
    with pytest.raises(SystemExit, match="carries"):
        cli.cmd_gate(7, "approve", None)


# --------------------------------------------------------------------------- diff, metrics


def test_annotate_marks_old_new_and_context_lines():
    """Inline review comments need exact side/line pairs; the markers are what a reviewer cites."""
    patch = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n ctx\n-old\n+new\n"
    assert cli.annotate(patch).splitlines()[3:] == [
        "@@ -1,2 +1,2 @@", "[OLD:1,NEW:1] ctx", "[OLD:2] old", "[NEW:2] new"]


def test_item_metrics_and_aggregate_from_a_fixture_record():
    """Cost per shipped item, cycle time, autonomy, and steers are all derived from the record;
    pin the arithmetic."""
    comments = [
        {"body": cli.run_comment(report(cost_usd=0.5))},
        {"body": cli.run_comment(report("implement", "implemented", cost_usd=2.0,
                                        session_id="s2"))},
        {"body": f"{cli.GATE_MARK}" + json.dumps({"decision": "request_changes"}) + " -->"},
        {"body": f"{cli.GATE_MARK}" + json.dumps({"decision": "retriage"}) + " -->"},
        {"body": f"{cli.GATE_MARK}" + json.dumps({"decision": "approve"}) + " -->"},
    ]
    timeline = [{"event": "labeled", "label": {"name": "factory:triage"},
                 "created_at": "2026-01-01T00:00:00Z"}]
    pr = {"mergedAt": "2026-01-01T12:00:00Z"}
    commits = [{"commit": {"author": {"email": cli.BOT_EMAIL}}},
               {"commit": {"author": {"email": "human@x"}}}]
    shipped = cli.item_metrics(7, comments, timeline, pr, commits)
    assert shipped == {"issue": 7, "pr": None, "runs": 2, "cost_usd": 2.5, "shipped": True,
                       "cycle_hours": 12.0, "steers": 3, "autonomous": False}
    stuck = cli.item_metrics(8, [{"body": cli.run_comment(report(cost_usd=1.0))}], [], None, [])
    agg = cli.aggregate([shipped, stuck])
    assert agg["cost_per_shipped_usd"] == 3.5 and agg["total_cost_usd"] == 3.5
    assert agg["median_cycle_hours"] == 12.0 and agg["autonomy_pct"] == 0
    assert agg["steers_per_shipped"] == 3.0 and agg["runs"] == 3
