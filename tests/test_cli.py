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


def issue_json(*labels, state="OPEN"):
    names = ["triaged", *labels] if labels else []
    return json.dumps({"number": 7, "title": "t", "state": state,
                       "labels": [{"name": f"factory:{s}"} for s in names]})


def pr_json(head="fix/7-slug", number=12, oid="a" * 40):
    return json.dumps([{"number": number, "url": f"https://x/pr/{number}", "headRefName": head,
                        "headRefOid": oid, "isDraft": False}])


@pytest.fixture
def gh(monkeypatch):
    stub = GH(**{"repo view": "o/r\n", "api --paginate --slurp": "[[]]", "pr list": "[]"})
    monkeypatch.setattr(cli, "_gh", stub)
    return stub


def report(station="triage", verdict="ready_to_implement", **extra):
    base = {"station": station, "verdict": verdict, "summary": "why", "model": "m",
            "cost_usd": 0.1, "session_id": "s1", "turns": 3, "duration_ms": 1000,
            "run_url": "https://x/run/1", "ts": "2026-01-01T00:00:00Z", "head": None, "pr": None}
    if station == "review":
        base |= {"body": "b", "comments": [], "head": "a" * 40, "pr": 12}
    return base | extra


def review(state, bot, at, verdict=None, session="s0"):
    rec = f'{cli.REVIEW_MARK}{{"verdict":"{verdict}","head":"x","session_id":"{session}"}} -->'
    return {"state": state, "submitted_at": at, "user": {"type": "Bot" if bot else "User"},
            "body": rec if verdict else ""}


def commit(email, at):
    return {"commit": {"author": {"email": email, "date": at}}}


def write(tmp_path, r):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(r))
    return str(p)


# --------------------------------------------------------------------------- contract


def test_schema_verdicts_are_exactly_the_transition_table():
    """The schema is derived from TRANSITIONS, so a verdict apply cannot route cannot be
    produced, and a new transition needs no second edit."""
    for station in cli.STATIONS:
        expected = sorted(v for (s, v) in cli.TRANSITIONS if s == station)
        assert cli.schema(station)["properties"]["verdict"]["enum"] == expected
        assert cli.schema(station)["additionalProperties"] is False
    assert cli.schema("retro")["properties"]["verdict"]["enum"] == ["proposed", "nothing_to_learn"]


def test_every_transition_has_a_headline_and_a_next_step():
    """The run comment is built from these tables by key; a transition missing from either would
    crash apply after the station already spent its tokens."""
    assert set(cli.HEADLINE) == set(cli.TRANSITIONS) == set(cli.NEXT_STEP)
    assert set(cli.DISPATCH) <= set(cli.TRANSITIONS)


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


def test_validate_accepts_a_folded_details_block_in_a_review_body():
    """The style contract asks for `<details><summary>Rules</summary>` in review bodies; the
    leaked-markup guard must not mistake that closing tag for a broken tool call."""
    body = "## TL;DR\nok\n\n<details><summary>Rules</summary>\n\n- 1 holds\n\n</details>"
    cli.validate(report("review", "approve", body=body), "review")
    with pytest.raises(SystemExit, match="malformed"):
        cli.validate(report("review", "approve", body="x</body>\n<parameter name=\"v\">"), "review")


def test_validate_checks_review_comment_shape():
    """A malformed inline comment would 422 the whole PR review at post time; catch it first."""
    bad = report("review", "approve", comments=[{"path": "a.py", "body": "x"}])
    with pytest.raises(SystemExit, match="comments\\[0\\]"):
        cli.validate(bad, "review")


def test_run_comment_is_headline_outcome_next_step_and_folded_notes():
    """The comment a human skims: outcome first, what to do next, everything else collapsed, and
    the hidden JSON that metrics and retro read back unchanged."""
    text = cli.run_comment(report(notes="the why", cost_usd=0.0731, duration_ms=118000))
    lines = text.splitlines()
    assert lines[0] == "**Triage · recommends ready-to-implement** · $0.07 · 2m · [run](https://x/run/1)"
    assert lines[1] == "why"
    assert lines[2] == "To start, add the `factory:ready-to-implement` label."
    assert lines[3] == "<details><summary>Details</summary>" and "the why" in text
    [rec] = cli.parse_marks(text, cli.RUN_MARK)
    assert (rec["cost_usd"], rec["session_id"]) == (0.0731, "s1")
    assert rec["verdict"] == "ready_to_implement"
    assert "capped" not in rec
    capped = cli.run_comment(report("review", "request_changes"), capped=True)
    assert cli.CAPPED_STEP in capped and cli.parse_marks(capped, cli.RUN_MARK)[0]["capped"]


def test_branch_issue_reads_type_and_number_from_factory_branches_only():
    """The branch name is the link between a PR and its issue; anything not shaped
    `<type>/<n>-…` belongs to no item."""
    assert cli.branch_issue("fix/12-blank-cell") == ("fix", 12)
    assert cli.branch_issue("spec/4-group-by") == ("spec", 4)
    assert cli.branch_issue("factory/retro-2026-09-13") is None
    assert cli.branch_issue("main") is None


def test_open_pr_picks_the_items_pr_of_the_asked_kind(gh):
    """An item has a spec PR and a code PR at different times; #7's query must not return #70's
    PR, and asking for the code PR must skip the spec one."""
    gh.responses[("pr", "list")] = json.dumps([
        {"number": 1, "headRefName": "spec/7-x", "headRefOid": "1", "isDraft": False, "url": ""},
        {"number": 2, "headRefName": "fix/70-x", "headRefOid": "2", "isDraft": False, "url": ""},
        {"number": 3, "headRefName": "feat/7-x", "headRefOid": "3", "isDraft": False, "url": ""},
    ])
    assert cli._open_pr(7, spec=True)["number"] == 1
    assert cli._open_pr(7, spec=False)["number"] == 3
    assert cli._open_pr(70, spec=True) is None


# --------------------------------------------------------------------------- attempt cap


def test_sendbacks_counts_factory_send_backs_since_the_last_human_touch():
    """Three unanswered send-backs is the cap; a human review or commit in between resets the
    count, and the review being applied (same session) is not counted twice on a retry."""
    reviews = [
        review("COMMENTED", True, "2026-01-01T01:00:00Z", "request_changes", "a"),
        review("COMMENTED", False, "2026-01-01T02:00:00Z"),
        review("COMMENTED", True, "2026-01-01T03:00:00Z", "request_changes", "b"),
        review("COMMENTED", True, "2026-01-01T04:00:00Z"),
        review("COMMENTED", True, "2026-01-01T05:00:00Z", "request_changes", "c"),
    ]
    assert cli.sendbacks(reviews, []) == 2
    assert cli.sendbacks(reviews, [commit("human@x", "2026-01-01T04:30:00Z")]) == 1
    assert cli.sendbacks(reviews, [commit(cli.BOT_EMAIL, "2026-01-01T04:30:00Z")]) == 2
    assert cli.sendbacks(reviews, [], session_id="c") == 1


def test_apply_caps_the_fourth_send_back_and_stops_dispatching(gh, tmp_path):
    """The loop must not run forever: after three factory send-backs with no human in between,
    the review is still posted but the item goes to needs-human and nothing is dispatched."""
    gh.responses[("issue", "view")] = issue_json("in-review")
    gh.responses[("pr", "list")] = pr_json()
    gh.responses[("api", "--paginate", "--slurp", "repos/o/r/pulls/12/reviews")] = json.dumps([[
        review("COMMENTED", True, f"2026-01-01T0{i}:00:00Z", "request_changes", f"s{i}")
        for i in range(1, 4)]])
    cli.cmd_apply(7, write(tmp_path, report("review", "request_changes", session_id="s9")))
    assert len(gh.argv("api", "--method", "POST")) == 1
    [(comment, _)] = gh.argv("issue", "comment")
    assert cli.CAPPED_STEP in comment[-1]
    [(edit, _)] = gh.argv("issue", "edit")
    assert edit[3:] == ("--add-label", "factory:needs-human", "--remove-label", "factory:in-review")


# --------------------------------------------------------------------------- apply


def test_apply_refuses_a_closed_issue_and_a_report_from_the_wrong_state(gh, tmp_path):
    """A replayed or misrouted report must not move an item that has moved on."""
    gh.responses[("issue", "view")] = issue_json("in-review", state="CLOSED")
    with pytest.raises(SystemExit, match="closed"):
        cli.cmd_apply(7, write(tmp_path, report("review", "approve")))
    gh.responses[("issue", "view")] = issue_json("spec-review")
    with pytest.raises(SystemExit, match="no implement run belongs"):
        cli.cmd_apply(7, write(tmp_path, report("implement", "implemented")))
    assert not gh.argv("issue", "edit")


def test_apply_refuses_implemented_and_ready_for_review_without_an_open_pr(gh, tmp_path):
    """`implemented` with no PR is the most common way a build run lies; the PR is the artifact."""
    gh.responses[("issue", "view")] = issue_json("ready-to-implement")
    with pytest.raises(SystemExit, match="no open PR"):
        cli.cmd_apply(7, write(tmp_path, report("implement", "implemented")))
    gh.responses[("issue", "view")] = issue_json("ready-to-spec")
    gh.responses[("pr", "list")] = pr_json(head="fix/7-code-not-spec")
    with pytest.raises(SystemExit, match="spec/7"):
        cli.cmd_apply(7, write(tmp_path, report("spec", "ready_for_review")))


def test_apply_triage_adds_triaged_and_leaves_the_choice_to_a_human(gh, tmp_path, capsys):
    """Triage recommends; only a human applies a ready label. needs_info is the one verdict that
    sets a state, because the reporter has to act before anyone else can."""
    gh.responses[("issue", "view")] = issue_json()
    cli.cmd_apply(7, write(tmp_path, report()))
    [(edit, _)] = gh.argv("issue", "edit")
    assert edit == ("issue", "edit", "7", "--add-label", "factory:triaged")
    assert capsys.readouterr().out.rstrip().endswith("next: none")
    gh.calls.clear()
    cli.cmd_apply(7, write(tmp_path, report(verdict="needs_info", session_id="s2")))
    [(edit, _)] = gh.argv("issue", "edit")
    assert edit[3:] == ("--add-label", "factory:triaged", "--add-label", "factory:needs-info")


def test_apply_implemented_moves_to_in_review_and_dispatches_review(gh, tmp_path, capsys):
    """Implement's push fires no event (GITHUB_TOKEN), so the dispatch line is how review starts;
    the superseded state label goes away in the same edit."""
    gh.responses[("issue", "view")] = issue_json("ready-to-implement")
    gh.responses[("pr", "list")] = pr_json()
    cli.cmd_apply(7, write(tmp_path, report("implement", "implemented")))
    [(edit, _)] = gh.argv("issue", "edit")
    assert edit[3:] == ("--add-label", "factory:in-review", "--remove-label",
                        "factory:ready-to-implement")
    out = capsys.readouterr().out
    assert "https://x/pr/12" in out and out.rstrip().endswith("next: review")


def test_apply_comments_once_per_session_but_always_fixes_the_label(gh, tmp_path):
    """A retried apply (Actions re-run, flaky network) must not duplicate the run comment, but
    must still leave the label correct."""
    gh.responses[("issue", "view")] = issue_json("ready-to-implement")
    gh.responses[("pr", "list")] = pr_json()
    r = report("implement", "implemented")
    cli.cmd_apply(7, write(tmp_path, r))
    assert len(gh.argv("issue", "comment")) == 1
    gh.calls.clear()
    gh.responses[("api", "--paginate", "--slurp", "repos/o/r/issues/7/comments")] = json.dumps(
        [[{"body": cli.run_comment(r)}]])
    cli.cmd_apply(7, write(tmp_path, r))
    assert not gh.argv("issue", "comment") and gh.argv("issue", "edit")


def test_apply_review_posts_the_review_before_the_label_and_resolves_threads(gh, tmp_path, capsys):
    """The review must land on the PR first: if the label moved and the post failed, implement
    would run with no worklist. Thread resolutions ride the report so the station needs no write
    token."""
    gh.responses[("issue", "view")] = issue_json("in-review")
    gh.responses[("pr", "list")] = pr_json(oid="b" * 40)
    r = report("review", "request_changes", body="## TL;DR\nx", head="b" * 40, resolve=["PRRT_1"],
               comments=[{"path": "a.py", "line": 3, "side": "RIGHT", "body": "⚠️ [IMPORTANT] x"}])
    cli.cmd_apply(7, write(tmp_path, r))
    [(post, payload)] = gh.argv("api", "--method", "POST")
    sent = json.loads(payload)
    assert sent["event"] == "REQUEST_CHANGES" and sent["commit_id"] == "b" * 40
    assert sent["body"].startswith("## TL;DR\nx\n\n<sub>factory review · [run](https://x/run/1)")
    assert cli.parse_marks(sent["body"], cli.REVIEW_MARK)[0]["head"] == "b" * 40
    assert sent["comments"][0]["path"] == "a.py"
    assert cli.REVIEW_MARK not in sent["comments"][0]["body"]
    [(mut, _)] = gh.argv("api", "graphql")
    assert "resolveReviewThread" in mut[3] and mut[-1] == "id=PRRT_1"
    order = [a[:2] for a, _ in gh.calls]
    assert order.index(("api", "--method")) < order.index(("issue", "edit"))
    assert capsys.readouterr().out.rstrip().endswith("next: implement")


def test_apply_review_of_a_stale_head_is_dropped_without_error(gh, tmp_path, capsys):
    """A human pushed while the review ran: the push already triggered a fresh review, so the
    stale one is neither posted nor applied, and the job stays green."""
    gh.responses[("issue", "view")] = issue_json("in-review")
    gh.responses[("pr", "list")] = pr_json(oid="c" * 40)
    cli.cmd_apply(7, write(tmp_path, report("review", "approve", head="a" * 40)))
    assert not gh.argv("api", "--method", "POST") and not gh.argv("issue", "edit")
    assert capsys.readouterr().out.rstrip().endswith("next: none")


def test_apply_files_followups_as_plain_issues(gh, tmp_path):
    """An out-of-scope defect a station finds must land somewhere durable; a plain, unlabeled
    issue is triaged like any other."""
    gh.responses[("issue", "view")] = issue_json()
    r = report(followups=[{"title": "README invocation fails", "body": "no [project.scripts]"}])
    cli.cmd_apply(7, write(tmp_path, r))
    [(create, _)] = gh.argv("issue", "create")
    assert create[3] == "README invocation fails" and "working on #7" in create[5]


def test_post_review_skips_a_reviewed_head_and_survives_a_failed_resolve(gh, tmp_path):
    """A retry after a partial apply (review posted, comment not yet) must not post the review
    again, and a token that cannot resolve threads must not fail the whole apply."""
    gh.responses[("issue", "view")] = issue_json("in-review")
    gh.responses[("pr", "list")] = pr_json()
    gh.responses[("api", "--paginate", "--slurp", "repos/o/r/pulls/12/reviews")] = json.dumps([[
        {"user": {"type": "Bot"}, "submitted_at": "2026-01-01T00:00:00Z",
         "body": f'{cli.REVIEW_MARK}{{"verdict":"approve","head":"{"a" * 40}"}} -->'}]])
    gh.responses[("api", "graphql")] = subprocess.CalledProcessError(1, ["gh"], "", "denied")
    r = report("review", "approve", resolve=["PRRT_1"])
    cli.cmd_apply(7, write(tmp_path, r))
    assert not gh.argv("api", "--method", "POST")
    assert gh.argv("issue", "comment") and gh.argv("issue", "edit")


def test_post_review_degrades_anchor_then_event_but_never_drops_findings(gh):
    """GitHub rejects bad inline anchors (422) and reviews of the poster's own PR; both fall back
    and keep the findings in the body."""
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


# --------------------------------------------------------------------------- labels, metrics


def test_labels_creates_the_set_and_removes_stale_factory_labels(gh):
    """`factory labels` is the whole label migration: the eight current labels with their colors,
    and any other factory:* label gone."""
    gh.responses[("label", "list")] = json.dumps(
        [{"name": "factory:triage"}, {"name": "factory:triaged"}, {"name": "bug"}])
    cli.cmd_labels()
    created = [a[2] for a, _ in gh.argv("label", "create")]
    assert created == [f"factory:{name}" for name in cli.LABELS]
    assert gh.argv("label", "create")[0][0][4] == "5319E7"
    assert [a[2] for a, _ in gh.argv("label", "delete")] == ["factory:triage"]


def test_item_metrics_and_aggregate_from_a_fixture_record():
    """Cost per shipped item, cycle time, autonomy, and steers are all derived from the record;
    pin the arithmetic."""
    issue = {"number": 7, "state": "CLOSED", "stateReason": "COMPLETED",
             "createdAt": "2026-01-01T00:00:00Z", "labels": [{"name": "factory:triaged"}]}
    comments = [
        {"body": cli.run_comment(report(cost_usd=0.5))},
        {"body": cli.run_comment(report("implement", "implemented", cost_usd=2.0,
                                        session_id="s2"))},
    ]
    prs = [{"number": 3, "headRefName": "spec/7-x", "mergedAt": "2026-01-01T06:00:00Z"},
           {"number": 4, "headRefName": "feat/7-x", "mergedAt": "2026-01-01T12:00:00Z"}]
    reviews = [review("CHANGES_REQUESTED", False, "2026-01-01T07:00:00Z"),
               review("COMMENTED", True, "2026-01-01T08:00:00Z", "request_changes"),
               review("APPROVED", False, "2026-01-01T11:00:00Z")]
    commits = [commit(cli.BOT_EMAIL, "2026-01-01T09:00:00Z"),
               commit("human@x", "2026-01-01T10:00:00Z")]
    shipped = cli.item_metrics(issue, comments, prs, reviews, commits)
    assert shipped == {"issue": 7, "prs": [3, 4], "runs": 2, "cost_usd": 2.5, "shipped": True,
                       "parked": False, "cycle_hours": 12.0, "steers": 2, "autonomous": False,
                       "needs_human": False}
    stuck = cli.item_metrics(
        {"number": 8, "state": "OPEN", "stateReason": None, "createdAt": "2026-01-01T00:00:00Z"},
        [{"body": cli.run_comment(report("implement", "blocked", cost_usd=1.0))}], [], [], [])
    assert stuck["needs_human"] and not stuck["shipped"]
    agg = cli.aggregate([shipped, stuck])
    assert agg["cost_per_shipped_usd"] == 3.5 and agg["total_cost_usd"] == 3.5
    assert agg["median_cycle_hours"] == 12.0 and agg["autonomy_pct"] == 0
    assert agg["steers_per_shipped"] == 2.0 and agg["runs"] == 3 and agg["needs_human"] == 1
