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
from typing import TYPE_CHECKING, Annotated, Final

import polars as pl
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

    from rwa_liquidity.metrics.report import AssetReport
    from rwa_liquidity.sources.base import Source

console = Console()

app = typer.Typer(
    name="rwa-liquidity",
    no_args_is_help=True,
    add_completion=False,
)

#: Cap on how many per-source failures to list before summarising the rest.
_MAX_FAILURES_SHOWN: Final = 5

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


def _collect_live(
    period: Window, *, refresh: bool
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, frozenset[str]]:
    """Measure the registry's assets against live, keyless sources.

    The on-chain adapter comes first because its figures are derived from chain
    state and checked against the contract's own `totalSupply()`, so they are the
    ones to trust when a provider disagrees.
    """
    from rwa_liquidity.pipeline import collect  # noqa: PLC0415 -- keeps `--version` fast
    from rwa_liquidity.sources import (  # noqa: PLC0415
        DeFiLlamaPricesSource,
        EvmRpcSource,
        issuer_addresses,
        load_defillama_registry,
        load_known_addresses,
    )

    assets = [entry.ref for entry in load_defillama_registry()]
    console.print(
        f"Measuring [bold]{len(assets)}[/bold] assets against a public Ethereum node. "
        f"The first run replays each token's full transfer history -- a cold run of the "
        f"whole registry can take a while, and every window is cached as it arrives, so "
        f"re-running after an interruption resumes rather than restarts. See "
        f"[bold]--demo[/bold] for an instant run, or docs/methodology.md for why this "
        f"one is slow."
    )

    known = load_known_addresses()
    sources: list[Source] = [
        EvmRpcSource(issuer_addresses=issuer_addresses(known)),
        DeFiLlamaPricesSource(),
    ]
    try:
        result = collect(sources, assets, window=period, refresh=refresh)
    finally:
        for source in sources:
            source.close()

    if result.failures:
        console.print(f"\n[yellow]{len(result.failures)} fetch(es) failed:[/yellow]")
        for name, message in result.failures[:_MAX_FAILURES_SHOWN]:
            console.print(f"  [yellow]-[/yellow] {name}: {message}")
        remaining = len(result.failures) - _MAX_FAILURES_SHOWN
        if remaining > 0:
            console.print(f"  [dim]... and {remaining} more[/dim]")

    console.print(
        f"\nsources: [bold]{', '.join(result.sources_used) or 'none'}[/bold]    "
        f"transfers: {result.transfers.height:,}    holders: {result.holders.height:,}\n"
    )
    return result.snapshots, result.transfers, result.holders, result.unmeasured


def _collect_history(
    periods: Sequence[Window], *, refresh: bool
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, frozenset[str]]:
    """Gather transfers plus a supply and holder history for every registry asset.

    One scan per asset serves every window: the on-chain adapter walks the full
    history anyway, so a window a year old costs no extra requests.
    """
    from rwa_liquidity.schema.frames import (  # noqa: PLC0415
        AssetSnapshot,
        HolderBalance,
        TransferEvent,
    )
    from rwa_liquidity.schema.validation import polars_schema  # noqa: PLC0415
    from rwa_liquidity.sources import (  # noqa: PLC0415
        EvmRpcSource,
        SourceError,
        issuer_addresses,
        load_defillama_registry,
        load_known_addresses,
    )

    ends = [period.end for period in periods]
    entries = load_defillama_registry()
    console.print(
        f"Reconstructing [bold]{len(entries)}[/bold] assets over "
        f"{len(periods)} windows from on-chain history."
    )

    snapshots: list[pl.DataFrame] = []
    transfers: list[pl.DataFrame] = []
    holders: list[pl.DataFrame] = []
    unmeasured: set[str] = set()

    source = EvmRpcSource(issuer_addresses=issuer_addresses(load_known_addresses()))
    try:
        for entry in entries:
            try:
                snapshots.append(source.supply_snapshots(entry.ref, ends, refresh=refresh))
                holders.append(source.holder_snapshots(entry.ref, ends, refresh=refresh))
                transfers.append(
                    source.fetch_transfers(
                        entry.ref, start=periods[0].start, end=periods[-1].end, refresh=refresh
                    )
                )
            except SourceError as error:
                unmeasured.add(entry.ref.uid)
                console.print(f"  [yellow]-[/yellow] {entry.symbol}: {str(error)[:90]}")
    finally:
        source.close()

    def merge(frames: list[pl.DataFrame], model: type) -> pl.DataFrame:
        # `frames` is empty when *every* asset raised, which a bad enough
        # network makes routine. Falling back to frames[0] then raises
        # IndexError from inside a command whose whole job is to report which
        # assets it could not reach -- the one failure it must survive. An
        # empty frame carrying the right schema keeps the failure legible:
        # every asset lands in `unmeasured` and is reported as such.
        populated = [frame for frame in frames if not frame.is_empty()]
        if populated:
            return pl.concat(populated)
        return pl.DataFrame(schema=dict(polars_schema(model)))

    console.print()
    return (
        merge(snapshots, AssetSnapshot),
        merge(transfers, TransferEvent),
        merge(holders, HolderBalance),
        frozenset(unmeasured),
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
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Bypass the response cache and refetch."),
    ] = False,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Write the table to a file (.csv, .parquet, .tex)."),
    ] = None,
) -> None:
    """Compute liquidity metrics and print them as a table.

    Without `--demo` this measures real assets against a public Ethereum node,
    which also needs no API keys but takes a minute on a cold cache. `--demo`
    reads the committed sample dataset instead and is instant.
    """
    if demo:
        dataset = load_demo_dataset()
        console.print(f"[bold yellow]{DEMO_LABEL}[/bold yellow]\n")
        window = (
            dataset.window
            if days == DEFAULT_WINDOW_DAYS
            else Window.ending(dataset.window.end, days=days)
        )
        snapshots, transfers, holders = dataset.snapshots, dataset.transfers, dataset.holders
        unmeasured: frozenset[str] = frozenset()
    else:
        window = Window.ending(datetime.now(UTC), days=days)
        snapshots, transfers, holders, unmeasured = _collect_live(window, refresh=refresh)

    from rwa_liquidity.sources import (  # noqa: PLC0415 -- keeps `--version` fast
        excluded_contracts,
        load_known_addresses,
    )

    reports = build_report(
        snapshots,
        transfers,
        holders,
        window=window,
        mode=mode,
        denomination=denomination,
        top_n=top_n,
        exclude=excluded_contracts(load_known_addresses()),
        unmeasured=unmeasured,
    )

    _render_table(reports, mode=mode)
    _render_caveats(reports)
    _render_reconciliation(snapshots)

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
def trend(  # noqa: PLR0913 -- window geometry, which metric, which mode, cache
    # policy and destination. Each changes the output and belongs on the command
    # line rather than in a config file.
    *,
    days: Annotated[
        int, typer.Option("--days", "-d", min=1, help="Length of each window.")
    ] = DEFAULT_WINDOW_DAYS,
    periods: Annotated[
        int, typer.Option("--periods", "-p", min=2, max=24, help="How many windows.")
    ] = 6,
    metric: Annotated[
        str, typer.Option("--metric", help="Which metric to track.")
    ] = "turnover_ratio",
    mode: Annotated[VolumeMode, typer.Option("--mode")] = VolumeMode.SECONDARY_ONLY,
    refresh: Annotated[bool, typer.Option("--refresh")] = False,
    out: Annotated[Path | None, typer.Option("--out", "-o")] = None,
) -> None:
    """Track one metric across consecutive windows, to see whether it is moving.

    Supply and holder distributions are reconstructed from the ledger at each
    window's end rather than taken from today, so a fund that has grown does not
    show a falsely collapsing turnover because its denominator moved.
    """
    from rwa_liquidity.metrics.trend import (  # noqa: PLC0415 -- keeps `--version` fast
        build_trend,
        trend_frame,
        windows_ending,
    )

    known = {name for name, _ in METRIC_COLUMNS}
    if metric not in known:
        console.print(
            f"[red]Unknown metric {metric!r}.[/red] Choose one of: {', '.join(sorted(known))}"
        )
        raise typer.Exit(code=2)

    from rwa_liquidity.sources import (  # noqa: PLC0415 -- keeps `--version` fast
        excluded_contracts,
        load_known_addresses,
    )

    periods_of = windows_ending(datetime.now(UTC), days=days, periods=periods)
    snapshots, transfers, holders, unmeasured = _collect_history(periods_of, refresh=refresh)
    trends = build_trend(
        snapshots,
        transfers,
        holders,
        windows=periods_of,
        metric=metric,
        mode=mode,
        exclude=excluded_contracts(load_known_addresses()),
        unmeasured=unmeasured,
    )

    console.print(
        f"[bold]{metric}[/bold]  mode = {mode}  {periods} windows of {days} days, oldest first"
    )
    table = Table(header_style="bold", expand=False)
    table.add_column("Asset", no_wrap=True)
    for period in periods_of:
        # Month-day only: the full date truncates in an 80-column terminal, and
        # the year is already implied by the header line above the table.
        table.add_column(f"{period.end:%m-%d}", justify="right")
    table.add_column("Direction", no_wrap=True)

    for item in trends:
        table.add_row(
            item.symbol or item.asset_uid,
            *(_cell(metric, value) for value in item.values),
            item.direction,
        )
    console.print(table)
    console.print(
        "  [dim]Direction compares the first defined point with the last, and is "
        "deliberately coarse: a handful of observations of a thin market cannot "
        "support a growth rate.[/dim]"
    )

    if out is not None:
        from rwa_liquidity.export import write_frame  # noqa: PLC0415

        written = write_frame(
            trend_frame(trends),
            out,
            caption=f"{metric} over {periods} windows of {days} days ({mode}).",
        )
        console.print(f"\nWrote [bold]{written}[/bold]")


@app.command()
def issuance(*, refresh: Annotated[bool, typer.Option("--refresh")] = False) -> None:
    """Report how each registry asset issues, from its complete history.

    The primary/secondary split rests on issuance passing through the zero
    address. Whether a given token's does is a fact about that token, checkable
    from its own history, and this is where the blanket caveat gets replaced by a
    per-asset answer.
    """
    from rwa_liquidity.sources import (  # noqa: PLC0415
        EvmRpcSource,
        SourceError,
        load_defillama_registry,
    )

    source = EvmRpcSource()
    table = Table(header_style="bold", expand=False)
    for column, justify in (
        ("Asset", "left"),
        ("Transfers", "right"),
        ("Mints", "right"),
        ("Burns", "right"),
        ("Ever minted", "right"),
        ("Issuance visible", "left"),
    ):
        table.add_column(column, justify=justify)  # type: ignore[arg-type]

    caveats: list[tuple[str, str]] = []
    try:
        for entry in load_defillama_registry():
            try:
                profile = source.describe_issuance(entry.ref, refresh=refresh)
            except SourceError as error:
                table.add_row(
                    entry.symbol, "[dim]not measurable[/dim]", "", "", "", str(error)[:40]
                )
                continue
            table.add_row(
                entry.symbol,
                f"{profile.transfers:,}",
                f"{profile.mints:,}",
                f"{profile.burns:,}",
                f"{profile.minted_supply:,.2f}",
                "[green]yes[/green]" if profile.issuance_is_visible else "[yellow]no[/yellow]",
            )
            note = profile.caveat()
            if note is not None:
                caveats.append((entry.symbol, note))
    finally:
        source.close()

    console.print(table)
    if caveats:
        console.print("\n[bold]Caveats[/bold]")
        for symbol, note in caveats:
            console.print(f"  [yellow]•[/yellow] [bold]{symbol}[/bold]: {note}")
    else:
        console.print(
            "\n[green]Issuance is visible for every asset measured.[/green] Each one "
            "mints through the zero address, so the primary/secondary split can see how "
            "it is issued and the secondary figures are measurements rather than upper "
            "bounds."
        )


@app.command()
def sources() -> None:
    """List the ingestion adapters and what each one can answer."""
    from rwa_liquidity.sources import (  # noqa: PLC0415 -- keeps `--version` fast
        DeFiLlamaPricesSource,
        DeFiLlamaProtocolTvlSource,
        DuneSource,
        RwaXyzSource,
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
