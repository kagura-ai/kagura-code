"""Smoke tests for the CLI skeleton.

Phase 1 only verifies the CLI is wired up and `--version` returns the
package version. Real behavior tests arrive in Phase 2.
"""
from __future__ import annotations

from typer.testing import CliRunner

from kagura_code import __version__
from kagura_code.cli import app

runner = CliRunner()


def test_version_flag_reports_package_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_no_args_prints_skeleton_notice() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "skeleton" in result.stdout.lower()
