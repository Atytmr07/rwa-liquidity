"""Measuring the same assets over consecutive windows.

A single window says how liquid an asset was. It cannot say whether tokenized
markets are deepening, which is the question a reader of the cross-section asks
next.

The whole series is computed from data fetched once. The on-chain adapter walks a
token's entire history anyway, so a window a year old costs no more requests than
the current one, and supply is taken from the ledger at each window's end rather
than from today's figure -- a fund that has grown tenfold would otherwise show a
falsely collapsing turnover simply because the denominator moved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

import polars as pl

from rwa_liquidity.metrics.base import DEFAULT_WINDOW_DAYS, Window
from rwa_liquidity.metrics.report import build_report
from rwa_liquidity.schema.types import VolumeMode

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from datetime import datetime

__all__ = ["AssetTrend", "TrendPoint", "build_trend", "trend_frame", "windows_ending"]


@dataclass(frozen=True, slots=True)
class TrendPoint:
    """One metric value over one window."""

    window: Window
    value: float | None


@dataclass(frozen=True, slots=True)
class AssetTrend:
    """One asset's metric across consecutive windows, oldest first.

    Attributes:
        asset_uid: The asset measured.
        symbol: Ticker, where a source published one.
        metric: Which metric was tracked.
        mode: The volume mode applied throughout.
        points: One entry per window, oldest first.
    """

    asset_uid: str
    symbol: str | None
    metric: str
    mode: VolumeMode
    points: tuple[TrendPoint, ...]

    @property
    def values(self) -> tuple[float | None, ...]:
        """Return just the values, oldest first."""
        return tuple(point.value for point in self.points)

    @property
    def direction(self) -> str:
        """Describe the change from the first defined point to the last.

        Deliberately coarse. Six monthly observations of a thin market cannot
        support a growth rate, and quoting one would imply a precision the data
        does not have. "Rising" here means the latest defined value exceeds the
        earliest by more than a tenth of the earliest.
        """
        defined = [value for value in self.values if value is not None]
        if len(defined) < 2:  # noqa: PLR2004 -- a direction needs two points
            return "insufficient data"
        first, last = defined[0], defined[-1]
        if first == 0 and last == 0:
            return "flat at zero"
        if first == 0:
            return "rising from zero"
        change = (last - first) / abs(first)
        if change > _MATERIAL_CHANGE:
            return "rising"
        if change < -_MATERIAL_CHANGE:
            return "falling"
        return "flat"


#: Relative change below which a series is called flat. A tenth is loose, on
#: purpose: these are small counts and a tighter threshold would read noise as
#: trend.
_MATERIAL_CHANGE = 0.10


def windows_ending(
    end: datetime, *, days: int = DEFAULT_WINDOW_DAYS, periods: int = 6
) -> list[Window]:
    """Return `periods` consecutive windows of `days`, oldest first, ending at `end`.

    The windows tile without overlap because `Window` is half-open, so a transfer
    on a boundary is counted exactly once across the series.
    """
    if periods < 1:
        raise ValueError(f"periods must be at least 1, got {periods}")
    span = timedelta(days=days)
    return [
        Window(start=end - span * (index + 1), end=end - span * index)
        for index in reversed(range(periods))
    ]


def build_trend(  # noqa: PLR0913 -- the three frames, the window geometry, and
    # the two conventions that change what is being tracked.
    snapshots: pl.DataFrame,
    transfers: pl.DataFrame,
    holders: pl.DataFrame,
    *,
    windows: Sequence[Window],
    metric: str = "turnover_ratio",
    mode: VolumeMode = VolumeMode.SECONDARY_ONLY,
    unmeasured: Collection[str] = (),
) -> list[AssetTrend]:
    """Track one metric for every asset across `windows`.

    Args:
        snapshots: An `AssetSnapshot` frame. For a meaningful turnover series this
            should carry a supply figure per window end, as
            `EvmRpcSource.supply_snapshots` produces; a single current snapshot
            would divide every window by today's supply.
        transfers: A `TransferEvent` frame spanning all the windows.
        holders: A `HolderBalance` frame.
        windows: The periods to measure, oldest first.
        metric: Which metric to track, named as in `METRIC_COLUMNS`.
        mode: Which transfer kinds count.
        unmeasured: Assets whose data could not be fetched.

    Returns:
        One trend per asset, ordered by asset uid.
    """
    mode = VolumeMode(mode)
    series: dict[str, list[TrendPoint]] = {}
    symbols: dict[str, str | None] = {}

    for window in windows:
        for report in build_report(
            snapshots,
            transfers,
            holders,
            window=window,
            mode=mode,
            unmeasured=unmeasured,
        ):
            series.setdefault(report.asset_uid, []).append(
                TrendPoint(window=window, value=report.value(metric))
            )
            symbols.setdefault(report.asset_uid, report.symbol)

    return [
        AssetTrend(
            asset_uid=asset_uid,
            symbol=symbols[asset_uid],
            metric=metric,
            mode=mode,
            points=tuple(points),
        )
        for asset_uid, points in sorted(series.items())
    ]


def trend_frame(trends: Sequence[AssetTrend]) -> pl.DataFrame:
    """Flatten trends to one row per asset-window, for export."""
    rows = [
        {
            "asset_uid": trend.asset_uid,
            "symbol": trend.symbol,
            "metric": trend.metric,
            "mode": str(trend.mode),
            "window_start": point.window.start,
            "window_end": point.window.end,
            "value": point.value,
        }
        for trend in trends
        for point in trend.points
    ]
    schema = {
        "asset_uid": pl.String(),
        "symbol": pl.String(),
        "metric": pl.String(),
        "mode": pl.String(),
        "window_start": pl.Datetime("us", "UTC"),
        "window_end": pl.Datetime("us", "UTC"),
        "value": pl.Float64(),
    }
    return pl.DataFrame(rows, schema=schema) if rows else pl.DataFrame(schema=schema)
