"""The intake sensor: labeled GitHub issues become work items, idempotently.

gh is mocked at the adapter boundary — these tests pin the sensor's contract
(dedupe, mirror links, best-effort labeling), not GitHub's behavior."""

from pathlib import Path

import pytest

from factory.adapters import github
from factory.cli import main
from factory.dispatch import Dispatcher

ISSUES = [
    {"number": 7, "title": "Fix CSV export crash", "body": "Crashes on empty rows.",
     "url": "https://github.com/o/r/issues/7"},
    {"number": 9, "title": "Add health endpoint", "body": "", "url": "https://github.com/o/r/issues/9"},
]


@pytest.fixture
def gh_ok(monkeypatch):
    """A healthy gh: two open intake issues, label sync succeeds and is recorded."""
    synced = []

    def fake_sync(issue, new_state, old_state=None, repo=None):
        synced.append((issue, new_state))
        return 0, ""

    monkeypatch.setattr(github, "available", lambda: True)
    monkeypatch.setattr(github, "list_issues", lambda label, repo=None, limit=50: (0, ISSUES, ""))
    monkeypatch.setattr(github, "sync_label", fake_sync)
    return synced


def test_intake_files_labeled_issues_as_work_items(factory_root: Path, gh_ok, capsys):
    """Each labeled issue becomes a work item at the start of the line with the
    mirror recorded (source/source_ref, URL in the body) and the conveyor label
    applied to the issue — GitHub issues as the factory's inbox. The item itself
    carries no classifier label; the mirror is its provenance, and triage assigns
    any labels."""
    rc = main(["--root", str(factory_root), "intake"])
    assert rc == 0
    d = Dispatcher(factory_root)
    items = d.store.list_items()
    assert [(i.title, i.source, i.source_ref, i.state) for i in items] == [
        ("Fix CSV export crash", "github", "7", "triage"),
        ("Add health endpoint", "github", "9", "triage"),
    ]
    assert "Mirrors: https://github.com/o/r/issues/7" in items[0].body
    assert items[0].labels == []
    assert gh_ok == [("7", "triage"), ("9", "triage")]
    assert "2 ingested, 0 already on the line" in capsys.readouterr().out


def test_intake_is_idempotent_across_runs(factory_root: Path, gh_ok, capsys):
    """Re-running the sensor must skip issues already on the line (matched by
    source_ref) — that's what makes it safe on a cron with no ingested-marker
    state on the GitHub side."""
    main(["--root", str(factory_root), "intake"])
    capsys.readouterr()
    rc = main(["--root", str(factory_root), "intake"])
    assert rc == 0
    assert "0 ingested, 2 already on the line" in capsys.readouterr().out
    assert len(Dispatcher(factory_root).store.list_ids()) == 2


def test_intake_dry_run_creates_nothing(factory_root: Path, gh_ok, capsys):
    """--dry-run must preview the ingest list and leave the store untouched."""
    rc = main(["--root", str(factory_root), "intake", "--dry-run"])
    assert rc == 0
    assert "would ingest: #7" in capsys.readouterr().out
    assert Dispatcher(factory_root).store.list_ids() == []


def test_intake_fails_loudly_without_gh(factory_root: Path, monkeypatch, capsys):
    """No gh means the sensor can't sense — an explicit error, not a silent
    zero-issue success that reads like an empty inbox."""
    monkeypatch.setattr(github, "available", lambda: False)
    rc = main(["--root", str(factory_root), "intake"])
    assert rc == 1
    assert "gh not found" in capsys.readouterr().err


def test_intake_surfaces_list_failures(factory_root: Path, monkeypatch, capsys):
    """A failing gh call (bad repo, no auth) must fail the command with gh's own
    error — not masquerade as an empty inbox."""
    monkeypatch.setattr(github, "available", lambda: True)
    monkeypatch.setattr(
        github, "list_issues", lambda label, repo=None, limit=50: (1, [], "no auth token")
    )
    rc = main(["--root", str(factory_root), "intake"])
    assert rc == 1
    assert "no auth token" in capsys.readouterr().err
    assert Dispatcher(factory_root).store.list_ids() == []


def test_intake_keeps_the_item_when_label_sync_fails(factory_root: Path, monkeypatch, capsys):
    """The issue-side breadcrumb is best-effort: a failed label sync must warn
    but never roll back or hide the created work item — dedupe rides on the
    store, not the label."""
    monkeypatch.setattr(github, "available", lambda: True)
    monkeypatch.setattr(
        github, "list_issues", lambda label, repo=None, limit=50: (0, ISSUES[:1], "")
    )
    monkeypatch.setattr(
        github,
        "sync_label",
        lambda issue, new_state, old_state=None, repo=None: (1, "label not found"),
    )
    rc = main(["--root", str(factory_root), "intake"])
    assert rc == 0
    assert "label sync failed" in capsys.readouterr().out
    assert len(Dispatcher(factory_root).store.list_ids()) == 1


def test_list_issues_builds_the_gh_query_and_parses_json(monkeypatch):
    """The adapter must ask gh for open issues with the label and clean --json
    fields, and hand back parsed dicts — stdout/stderr kept apart so gh noise
    can't corrupt the parse."""
    calls = []

    def fake_run(args):
        calls.append(args)
        return 0, '[{"number": 3, "title": "t", "body": "b", "url": "u"}]', "warning: noise"

    monkeypatch.setattr(github, "_run", fake_run)
    rc, issues, err = github.list_issues("intake", repo="o/r", limit=10)
    assert rc == 0 and err == ""
    assert issues == [{"number": 3, "title": "t", "body": "b", "url": "u"}]
    args = calls[0]
    assert args[:2] == ["issue", "list"]
    assert ("--label", "intake") == (args[2], args[3])
    assert "--repo" in args and "o/r" in args
    assert "number,title,body,url" in args
