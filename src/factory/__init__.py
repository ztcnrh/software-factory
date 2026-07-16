"""software-factory: a personal, self-improving agentic delivery line.

The engine here is deliberately "dumb": a deterministic state machine over work
items. All intelligence (running a station) lives in Claude Code skills and
subagents. This package decides WHAT happens next and records WHAT happened, so
the moving parts stay testable and the line stays inspectable.
"""
