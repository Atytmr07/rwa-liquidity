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

from rwa_liquidity.metrics.base import MetricResult, Window, latest_holders
from rwa_liquidity.metrics.concentration import (
    DEFAULT_TOP_N,
    holder_hhi,
    holder_hhi_conditional,
    retained_coverage,
    top_holder_share,
    top_holder_share_conditional,
)
from rwa_liquidity.metrics.participation import active_holder_ratio, dormancy
from rwa_liquidity.metrics.volume import (
    total_volume,
    turnover_ratio,
    volume_per_active_address,
)
from rwa_liquidity.schema.types import Denomination, VolumeMode

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

__all__ = [
    "COVERAGE_COLUMNS",
    "METRIC_COLUMNS",
    "AssetReport",
    "build_report",
    "report_frame",
]

#: Column order for the output table, and the labels used when rendering it.
METRIC_COLUMNS: tuple[tuple[str, str], ...] = (
    ("turnover_ratio", "Turnover"),
    ("active_holder_ratio", "Active holders"),
    ("volume_per_active_address", "Vol / active addr"),
    ("top_10_holder_share", "Top-10 share"),
    ("holder_hhi", "HHI"),
    ("dormancy", "Dormancy"),
)

#: Exported alongside `METRIC_COLUMNS` but kept out of the terminal table. They
#: separate the two ways concentration can move after an exclusion: the share
#: of supply the retained addresses represent, and how concentrated those
#: addresses are among themselves.
COVERAGE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("retained_coverage", "Retained coverage"),
    ("top_10_holder_share_conditional", "Top-10 share (retained)"),
    ("holder_hhi_conditional", "HHI (retained)"),
)

#: Metrics derived from the holder distribution, withheld when that
#: distribution failed to reconcile against total supply.
_HOLDER_METRICS: frozenset[str] = frozenset(
    {
        "active_holder_ratio",
        "top_10_holder_share",
        "holder_hhi",
        "dormancy",
        "retained_coverage",
        "top_10_holder_share_conditional",
        "holder_hhi_conditional",
    }
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
        notes: Report-level caveats that belong to no single metric, such as the
            asset's data having failed to load at all.
        reconciled: Whether the holder distribution matched total supply
            (`True`), did not (`False`), or was not checked (`None`).
        dropped_transfers: Transfers discarded as impossible before any metric
            was computed, or `None` where the source does not report it.
        blocks: `(first_block, last_block, read_block)` for the window, or
            `None` where the data did not come from a node.
    """

    asset_uid: str
    symbol: str | None
    metrics: dict[str, MetricResult]
    window: Window
    mode: VolumeMode
    notes: tuple[str, ...] = ()
    reconciled: bool | None = None
    dropped_transfers: int | None = None
    blocks: tuple[int, int, int] | None = None

    def value(self, name: str) -> float | None:
        """Return one metric's value, or `None` if it is undefined."""
        result = self.metrics.get(name)
        return result.value if result is not None else None

    @property
    def warnings(self) -> tuple[str, ...]:
        """Return every distinct caveat on this row, in a stable order."""
        seen: dict[str, None] = dict.fromkeys(self.notes)
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


def _holders_for_window(holders: pl.DataFrame, window: Window) -> pl.DataFrame | None:
    """Return the distribution belonging to `window`, or `None` if there is none.

    The active-holder denominator has to count the same set of holders the
    concentration metrics use, or the two would describe different moments.
    """
    selected = latest_holders(holders, window)
    return None if selected.is_empty() else selected


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
    exclude: Mapping[str, Collection[str]] | None = None,
    unmeasured: Collection[str] = (),
    missing: Mapping[str, Sequence[str]] | None = None,
    reconciliation: Mapping[str, bool | None] | None = None,
    dropped_transfers: Mapping[str, int] | None = None,
    blocks: tuple[int, int, int] | None = None,
) -> list[AssetReport]:
    """Compute every metric for every asset present in `snapshots` or `unmeasured`.

    An asset with no transfers or no holder rows still gets a row: the metrics
    that cannot be computed report themselves undefined, which is information.
    Dropping the asset would hide it. The same is true of an asset absent from
    `snapshots` altogether -- a caller that lost every fetch for it (a total
    outage, say) still owes it a row, or the report silently shrinks to
    whatever fraction of the registry happened to answer, with nothing to
    signal that the rest went missing.

    Args:
        snapshots: An `AssetSnapshot` frame, possibly spanning several assets.
        transfers: A `TransferEvent` frame.
        holders: A `HolderBalance` frame.
        window: The observation period.
        mode: Which transfer kinds count.
        denomination: Units for the volume-based metrics.
        top_n: How many holders the concentration share covers.
        exclude: Addresses to leave out of the holder distribution, per asset
            uid. An address listed for one asset is not excluded from another.
        unmeasured: Assets whose data could not be fetched. Their metrics are
            left undefined rather than computed from an empty frame, because an
            empty frame otherwise reads as "did not trade" -- a finding this
            package must not manufacture from a failed request. Included in
            the report even when `snapshots` has no rows for them at all.
        missing: Per asset, which kinds of data could not be fetched
            (`"transfers"`, `"holders"`). Every asset named here is treated as
            unmeasured, and its note says what is missing.
        reconciliation: Per asset, whether its holder distribution matched
            total supply. Where it did not (`False`), every holder-derived metric
            is reported undefined; where it was not checked (`None`), the
            metrics are computed and carry a warning saying so.
        dropped_transfers: Per asset, transfers discarded as impossible.
        blocks: `(first_block, last_block, read_block)` for `window`, recorded
            on every row so the figures can be recomputed from the same blocks.

    Returns:
        One report per asset, ordered by asset uid.
    """
    mode = VolumeMode(mode)
    denomination = Denomination(denomination)
    missing = dict(missing or {})
    reconciliation = dict(reconciliation or {})
    dropped_transfers = dict(dropped_transfers or {})
    exclude = dict(exclude or {})
    unknown = set(unmeasured) | set(missing)
    reports: list[AssetReport] = []

    # unknown is unioned in rather than only consulted per-row: an asset
    # missing from snapshots entirely -- every fetch for it failed -- must
    # still surface here, or a bad enough outage silently empties the report
    # instead of naming what it could not reach.
    known_uids = {str(uid) for uid in snapshots["asset_uid"].unique().to_list()}
    for asset_uid in sorted(known_uids | unknown):
        asset_snapshots = _for_asset(snapshots, str(asset_uid))
        asset_transfers = _for_asset(transfers, str(asset_uid))
        asset_holders = _for_asset(holders, str(asset_uid))
        asset_exclude = exclude.get(str(asset_uid), ())

        if str(asset_uid) in unknown:
            symbols = [s for s in asset_snapshots["symbol"].to_list() if s]
            kinds = missing.get(str(asset_uid))
            what = " and ".join(kinds) if kinds else "transfer or holder"
            reports.append(
                AssetReport(
                    asset_uid=str(asset_uid),
                    symbol=str(symbols[0]) if symbols else None,
                    metrics={},
                    window=window,
                    mode=mode,
                    notes=(
                        f"{what} data could not be fetched for this asset, so nothing "
                        f"about its activity is known. This is not the same as having "
                        f"measured no activity.",
                    ),
                    reconciled=reconciliation.get(str(asset_uid)),
                    dropped_transfers=dropped_transfers.get(str(asset_uid)),
                    blocks=blocks,
                )
            )
            continue

        metrics: dict[str, MetricResult] = {}
        # Computed even when the transfer frame is empty: an asset that did not
        # move has a turnover of zero, and that is the finding this package
        # exists to surface. Skipping it would report the quietest assets --
        # exactly the interesting ones -- as unmeasured.
        metrics["turnover_ratio"] = turnover_ratio(
            asset_transfers,
            asset_snapshots,
            window=window,
            mode=mode,
            denomination=denomination,
            asset_uid=str(asset_uid),
        )
        metrics["volume_per_active_address"] = volume_per_active_address(
            asset_transfers,
            window=window,
            mode=mode,
            denomination=denomination,
            asset_uid=str(asset_uid),
        )
        metrics["active_holder_ratio"] = active_holder_ratio(
            asset_transfers,
            asset_snapshots,
            window=window,
            mode=mode,
            # An observed distribution beats a reported count; see
            # active_holder_ratio for why.
            holders=_holders_for_window(asset_holders, window),
            asset_uid=str(asset_uid),
        )
        metrics["total_volume"] = total_volume(
            asset_transfers,
            window=window,
            mode=mode,
            denomination=denomination,
            asset_uid=str(asset_uid),
        )
        if not asset_holders.is_empty():
            metrics["top_10_holder_share"] = top_holder_share(
                asset_holders, asset_snapshots, window=window, n=top_n, exclude=asset_exclude
            )
            metrics["holder_hhi"] = holder_hhi(
                asset_holders, asset_snapshots, window=window, exclude=asset_exclude
            )
            # No transfer guard here either. Dormancy takes its asset identity
            # from the holder frame, and holders with no transfers at all are
            # entirely dormant -- a share of 1.0, which is the strongest finding
            # this metric can report rather than a gap in the data.
            metrics["dormancy"] = dormancy(
                asset_holders,
                asset_transfers,
                asset_snapshots,
                window=window,
                mode=mode,
                exclude=asset_exclude,
            )
            metrics["retained_coverage"] = retained_coverage(
                asset_holders, asset_snapshots, window=window, exclude=asset_exclude
            )
            metrics["top_10_holder_share_conditional"] = top_holder_share_conditional(
                asset_holders, asset_snapshots, window=window, n=top_n, exclude=asset_exclude
            )
            metrics["holder_hhi_conditional"] = holder_hhi_conditional(
                asset_holders, asset_snapshots, window=window, exclude=asset_exclude
            )

        reconciled = reconciliation.get(str(asset_uid))
        if reconciled is False:
            metrics = {
                name: _withheld(result) if name in _HOLDER_METRICS else result
                for name, result in metrics.items()
            }
        elif reconciled is None and str(asset_uid) in reconciliation:
            metrics = {
                name: _unverified(result) if name in _HOLDER_METRICS else result
                for name, result in metrics.items()
            }

        symbols = [s for s in asset_snapshots["symbol"].to_list() if s]
        reports.append(
            AssetReport(
                asset_uid=str(asset_uid),
                symbol=str(symbols[0]) if symbols else None,
                metrics=metrics,
                window=window,
                mode=mode,
                reconciled=reconciled,
                dropped_transfers=dropped_transfers.get(str(asset_uid)),
                blocks=blocks,
            )
        )
    return reports


def _withheld(result: MetricResult) -> MetricResult:
    """Return `result` as undefined, because its holder distribution failed to reconcile."""
    return MetricResult(
        value=None,
        provenance=result.provenance.with_warning(
            "the reconstructed holder distribution does not reconcile with total "
            "supply (missing transfers, negative balances, or balances that change "
            "without a Transfer event), so this holder-derived metric is withheld"
        ),
    )


def _unverified(result: MetricResult) -> MetricResult:
    """Return `result` with a warning that its holder distribution was not checked."""
    return MetricResult(
        value=result.value,
        provenance=result.provenance.with_warning(
            "the holder distribution could not be checked against total supply at "
            "the block it was reconstructed to"
        ),
    )


def report_frame(reports: Sequence[AssetReport]) -> pl.DataFrame:
    """Flatten reports into one row per asset, for export.

    Provenance does not survive the flattening beyond the source list, the
    record count and the warning count, because a CSV cell is the wrong place
    for a paragraph. The full records stay on the `AssetReport` objects. The
    block columns identify exactly which blocks a row was computed from, so the
    same figures can be recomputed later.
    """
    columns = [name for name, _ in (*METRIC_COLUMNS, *COVERAGE_COLUMNS)]
    return pl.DataFrame(
        {
            "asset_uid": [r.asset_uid for r in reports],
            "symbol": [r.symbol for r in reports],
            "window_start": [r.window.start for r in reports],
            "window_end": [r.window.end for r in reports],
            "start_block": [r.blocks[0] if r.blocks else None for r in reports],
            "end_block": [r.blocks[1] if r.blocks else None for r in reports],
            "head_block": [r.blocks[2] if r.blocks else None for r in reports],
            "mode": [str(r.mode) for r in reports],
            **{name: [r.value(name) for r in reports] for name in columns},
            "reconciled": [r.reconciled for r in reports],
            "dropped_transfers": [r.dropped_transfers for r in reports],
            "sources": [", ".join(r.sources) for r in reports],
            "n_warnings": [len(r.warnings) for r in reports],
        },
        schema={
            "asset_uid": pl.String(),
            "symbol": pl.String(),
            "window_start": pl.Datetime("us", "UTC"),
            "window_end": pl.Datetime("us", "UTC"),
            "start_block": pl.Int64(),
            "end_block": pl.Int64(),
            "head_block": pl.Int64(),
            "mode": pl.String(),
            **dict.fromkeys(columns, pl.Float64()),
            "reconciled": pl.Boolean(),
            "dropped_transfers": pl.Int64(),
            "sources": pl.String(),
            "n_warnings": pl.Int64(),
        },
    )
