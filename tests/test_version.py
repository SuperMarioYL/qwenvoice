"""Version lockstep — pyproject.toml, VERSION, __version__, CLI --version agree.

Every version surface found by the drift sweeps must carry the same value; a
bump that misses a surface fails here. v0.4.0 added the two surfaces the
previous guard missed: the newest CHANGELOG heading and the site's
``meta.content_version``.
"""

from __future__ import annotations

import json
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


def _newest_changelog_version() -> str:
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## \[([^\]]+)\]", text, flags=re.MULTILINE)
    assert m, "CHANGELOG.md has no version heading"
    return m.group(1)


def _site_content_version() -> str:
    data = json.loads((REPO_ROOT / "web" / "site.json").read_text(encoding="utf-8"))
    return data["meta"]["content_version"]


def test_version_lockstep_across_all_surfaces() -> None:
    version_file = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert __version__ == _pyproject_version() == version_file


def test_changelog_head_matches_version() -> None:
    # Equality, not "contains a heading": a bump that forgets the changelog fails.
    assert _newest_changelog_version() == __version__


def test_site_content_version_matches_version() -> None:
    assert _site_content_version() == f"v{__version__}"


def test_cli_version_flag_matches_package_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output
