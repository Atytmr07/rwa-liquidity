"""Volume-based metrics.

Both metrics here depend on the primary/secondary distinction, and both default
to `secondary_only`. A tokenized fund that only mints and redeems has no
secondary market, whatever its raw transfer volume looks like; defaulting to
`all` would reproduce exactly the overstatement this package exists to correct.
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
    single_asset,
    sources_of,
)
from rwa_liquidity.schema.types import Denomination, TransferKind, VolumeMode

if TYPE_CHECKING:
    from rwa_liquidity.metrics.base import Window

__all__ = ["total_volume", "turnover_ratio", "volume_per_active_address"]

_AMOUNT_COLUMN = {Denomination.NATIVE: "amount", Denomination.USD: "amount_usd"}
_DENOMINATOR_COLUMN = {
    Denomination.NATIVE: "total_supply",
    Denomination.USD: "market_value_usd",
}


def _unclassified_note(transfers: pl.DataFrame, mode: VolumeMode) -> tuple[str, ...]:
    """Warn when transfers were dropped because they could not be classified.

    Under any mode narrower than `ALL`, an unclassified transfer is excluded.
    That is the right default, but the reader has to know how much was set
    aside: an asset whose transfers are mostly unclassified has not been
    measured, it has been guessed at.
    """
    if mode is VolumeMode.ALL or transfers.is_empty():
        return ()
    unclassified = transfers.filter(pl.col("kind") == TransferKind.UNCLASSIFIED.value).height
    if unclassified == 0:
        return ()
    share = unclassified / transfers.height
    return (
        f"{unclassified} of {transfers.height} transfers ({share:.1%}) could not be "
        f"classified as primary or secondary and are excluded under mode "
        f"{mode.value!r}; the value is a lower bound on activity",
    )


def total_volume(
    transfers: pl.DataFrame,
    *,
    window: Window,
    mode: VolumeMode = VolumeMode.SECONDARY_ONLY,
    denomination: Denomination = Denomination.NATIVE,
) -> MetricResult:
    """Return the summed transfer amount over the window.

    Not one of the six headline metrics, but the numerator of two of them, so it
    is exposed with its own provenance rather than hidden inside them.

    Args:
        transfers: A `TransferEvent` frame for one asset.
        window: The observation period.
        mode: Which transfer kinds to count.
        denomination: `native` for token units, `usd` for the source's own
            dollar figures.

    Returns:
        The volume, or `None` if the chosen denomination is not populated.
    """
    # Coerce rather than trust: a raw string reaches the dict lookups intact
    # (StrEnum hashes as its value) but has no `.kinds`, so it would half-work
    # and then fail somewhere less obvious.
    mode = VolumeMode(mode)
    denomination = Denomination(denomination)
    asset_uid = single_asset(transfers, what="transfers")
    in_window = window.clip(transfers, column="block_time")
    counted = filter_by_mode(in_window, mode)
    column = _AMOUNT_COLUMN[denomination]

    provenance = Provenance(
        metric="total_volume",
        asset_uid=asset_uid,
        sources=sources_of(transfers),
        window=window,
        n_records=counted.height,
        mode=mode,
        denomination=denomination,
        exclusions=(
            f"{in_window.height - counted.height} of {in_window.height} in-window "
            f"transfers excluded by mode {mode.value!r}",
        ),
        warnings=_unclassified_note(in_window, mode),
    )

    if counted.is_empty():
        # No qualifying transfers is a real answer: the asset did not trade.
        return MetricResult(value=0.0, provenance=provenance)

    if counted[column].null_count() == counted.height:
        return MetricResult(
            value=None,
            provenance=provenance.with_warning(
                f"no {column!r} values are populated, so volume cannot be expressed "
                f"in {denomination.value}"
            ),
        )
    if counted[column].null_count() > 0:
        provenance = provenance.with_warning(
            f"{counted[column].null_count()} of {counted.height} counted transfers have "
            f"no {column!r}; they contribute nothing to the total"
        )

    return MetricResult(value=float(counted[column].sum()), provenance=provenance)


def turnover_ratio(
    transfers: pl.DataFrame,
    snapshots: pl.DataFrame,
    *,
    window: Window,
    mode: VolumeMode = VolumeMode.SECONDARY_ONLY,
    denomination: Denomination = Denomination.NATIVE,
) -> MetricResult:
    """Return transfer volume over the window divided by asset size at its end.

    The specification defines this as volume over total asset value. Two
    readings are possible and both are implemented:

    * `native` (the default) divides token volume by total supply. It needs no
      price series, so it is exactly reproducible from the transfer data alone.
    * `usd` divides dollar volume by market value. It matches the specification
      literally but inherits whatever price assumptions the source made, which
      are rarely documented and never uniform between providers.

    For a constant-NAV fund the two nearly coincide. For anything whose price
    moves they do not.

    Args:
        transfers: A `TransferEvent` frame for one asset.
        snapshots: An `AssetSnapshot` frame for the same asset.
        window: The observation period.
        mode: Which transfer kinds to count.
        denomination: Which of the two readings to compute.

    Returns:
        The ratio, or `None` if the denominator is absent or zero.
    """
    # Coerce rather than trust: a raw string reaches the dict lookups intact
    # (StrEnum hashes as its value) but has no `.kinds`, so it would half-work
    # and then fail somewhere less obvious.
    mode = VolumeMode(mode)
    denomination = Denomination(denomination)
    volume = total_volume(transfers, window=window, mode=mode, denomination=denomination)
    snapshot = latest_snapshot(snapshots, window)
    column = _DENOMINATOR_COLUMN[denomination]
    size = snapshot.get(column)

    provenance = Provenance(
        metric="turnover_ratio",
        asset_uid=volume.provenance.asset_uid,
        sources=sources_of(transfers, snapshots),
        window=window,
        n_records=volume.provenance.n_records,
        mode=mode,
        denomination=denomination,
        exclusions=volume.provenance.exclusions,
        warnings=volume.provenance.warnings,
    )

    if volume.value is None:
        return MetricResult(value=None, provenance=provenance.with_warning("volume is undefined"))
    if size is None:
        return MetricResult(
            value=None,
            provenance=provenance.with_warning(
                f"the snapshot has no {column!r}, so there is no denominator"
            ),
        )

    size_value = float(size)  # type: ignore[arg-type]
    if size_value <= 0:
        # Zero supply with non-zero volume is contradictory, so it is reported
        # as undefined rather than as an infinite or enormous ratio.
        return MetricResult(
            value=None,
            provenance=provenance.with_warning(
                f"{column} is {size_value}, so the ratio is undefined"
            ),
        )

    return MetricResult(value=volume.value / size_value, provenance=provenance)


def volume_per_active_address(
    transfers: pl.DataFrame,
    *,
    window: Window,
    mode: VolumeMode = VolumeMode.SECONDARY_ONLY,
    denomination: Denomination = Denomination.NATIVE,
) -> MetricResult:
    """Return transfer volume over the window divided by active addresses.

    An address is active if it appears on either side of a counted transfer.
    Burn addresses are not counted as participants.

    Args:
        transfers: A `TransferEvent` frame for one asset.
        window: The observation period.
        mode: Which transfer kinds to count.
        denomination: Which unit to express volume in.

    Returns:
        The ratio, or `None` if no address was active.
    """
    # Coerce rather than trust: a raw string reaches the dict lookups intact
    # (StrEnum hashes as its value) but has no `.kinds`, so it would half-work
    # and then fail somewhere less obvious.
    mode = VolumeMode(mode)
    denomination = Denomination(denomination)
    volume = total_volume(transfers, window=window, mode=mode, denomination=denomination)
    counted = filter_by_mode(window.clip(transfers, column="block_time"), mode)
    active = active_addresses(counted)

    provenance = Provenance(
        metric="volume_per_active_address",
        asset_uid=volume.provenance.asset_uid,
        sources=sources_of(transfers),
        window=window,
        n_records=counted.height,
        mode=mode,
        denomination=denomination,
        exclusions=(
            *volume.provenance.exclusions,
            "burn addresses excluded from the active address count",
        ),
        warnings=volume.provenance.warnings,
    )

    if volume.value is None:
        return MetricResult(value=None, provenance=provenance.with_warning("volume is undefined"))
    if not active:
        # Zero active addresses means the denominator does not exist, which is
        # different from every active address having moved nothing.
        return MetricResult(
            value=None,
            provenance=provenance.with_warning(
                "no addresses were active in the window, so the ratio is undefined"
            ),
        )

    return MetricResult(value=volume.value / len(active), provenance=provenance)
