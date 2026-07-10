# Deferred capabilities — parked, not installed

Things the factory can grow into but doesn't run in v1. They live outside `.claude/` on purpose: `install/install.py` only copies what's listed in `CLAUDE_ITEMS`/`ROOT_FILES`, and nothing here is on those lists — so adopting a repo never installs a station that isn't wired into the line. Keeping the code here (rather than deleting it) means re-enabling is a move-and-register, not a rewrite.

## `factory-monitor/`
The monitoring station — watch a shipped change and spawn a follow-up work item when something breaks. Deferred because continuous monitoring needs a real signal layer (logs/alerts/metrics reasoning) the factory doesn't own yet; a green post-merge deploy is v1's ship-and-success signal, and post-ship regressions enter as *new* work items. See `docs/OPTIMIZATION-AREAS.md` §4 for the rationale and the plan for turning it on. The re-enable steps live at the top of `factory-monitor/SKILL.md`.
