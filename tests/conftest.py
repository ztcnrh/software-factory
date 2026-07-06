import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def factory_root(tmp_path: Path) -> Path:
    """A throwaway factory root: the real line.yml plus an empty policy set."""
    shutil.copy(REPO / "line.yml", tmp_path / "line.yml")
    (tmp_path / "policies.yml").write_text("version: 1\ndefault: require_human\nrules: []\n")
    return tmp_path
