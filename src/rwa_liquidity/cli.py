"""Command-line interface.

The CLI is presentation only. Every number it shows comes from the same
functions the Python API exposes, so nothing can be computed one way on the
terminal and another way in a notebook.

Two things it goes out of its way to show, because a table of six numbers is
easy to misread:

* **The mode is in the header, always.** A turnover ratio means something
  different under `secondary_only` than under `all`, and a figure copied out of
  a terminal loses that context unless it was printed with it.
* **Caveats are printed, not swallowed.** Metrics carry warnings about truncated
  holder lists, unclassified transfers, and undefined denominators. They appear
  under the table rather than being dropped to keep the output tidy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from rich.table import Table

from rwa_liquidity import __version__
from rwa_liquidity.demo import DEMO_LABEL, load_demo_dataset
from rwa_liquidity.metrics.base import DEFAULT_WINDOW_DAYS, Window
from rwa_liquidity.metrics.report import METRIC_COLUMNS, build_report, report_frame
from rwa_liquidity.reconcile import reconcile_snapshots
from rwa_liquidity.schema.types import Denomination, VolumeMode

if TYPE_CHECKING:
    from collections.abc import Sequence

    import polars as pl

    from rwa_liquidity.metrics.report import AssetReport

console = Console()

app = typer.Typer(
    name="rwa-liquidity",
    no_args_is_help=True,
    add_completion=False,
)

#: How each metric is rendered. Ratios that are conceptually shares are shown as
#: percentages; turnover is left as a ratio because that is how it is quoted.
_FORMATS: dict[str, str] = {
    "turnover_ratio": "ratio",
    "active_holder_ratio": "percent",
    "volume_per_active_address": "quantity",
    "top_10_holder_share": "percent",
    "holder_hhi": "index",
    "dormancy": "percent",
}


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


def _cell(name: str, value: float | None) -> str:
    """Render one metric value, marking an undefined one as such."""
    if value is None:
        # Not "0", and not blank. The metric could not be computed, which is
        # different from it being zero and different from it being missing.
        return "[dim]n/a[/dim]"
    match _FORMATS.get(name, "ratio"):
        case "percent":
            return f"{value:.1%}"
        case "index":
            return f"{value:,.0f}"
        case "quantity":
            return f"{value:,.0f}"
        case _:
            return f"{value:.4f}"


def _render_table(reports: Sequence[AssetReport], *, mode: VolumeMode) -> None:
    if reports:
        # Printed above the table rather than as a title: a long title wraps and
        # becomes unreadable in an 80-column terminal, and the mode is the one
        # piece of context a copied figure must not lose.
        console.print(f"[bold]mode[/bold] = {mode}    [bold]window[/bold] = {reports[0].window}")
    table = Table(header_style="bold", expand=False)
    table.add_column("Asset", no_wrap=True)
    for _, label in METRIC_COLUMNS:
        table.add_column(label, justify="right")

    for report in reports:
        label = report.symbol or report.asset_uid
        table.add_row(label, *(_cell(name, report.value(name)) for name, _ in METRIC_COLUMNS))
    console.print(table)


def _render_caveats(reports: Sequence[AssetReport]) -> None:
    flagged = [(r, r.warnings) for r in reports if r.warnings]
    if not flagged:
        return
    console.print("\n[bold]Caveats[/bold]")
    for report, warnings in flagged:
        name = report.symbol or report.asset_uid
        for warning in warnings:
            console.print(f"  [yellow]•[/yellow] [bold]{name}[/bold]: {warning}")


def _render_reconciliation(snapshots: pl.DataFrame) -> None:
    report = reconcile_snapshots(snapshots)
    if report.compared == 0:
        return
    if report.agrees:
        console.print(
            f"\n[green]Sources agree[/green] across {report.compared} comparison(s) "
            f"within {report.tolerance:.0%}."
        )
        return
    console.print(
        f"\n[bold]Cross-source disagreement[/bold] "
        f"({len(report.disagreements)} of {report.compared} comparisons)"
    )
    for item in report.disagreements:
        console.print(f"  [yellow]•[/yellow] {item.describe()}")
    console.print(
        "  [dim]A disagreement is not automatically an error in either source; "
        "see docs/data-sources.md.[/dim]"
    )


@app.command()
def report(  # noqa: PLR0913 -- each option changes what the numbers mean and
    # belongs on the command line rather than hidden in a config file.
    *,
    demo: Annotated[
        bool,
        typer.Option("--demo", help="Use the committed synthetic sample dataset. No API keys."),
    ] = False,
    mode: Annotated[
        VolumeMode,
        typer.Option("--mode", help="Which transfer kinds to count."),
    ] = VolumeMode.SECONDARY_ONLY,
    denomination: Annotated[
        Denomination,
        typer.Option("--denomination", help="Units for volume-based metrics."),
    ] = Denomination.NATIVE,
    days: Annotated[
        int,
        typer.Option("--days", "-d", min=1, help="Length of the observation window."),
    ] = DEFAULT_WINDOW_DAYS,
    top_n: Annotated[
        int,
        typer.Option("--top-n", min=1, help="How many holders the concentration share covers."),
    ] = 10,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Write the table to a file (.csv, .parquet, .tex)."),
    ] = None,
) -> None:
    """Compute liquidity metrics and print them as a table.

    With `--demo` this reads the committed sample dataset and needs no API keys,
    which is the fastest way to see what the package produces.
    """
    if not demo:
        # Live ingestion needs at least a Dune key for transfer data, and there
        # is no honest way to fake it. Saying so beats printing a table of n/a.
        console.print(
            "[yellow]Live mode is not wired up yet.[/yellow] The metrics need "
            "transfer-level data, which only the keyed Dune adapter supplies, and "
            "those adapters have not been verified against their live APIs.\n\n"
            "Run [bold]rwa-liquidity report --demo[/bold] to see the package work "
            "against the committed sample dataset."
        )
        raise typer.Exit(code=1)

    dataset = load_demo_dataset()
    console.print(f"[bold yellow]{DEMO_LABEL}[/bold yellow]\n")

    window = (
        dataset.window
        if days == DEFAULT_WINDOW_DAYS
        else Window.ending(dataset.window.end, days=days)
    )
    reports = build_report(
        dataset.snapshots,
        dataset.transfers,
        dataset.holders,
        window=window,
        mode=mode,
        denomination=denomination,
        top_n=top_n,
    )

    _render_table(reports, mode=mode)
    _render_caveats(reports)
    _render_reconciliation(dataset.snapshots)

    if out is not None:
        from rwa_liquidity.export import write_frame  # noqa: PLC0415 -- optional path

        written = write_frame(
            report_frame(reports),
            out,
            caption=f"Liquidity metrics ({mode}, {days}-day window). Synthetic sample data.",
            column_labels=dict(METRIC_COLUMNS),
        )
        console.print(f"\nWrote [bold]{written}[/bold]")


@app.command()
def sources() -> None:
    """List the ingestion adapters and what each one can answer."""
    from rwa_liquidity.sources import (  # noqa: PLC0415 -- keeps `--version` fast
        DeFiLlamaPricesSource,
        DeFiLlamaProtocolTvlSource,
        DuneSource,
        RwaXyzSource,
        Source,
    )

    table = Table(title="Ingestion adapters", header_style="bold")
    table.add_column("Source")
    table.add_column("Capabilities")
    table.add_column("Key")
    table.add_column("Verified live")

    # Annotated explicitly: a bare list of differing classes is joined by mypy to
    # their shared metaclass, which has none of the attributes read below.
    rows: list[tuple[type[Source], str, str]] = [
        (DeFiLlamaPricesSource, "no", "yes"),
        (DeFiLlamaProtocolTvlSource, "no", "yes"),
        (RwaXyzSource, "yes", "[yellow]no[/yellow]"),
        (DuneSource, "yes", "[yellow]no[/yellow]"),
    ]
    for source_type, key, verified in rows:
        table.add_row(
            source_type.name,
            ", ".join(sorted(capability.value for capability in source_type.capabilities)),
            key,
            verified,
        )
    console.print(table)
    console.print(
        "\n[dim]'Verified live' means the adapter has been run against the real API. "
        "The others were written against published documentation; see "
        "docs/data-sources.md.[/dim]"
    )


@app.command()
def window(days: int = DEFAULT_WINDOW_DAYS) -> None:
    """Print the observation window that `--days` would produce, ending now."""
    period = Window.ending(datetime.now(UTC), days=days)
    console.print(f"{period}  ({period.days:.0f} days)")
