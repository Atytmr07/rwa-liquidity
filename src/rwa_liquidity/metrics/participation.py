"""Participation metrics: how much of the holder base actually trades.

Both metrics take a `VolumeMode`, and both default to `secondary_only`. That is
deliberate and it is the point of the package. An address that received a mint
and never traded is dormant under this package's own thesis; if the mode filter
applied only to volume metrics, the same dataset could report an asset as fully
active and never traded at once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_liquidity.metrics.base import (
    MetricResult,
    Provenance,
    active_addresses,
    filter_by_mode,
    impossible_share,
    latest_snapshot,
    prepare_holders,
    resolve_total_supply,
    single_asset,
    sources_of,
)
from rwa_liquidity.schema.types import VolumeMode

if TYPE_CHECKING:
    from collections.abc import Collection

    from rwa_liquidity.metrics.base import Window

__all__ = ["active_holder_ratio", "dormancy"]


def active_holder_ratio(  # noqa: PLR0913 -- the two frames plus mode, and two
    # optional overrides that make the metric usable on real data: an observed
    # holder distribution, and the asset identity for an empty window.
    transfers: pl.DataFrame,
    snapshots: pl.DataFrame,
    *,
    window: Window,
    mode: VolumeMode = VolumeMode.SECONDARY_ONLY,
    holders: pl.DataFrame | None = None,
    asset_uid: str | None = None,
) -> MetricResult:
    """Return active addresses in the window over total holders at its end.

    An address is active if it appears on either side of a counted transfer.
    Burn addresses are not participants and are not counted.

    The denominator prefers an **observed** holder distribution over a reported
    count. A distribution derived from the full transfer history and checked
    against the contract's own supply is exact, whereas a provider's
    `holder_count` is a figure to be taken on faith and is frequently absent.
    Where `holders` is supplied its row count is used and the provenance says so;
    otherwise the reported count is used; if neither exists the metric is
    undefined.

    The ratio can exceed 1. That is not a bug: an address can trade during the
    window and hold nothing by the end of it, so the numerator counts people the
    denominator does not. A value above 1 is reported with a warning rather than
    clamped, because clamping would hide churn that is itself a liquidity
    signal.

    Args:
        transfers: A `TransferEvent` frame for one asset.
        snapshots: An `AssetSnapshot` frame for the same asset.
        window: The observation period.
        mode: Which transfer kinds count as activity.
        holders: An observed `HolderBalance` frame for the same asset. Preferred
            over the snapshot's reported count when present.
        asset_uid: The asset being measured, so an empty transfer frame still
            identifies the asset it describes.

    Returns:
        The ratio, or `None` if there is no denominator from either source.
    """
    # Coerce rather than trust: a raw string has no `.kinds` and would fail
    # somewhere less obvious than here.
    mode = VolumeMode(mode)
    asset_uid = single_asset(transfers, what="transfers", expected=asset_uid)
    counted = filter_by_mode(window.clip(transfers, column="block_time"), mode)
    active = active_addresses(counted)
    snapshot = latest_snapshot(snapshots, window)

    observed = holders.height if holders is not None and not holders.is_empty() else None
    reported_raw = snapshot.get("holder_count")
    reported = int(reported_raw) if reported_raw is not None else None  # type: ignore[call-overload]

    provenance = Provenance(
        metric="active_holder_ratio",
        asset_uid=asset_uid,
        sources=sources_of(transfers, snapshots)
        if holders is None
        else sources_of(transfers, snapshots, holders),
        window=window,
        n_records=counted.height,
        mode=mode,
        exclusions=("burn addresses excluded from the active address count",),
    )

    denominator = observed if observed is not None else reported
    if denominator is None:
        return MetricResult(
            value=None,
            provenance=provenance.with_warning(
                "no holder distribution was observed and no source reported a "
                "holder_count, so there is no denominator"
            ),
        )
    if observed is not None:
        provenance = provenance.with_warning(
            f"the denominator is the {observed} holders actually observed, not a "
            f"reported count"
            + (
                f"; the reported count was {reported}"
                if reported is not None and reported != observed
                else ""
            )
        )
    if denominator <= 0:
        return MetricResult(
            value=None,
            provenance=provenance.with_warning(
                f"the holder count is {denominator}, so the ratio is undefined"
            ),
        )

    ratio = len(active) / denominator
    if ratio > 1:
        provenance = provenance.with_warning(
            f"{len(active)} addresses were active but only {denominator} hold the asset at "
            f"the end of the window; addresses that traded out are counted in the "
            f"numerator and not the denominator"
        )
    return MetricResult(value=ratio, provenance=provenance)


def dormancy(  # noqa: PLR0913 -- dormancy is a join across all three normalized
    # frames by definition: who holds, who moved, and how much exists. Bundling
    # them into a container would only move the argument count elsewhere.
    holders: pl.DataFrame,
    transfers: pl.DataFrame,
    snapshots: pl.DataFrame,
    *,
    window: Window,
    mode: VolumeMode = VolumeMode.SECONDARY_ONLY,
    exclude: Collection[str] = (),
) -> MetricResult:
    """Return the share of supply held by addresses that did not transfer.

    Under the default `secondary_only` mode, an address that received a mint and
    never traded counts as dormant. That is the intended reading: taking
    delivery of an issuance is not market participation.

    Args:
        holders: A `HolderBalance` frame for one asset.
        transfers: A `TransferEvent` frame for the same asset.
        snapshots: An `AssetSnapshot` frame for the same asset.
        window: The observation period.
        mode: Which transfer kinds count as activity.
        exclude: Addresses to leave out of the holder distribution.

    Returns:
        The share in `[0, 1]`, or `None` if there are no holders.
    """
    # Coerce rather than trust: a raw string has no `.kinds` and would fail
    # somewhere less obvious than here.
    mode = VolumeMode(mode)
    asset_uid = single_asset(holders, what="holders")
    kept, notes = prepare_holders(holders, exclude)
    total, warnings = resolve_total_supply(kept, snapshots, window)

    counted = filter_by_mode(window.clip(transfers, column="block_time"), mode)
    active = active_addresses(counted)

    provenance = Provenance(
        metric="dormancy",
        asset_uid=asset_uid,
        sources=sources_of(holders, transfers, snapshots),
        window=window,
        n_records=kept.height,
        mode=mode,
        exclusions=tuple(notes),
        warnings=tuple(warnings),
    )

    if kept.is_empty() or total <= 0:
        return MetricResult(
            value=None,
            provenance=provenance.with_warning("no holders remain after exclusions"),
        )

    # Address comparison is case-insensitive because a source may report EIP-55
    # checksummed addresses in one frame and lowercase in another; a case
    # mismatch would silently mark every active holder dormant.
    active_lower = [address.lower() for address in active]
    dormant = kept.filter(~pl.col("address").str.to_lowercase().is_in(active_lower))

    share = float(dormant["balance"].sum()) / total
    problem = impossible_share(share, what="dormancy")
    if problem is not None:
        return MetricResult(value=None, provenance=provenance.with_warning(problem))
    return MetricResult(value=share, provenance=provenance)
