"""The recognized work-item classifiers — the vocabulary stations label from.

Not to be confused with ``github-labels.yml`` — the conveyor labels mirrored onto
GitHub issues, which are presentation. These are the terms gate policies match on
(``labels_any`` / ``labels_all``).

The set is open at the edges: a label outside it is still recorded (the
classification may be right and the vocabulary merely behind), but it is marked
unrecognized wherever labels are shown and never satisfies a policy, and promoting
it is a human edit to ``classifiers.yml``. That asymmetry is what stops
``docs-update`` and ``doc-update`` quietly becoming two terms.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# A starting point, not a taxonomy — adopters are expected to diverge.
SEED = [
    "bug",
    "feature",
    "chore",
    "docs",
    "perf",
    "security",
    "infra",
    "refactor",
    "test",
]


class Classifiers:
    def __init__(self, names: list[str] | None = None, path: Path | None = None):
        self.path = path
        self.names: list[str] = list(names if names is not None else SEED)
        self._set = set(self.names)

    @classmethod
    def default(cls) -> Classifiers:
        return cls()

    @classmethod
    def load(cls, path: str | Path) -> Classifiers:
        """Load the vocabulary, falling back to the seed when the file is absent, so
        a repo without one doesn't read every label as unrecognized."""
        p = Path(path)
        if not p.exists():
            return cls(path=p)
        data = yaml.safe_load(p.read_text()) or {}
        return cls(data.get("classifiers") or [], path=p)

    def is_recognized(self, name: str) -> bool:
        return name in self._set

    def recognized(self, names: list[str]) -> list[str]:
        return [n for n in names if n in self._set]

    def unrecognized(self, names: list[str]) -> list[str]:
        return [n for n in names if n not in self._set]

    def mark(self, names: list[str]) -> str:
        """Render labels for a human, flagging what the vocabulary doesn't know."""
        return ", ".join(n if n in self._set else f"{n} (unrecognized)" for n in names)
