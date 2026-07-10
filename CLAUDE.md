# Working on the software factory

- Everything runs through uv: `uv run pytest -q`, `uvx ruff check .`. Python 3.13, line length 100, double quotes.
- The engine stays dumb: `src/factory/` is a deterministic state machine — no natural-language interpretation belongs there. All language understanding lives in `.claude/` (skills, commands). `line.yml` is the single source of truth for the line's shape.
- One consumer per template: `templates/` holds only files a live component fills in or points at (rule and table in `templates/README.md`).
- The CLI's `--help` is its source-of-truth documentation — flag docs live in the parser, and `.claude/` recipes stay thin pointers. Every bug fix ships with a regression test.
- Docs are living artifacts: a change that affects behavior or design updates whatever it touches under `docs/` and `FACTORY-MANUAL.md` in the same change — they are how human adopters and future agents understand the factory and its why, so a stale doc is a bug. If the line's shape or flow changes, also update `docs/diagram.md` (the Mermaid source of truth) and re-render `docs/diagram.png` with `scripts/render-diagram.sh`.
- `docs/OPTIMIZATION-AREAS.md` is a deliberate log, not a wishlist: add an entry only when you can state both the current cost and a plausible direction against the existing architecture; remove one only when it shipped or stopped being true.
- Reading path for the codebase: `docs/CODE-TOUR.md`. Architecture rationale: `docs/ARCHITECTURE.md`.
