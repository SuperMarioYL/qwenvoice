"""Version lockstep — pyproject.toml, VERSION, __version__, CLI --version agree.

Every version surface found by the v0.2.0 drift sweep must carry the same
value; a bump that misses a surface fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from qwenvoice import __version__
from qwenvoice.cli import app

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    assert m, "pyproject.toml has no version line"
    return m.group(1)


def test_version_lockstep_across_all_surfaces() -> None:
    version_file = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert __version__ == _pyproject_version() == version_file


def test_cli_version_flag_matches_package_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output
