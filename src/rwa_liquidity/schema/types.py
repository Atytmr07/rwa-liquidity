"""Enumerations shared across the normalized data model.

These are the vocabulary the rest of the package is written in. They live here
rather than next to their consumers because adapters, metrics, and reconcile all
need to agree on them.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "BURN_ADDRESSES",
    "ZERO_ADDRESS",
    "Denomination",
    "TransferKind",
    "VolumeMode",
]

# The canonical EVM null address. A transfer out of it is an issuance; a
# transfer into it is a redemption. Both are primary activity, not trading.
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# Addresses that are conventionally used to destroy tokens on EVM chains when a
# contract does not burn to the zero address. Tokens sent here are unrecoverable
# in practice, so a transfer to one of them is treated as a redemption.
BURN_ADDRESSES = frozenset(
    {
        ZERO_ADDRESS,
        "0x000000000000000000000000000000000000dead",
    }
)


class TransferKind(StrEnum):
    """How a transfer relates to the primary market.

    The distinction between primary issuance and secondary trading is the
    central methodological claim of this package. A tokenized fund that only
    mints and redeems has no secondary market, however large its raw transfer
    volume looks.
    """

    MINT = "mint"
    """Tokens created: issuance from the zero address or a designated issuer."""

    BURN = "burn"
    """Tokens destroyed: redemption to the zero address or a burn address."""

    SECONDARY = "secondary"
    """A transfer between two addresses that are neither issuer nor burn."""

    UNCLASSIFIED = "unclassified"
    """Classification was not possible with the information available.

    This exists so that ambiguous transfers are never silently counted as
    secondary trading, which would overstate liquidity in exactly the way this
    package sets out to avoid. Metrics report the unclassified share in their
    provenance record so the reader can judge how much it matters.
    """

    @classmethod
    def primary(cls) -> frozenset[TransferKind]:
        """Return the kinds that constitute primary-market activity."""
        return frozenset({cls.MINT, cls.BURN})


class VolumeMode(StrEnum):
    """Which transfer kinds a volume-based metric should count."""

    ALL = "all"
    """Every classified transfer, including issuance and redemption."""

    SECONDARY_ONLY = "secondary_only"
    """Only transfers between holders. The default, and the honest measure."""

    PRIMARY_ONLY = "primary_only"
    """Only issuance and redemption. Useful for characterising an asset that
    turns out to have no secondary market at all."""

    @property
    def kinds(self) -> frozenset[TransferKind]:
        """Return the transfer kinds included under this mode.

        `UNCLASSIFIED` is included only under `ALL`. Assigning it to either the
        primary or the secondary bucket would be a guess, and guessing in the
        secondary direction is the specific error this package exists to avoid.
        """
        match self:
            case VolumeMode.ALL:
                return frozenset(TransferKind)
            case VolumeMode.SECONDARY_ONLY:
                return frozenset({TransferKind.SECONDARY})
            case VolumeMode.PRIMARY_ONLY:
                return TransferKind.primary()


class Denomination(StrEnum):
    """The unit a value-based metric is expressed in."""

    NATIVE = "native"
    """Token units. Requires no price series, so it is exactly reproducible."""

    USD = "usd"
    """US dollars, as reported by the source. Depends on the source's own price
    assumptions, which are rarely documented and never uniform across sources."""
