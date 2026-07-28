"""Command-line entry point.

Commands are added as their supporting layers land; see the build phases in
README.md. This module stays thin -- argument parsing and presentation only, no
analysis logic -- so that everything the CLI can do is also reachable from the
Python API.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from rwa_liquidity import __version__

console = Console()

app = typer.Typer(
    name="rwa-liquidity",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    """Print the version and exit, before any other option is processed."""
    if value:
        console.print(f"rwa-liquidity {__version__}")
        raise typer.Exit


@app.callback()
def main(
    # `version` is never read in the body: typer's eager callback fires during
    # parsing and exits before this function runs. The parameter exists so that
    # typer knows to register the option at all.
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the installed version and exit.",
        ),
    ] = False,
) -> None:
    """Measure liquidity in tokenized real-world asset (RWA) markets."""
