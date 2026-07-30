"""Computing every metric for every asset in one pass.

The individual metric functions each take the frames they need and nothing more,
which keeps them independently testable. This module is the convenience layer on
top: given the three normalized frames, it produces one row per asset with every
metric and a merged record of everything doubtful about that row.

Warnings are carried forward, not summarised away. A table of six numbers with a
footnote saying which of them are provisional is more useful than six numbers
that all look equally solid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl

from rwa_liquidity.metrics.concentration import DEFAULT_TOP_N, holder_hhi, top_holder_share
from rwa_liquidity.metrics.participation import active_holder_ratio, dormancy
from rwa_liquidity.metrics.volume import (
    total_volume,
    turnover_ratio,
    volume_per_active_address,
)
from rwa_liquidity.schema.types import Denomination, VolumeMode

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from rwa_liquidity.metrics.base import MetricResult, Window

__all__ = ["METRIC_COLUMNS", "AssetReport", "build_report", "report_frame"]

#: Column order for the output table, and the labels used when rendering it.
METRIC_COLUMNS: tuple[tuple[str, str], ...] = (
    ("turnover_ratio", "Turnover"),
    ("active_holder_ratio", "Active holders"),
    ("volume_per_active_address", "Vol / active addr"),
    ("top_10_holder_share", "Top-10 share"),
    ("holder_hhi", "HHI"),
    ("dormancy", "Dormancy"),
)


@dataclass(frozen=True, slots=True)
class AssetReport:
    """Every metric for one asset, with the caveats attached.

    Attributes:
        asset_uid: The asset measured.
        symbol: Ticker, where a source published one.
        metrics: Metric name to result, in `METRIC_COLUMNS` order.
        window: The observation period.
        mode: The volume mode applied.
    """

    asset_uid: str
    symbol: str | None
    metrics: dict[str, MetricResult]
    window: Window
    mode: VolumeMode

    def value(self, name: str) -> float | None:
        """Return one metric's value, or `None` if it is undefined."""
        result = self.metrics.get(name)
        return result.value if result is not None else None

    @property
    def warnings(self) -> tuple[str, ...]:
        """Return every distinct warning across the metrics, in a stable order."""
        seen: dict[str, None] = {}
        for result in self.metrics.values():
            for warning in result.provenance.warnings:
                seen[warning] = None
        return tuple(seen)

    @property
    def sources(self) -> tuple[str, ...]:
        """Return every source that contributed to any metric on this row."""
        labels: set[str] = set()
        for result in self.metrics.values():
            labels.update(result.provenance.sources)
        return tuple(sorted(labels))


def _for_asset(frame: pl.DataFrame, asset_uid: str) -> pl.DataFrame:
    return frame.filter(pl.col("asset_uid") == asset_uid)


def build_report(  # noqa: PLR0913 -- the three frames plus the three knobs that
    # change what the numbers mean; none has a sensible home elsewhere.
    snapshots: pl.DataFrame,
    transfers: pl.DataFrame,
    holders: pl.DataFrame,
    *,
    window: Window,
    mode: VolumeMode = VolumeMode.SECONDARY_ONLY,
    denomination: Denomination = Denomination.NATIVE,
    top_n: int = DEFAULT_TOP_N,
    exclude: Collection[str] = (),
) -> list[AssetReport]:
    """Compute every metric for every asset present in `snapshots`.

    An asset with no transfers or no holder rows still gets a row: the metrics
    that cannot be computed report themselves undefined, which is information.
    Dropping the asset would hide it.

    Args:
        snapshots: An `AssetSnapshot` frame, possibly spanning several assets.
        transfers: A `TransferEvent` frame.
        holders: A `HolderBalance` frame.
        window: The observation period.
        mode: Which transfer kinds count.
        denomination: Units for the volume-based metrics.
        top_n: How many holders the concentration share covers.
        exclude: Addresses to leave out of the holder distribution.

    Returns:
        One report per asset, ordered by asset uid.
    """
    mode = VolumeMode(mode)
    denomination = Denomination(denomination)
    reports: list[AssetReport] = []

    for asset_uid in sorted(snapshots["asset_uid"].unique().to_list()):
        asset_snapshots = _for_asset(snapshots, str(asset_uid))
        asset_transfers = _for_asset(transfers, str(asset_uid))
        asset_holders = _for_asset(holders, str(asset_uid))

        metrics: dict[str, MetricResult] = {}
        if not asset_transfers.is_empty():
            metrics["turnover_ratio"] = turnover_ratio(
                asset_transfers,
                asset_snapshots,
                window=window,
                mode=mode,
                denomination=denomination,
            )
            metrics["volume_per_active_address"] = volume_per_active_address(
                asset_transfers, window=window, mode=mode, denomination=denomination
            )
            metrics["active_holder_ratio"] = active_holder_ratio(
                asset_transfers,
                asset_snapshots,
                window=window,
                mode=mode,
                # An observed distribution beats a reported count; see
                # active_holder_ratio for why.
                holders=asset_holders if not asset_holders.is_empty() else None,
            )
            metrics["total_volume"] = total_volume(
                asset_transfers, window=window, mode=mode, denomination=denomination
            )
        if not asset_holders.is_empty():
            metrics["top_10_holder_share"] = top_holder_share(
                asset_holders, asset_snapshots, window=window, n=top_n, exclude=exclude
            )
            metrics["holder_hhi"] = holder_hhi(
                asset_holders, asset_snapshots, window=window, exclude=exclude
            )
            if not asset_transfers.is_empty():
                metrics["dormancy"] = dormancy(
                    asset_holders,
                    asset_transfers,
                    asset_snapshots,
                    window=window,
                    mode=mode,
                    exclude=exclude,
                )

        symbols = [s for s in asset_snapshots["symbol"].to_list() if s]
        reports.append(
            AssetReport(
                asset_uid=str(asset_uid),
                symbol=str(symbols[0]) if symbols else None,
                metrics=metrics,
                window=window,
                mode=mode,
            )
        )
    return reports


def report_frame(reports: Sequence[AssetReport]) -> pl.DataFrame:
    """Flatten reports into one row per asset, for export.

    Provenance does not survive the flattening beyond the source list, the
    record count and the warning count, because a CSV cell is the wrong place
    for a paragraph. The full records stay on the `AssetReport` objects.
    """
    columns = [name for name, _ in METRIC_COLUMNS]
    return pl.DataFrame(
        {
            "asset_uid": [r.asset_uid for r in reports],
            "symbol": [r.symbol for r in reports],
            "window_start": [r.window.start for r in reports],
            "window_end": [r.window.end for r in reports],
            "mode": [str(r.mode) for r in reports],
            **{name: [r.value(name) for r in reports] for name in columns},
            "sources": [", ".join(r.sources) for r in reports],
            "n_warnings": [len(r.warnings) for r in reports],
        },
        schema={
            "asset_uid": pl.String(),
            "symbol": pl.String(),
            "window_start": pl.Datetime("us", "UTC"),
            "window_end": pl.Datetime("us", "UTC"),
            "mode": pl.String(),
            **dict.fromkeys(columns, pl.Float64()),
            "sources": pl.String(),
            "n_warnings": pl.Int64(),
        },
    )
