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


def active_holder_ratio(
    transfers: pl.DataFrame,
    snapshots: pl.DataFrame,
    *,
    window: Window,
    mode: VolumeMode = VolumeMode.SECONDARY_ONLY,
) -> MetricResult:
    """Return active addresses in the window over total holders at its end.

    An address is active if it appears on either side of a counted transfer.
    Burn addresses are not participants and are not counted.

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

    Returns:
        The ratio, or `None` if no holder count was reported.
    """
    # Coerce rather than trust: a raw string has no `.kinds` and would fail
    # somewhere less obvious than here.
    mode = VolumeMode(mode)
    asset_uid = single_asset(transfers, what="transfers")
    counted = filter_by_mode(window.clip(transfers, column="block_time"), mode)
    active = active_addresses(counted)
    snapshot = latest_snapshot(snapshots, window)

    provenance = Provenance(
        metric="active_holder_ratio",
        asset_uid=asset_uid,
        sources=sources_of(transfers, snapshots),
        window=window,
        n_records=counted.height,
        mode=mode,
        exclusions=("burn addresses excluded from the active address count",),
    )

    reported = snapshot.get("holder_count")
    if reported is None:
        return MetricResult(
            value=None,
            provenance=provenance.with_warning(
                "the snapshot reports no holder_count, so there is no denominator"
            ),
        )

    holders = int(reported)  # type: ignore[call-overload]
    if holders <= 0:
        return MetricResult(
            value=None,
            provenance=provenance.with_warning(
                f"holder_count is {holders}, so the ratio is undefined"
            ),
        )

    ratio = len(active) / holders
    if ratio > 1:
        provenance = provenance.with_warning(
            f"{len(active)} addresses were active but only {holders} hold the asset at "
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

    return MetricResult(
        value=float(dormant["balance"].sum()) / total,
        provenance=provenance,
    )
