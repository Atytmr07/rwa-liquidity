"""Classifying transfers as primary issuance or secondary trading.

This is the single most consequential piece of logic in the package, and it
lives on the adapter side because only an adapter knows the issuer addresses for
a given asset.

Two rules, applied in order:

1. **The zero-address rule.** A transfer out of the zero address created tokens;
   a transfer into it, or into a conventional burn address, destroyed them. Both
   are primary.
2. **The issuer rule.** Many RWA issuers do not mint per subscription. They mint
   a large tranche once and then distribute from a treasury address, so a
   subscription looks like an ordinary transfer on chain. Where the treasury
   address is known it is supplied through `issuer_addresses`, and transfers to
   or from it are primary too: an investor buying from the issuer is not buying
   from another investor.

Anything the rules cannot decide is labelled `unclassified` rather than assumed.
Assuming secondary would overstate liquidity, which is the error this package
exists to prevent.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from rwa_liquidity.schema.types import BURN_ADDRESSES, TransferKind

if TYPE_CHECKING:
    from collections.abc import Collection

__all__ = ["classify_transfers"]

logger = logging.getLogger(__name__)


def classify_transfers(
    frame: pl.DataFrame,
    *,
    issuer_addresses: Collection[str] = (),
    asset_uid: str = "",
) -> pl.DataFrame:
    """Add a `kind` column to a frame of `from_address`/`to_address` pairs.

    Args:
        frame: Rows with at least `from_address` and `to_address`.
        issuer_addresses: Treasury or distribution addresses whose transfers are
            primary rather than secondary. Case-insensitive.
        asset_uid: Included in the warning emitted when issuance is invisible.

    Returns:
        The frame with a `kind` column holding `TransferKind` values.
    """
    if frame.is_empty():
        return frame.with_columns(pl.lit(None, dtype=pl.String).alias("kind"))

    burn = list(BURN_ADDRESSES)
    issuers = [address.lower() for address in issuer_addresses]

    sender = pl.col("from_address").str.to_lowercase()
    recipient = pl.col("to_address").str.to_lowercase()

    from_burn = sender.is_in(burn)
    to_burn = recipient.is_in(burn)
    from_issuer = sender.is_in(issuers) if issuers else pl.lit(value=False)
    to_issuer = recipient.is_in(issuers) if issuers else pl.lit(value=False)

    classified = frame.with_columns(
        pl.when(from_burn & to_burn)
        # A transfer from the zero address to a burn address is not a coherent
        # event. Refusing to guess is the whole point of the fourth label.
        .then(pl.lit(TransferKind.UNCLASSIFIED.value))
        .when(from_burn | from_issuer)
        .then(pl.lit(TransferKind.MINT.value))
        .when(to_burn | to_issuer)
        .then(pl.lit(TransferKind.BURN.value))
        .otherwise(pl.lit(TransferKind.SECONDARY.value))
        .alias("kind")
    )

    _warn_if_issuance_is_invisible(classified, issuers=issuers, asset_uid=asset_uid)
    return classified


def _warn_if_issuance_is_invisible(
    classified: pl.DataFrame,
    *,
    issuers: list[str],
    asset_uid: str,
) -> None:
    """Warn when every transfer looks secondary and nothing could prove it.

    An asset whose window contains no primary activity at all is possible and
    unremarkable. An asset whose window contains no primary activity *and* for
    which no issuer address was configured is the exact shape of the failure
    this package is most exposed to: issuance routed through a treasury,
    silently counted as trading, liquidity overstated.

    It cannot be detected with certainty, so it is reported rather than acted
    upon.
    """
    if issuers:
        return
    kinds = set(classified["kind"].unique().to_list())
    if kinds == {TransferKind.SECONDARY.value}:
        logger.warning(
            "every transfer for %s classified as secondary and no issuer addresses "
            "were configured. If this asset issues from a treasury rather than the "
            "zero address, its issuance is being counted as trading and its "
            "liquidity is overstated. Supply issuer_addresses to rule this out.",
            asset_uid or "the asset",
        )
