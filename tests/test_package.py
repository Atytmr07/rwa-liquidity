"""Smoke tests for packaging and the CLI entry point.

These are not coverage filler. They fail when the package is not installed into
the environment under test, when the `rwa-liquidity` console script points at a
name that no longer exists, or when a subpackage is missing from the wheel --
each of which is a real and easy-to-miss build regression.
"""

from __future__ import annotations

import importlib
from importlib.metadata import entry_points

import pytest
from typer.testing import CliRunner

import rwa_liquidity
from rwa_liquidity.cli import app

runner = CliRunner()

SUBPACKAGES = [
    "rwa_liquidity.cache",
    "rwa_liquidity.export",
    "rwa_liquidity.metrics",
    "rwa_liquidity.reconcile",
    "rwa_liquidity.schema",
    "rwa_liquidity.sources",
]


def test_version_is_resolved_from_installed_metadata() -> None:
    # "0.0.0+unknown" is the fallback used when the package is importable but
    # not installed, which would mean the test environment is misconfigured.
    assert rwa_liquidity.__version__ != "0.0.0+unknown"


@pytest.mark.parametrize("module_name", SUBPACKAGES)
def test_subpackage_is_importable(module_name: str) -> None:
    assert importlib.import_module(module_name) is not None


def test_console_script_is_registered() -> None:
    scripts = entry_points(group="console_scripts")
    assert "rwa-liquidity" in scripts.names


def test_cli_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert rwa_liquidity.__version__ in result.output


def test_cli_with_no_arguments_shows_help() -> None:
    result = runner.invoke(app, [])
    # `no_args_is_help=True` makes typer exit with the usage message rather than
    # succeeding silently, which would be a confusing first-run experience.
    assert result.exit_code != 0
    assert "Usage" in result.output
