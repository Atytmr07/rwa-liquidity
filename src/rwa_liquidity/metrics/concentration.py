"""Concentration metrics over the holder distribution.

Both metrics here share one hazard: a provider that returns only the top N
holders makes them look better than they are. Shares are computed against total
supply, so a truncated list produces shares that sum to less than one, and HHI
comes out biased downward. That cannot be corrected, only disclosed, so both
metrics compare the rows they received against the reported holder count and
warn when they disagree.

Issuer treasury, bridge, and custody addresses are **included by default**.
Excluding them would bury an editorial judgement inside a published number;
including them is wrong in a way the reader can see and correct with the
`exclude` argument, which is recorded in the provenance when used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import polars as pl

from rwa_liquidity.metrics.base import (
    MetricInputError,
    MetricResult,
    Provenance,
    impossible_share,
    prepare_holders,
    resolve_total_supply,
    single_asset,
    sources_of,
)

if TYPE_CHECKING:
    from collections.abc import Collection

    from rwa_liquidity.metrics.base import Window

__all__ = ["DEFAULT_TOP_N", "HHI_SCALE", "holder_hhi", "top_holder_share"]

#: The specification's top-10 share.
DEFAULT_TOP_N: Final = 10

#: HHI is conventionally reported on 0-10,000 rather than 0-1, so that a
#: two-firm market reads as 5,000 rather than 0.5.
HHI_SCALE: Final = 10_000


def top_holder_share(
    holders: pl.DataFrame,
    snapshots: pl.DataFrame,
    *,
    window: Window,
    n: int = DEFAULT_TOP_N,
    exclude: Collection[str] = (),
) -> MetricResult:
    """Return the share of total supply held by the `n` largest addresses.

    Args:
        holders: A `HolderBalance` frame for one asset.
        snapshots: An `AssetSnapshot` frame for the same asset.
        window: The observation period; the snapshot at its end is used.
        n: How many of the largest holders to count. Defaults to 10.
        exclude: Addresses to leave out, e.g. a known issuer treasury. Recorded
            in the provenance when supplied.

    Returns:
        The share in `[0, 1]`, or `None` if there are no holders to rank.

    Raises:
        MetricInputError: If `n` is not positive, or supply is non-positive.
    """
    if n <= 0:
        raise MetricInputError(f"n must be positive, got {n}")

    asset_uid = single_asset(holders, what="holders")
    kept, notes = prepare_holders(holders, exclude)
    total, warnings = resolve_total_supply(kept, snapshots, window)

    provenance = Provenance(
        metric="top_holder_share",
        asset_uid=asset_uid,
        sources=sources_of(holders, snapshots),
        window=window,
        n_records=kept.height,
        exclusions=tuple(notes),
        warnings=tuple(warnings),
    )

    if kept.is_empty() or total <= 0:
        return MetricResult(
            value=None,
            provenance=provenance.with_warning("no holders remain after exclusions"),
        )

    if kept.height < n:
        provenance = provenance.with_warning(
            f"only {kept.height} holders are known, fewer than the {n} requested; "
            f"the share covers all of them"
        )

    top = float(kept.sort("balance", descending=True).head(n)["balance"].sum())
    share = top / total
    problem = impossible_share(share, what=f"the top-{n} holder share")
    if problem is not None:
        return MetricResult(value=None, provenance=provenance.with_warning(problem))
    return MetricResult(value=share, provenance=provenance)


def holder_hhi(
    holders: pl.DataFrame,
    snapshots: pl.DataFrame,
    *,
    window: Window,
    exclude: Collection[str] = (),
) -> MetricResult:
    """Return the Herfindahl-Hirschman index of holder balances, on 0-10,000.

    Each holder's share of total supply is squared and the squares are summed,
    then scaled by 10,000. A single holder owning everything scores 10,000; ten
    equal holders score 1,000.

    Args:
        holders: A `HolderBalance` frame for one asset.
        snapshots: An `AssetSnapshot` frame for the same asset.
        window: The observation period; the snapshot at its end is used.
        exclude: Addresses to leave out, recorded in the provenance.

    Returns:
        The index, or `None` if there are no holders.

    Raises:
        MetricInputError: If total supply is non-positive.
    """
    asset_uid = single_asset(holders, what="holders")
    kept, notes = prepare_holders(holders, exclude)
    total, warnings = resolve_total_supply(kept, snapshots, window)

    provenance = Provenance(
        metric="holder_hhi",
        asset_uid=asset_uid,
        sources=sources_of(holders, snapshots),
        window=window,
        n_records=kept.height,
        exclusions=tuple(notes),
        warnings=tuple(warnings),
    )

    if kept.is_empty() or total <= 0:
        return MetricResult(
            value=None,
            provenance=provenance.with_warning("no holders remain after exclusions"),
        )

    # One address can appear once per snapshot by the schema's uniqueness rule,
    # so balances are squared directly without needing to be grouped first.
    squared_shares = (kept["balance"] / total) ** 2
    index = float(squared_shares.sum())
    # HHI is a sum of squared shares, so it is bounded by 1 for the same reason a
    # share is; scaled, that is HHI_SCALE.
    problem = impossible_share(index, what="the holder HHI")
    if problem is not None:
        return MetricResult(value=None, provenance=provenance.with_warning(problem))
    return MetricResult(value=index * HHI_SCALE, provenance=provenance)
