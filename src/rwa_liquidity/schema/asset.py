"""Canonical asset identity.

Every source names assets differently: rwa.xyz has its own IDs, DeFiLlama has
protocol slugs, on-chain data has contract addresses. Reconciliation is only
possible if all of them can be reduced to one key, so the package defines that
key here and every adapter is responsible for producing it.

The key is `chain:address` because a token contract address is the only
identifier that all on-chain sources agree on and that no provider can redefine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

__all__ = ["AssetRef", "InvalidAssetRefError", "canonicalize_address"]

_UID_SEPARATOR: Final = ":"

# EVM addresses are 20 hex bytes and case-insensitive; mixed case only ever
# carries an EIP-55 checksum, which is not part of the identity. Anything that
# does not match this shape is left alone -- Solana and Stellar addresses are
# base58/base32 and ARE case-sensitive, so lowercasing them would corrupt them.
# Detecting the format from the address itself avoids maintaining a chain list
# that would silently rot as new networks are added.
_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


class InvalidAssetRefError(ValueError):
    """Raised when a chain or address cannot form a canonical asset key."""


def canonicalize_address(address: str) -> str:
    """Normalize a token contract address for use in the canonical key.

    EVM addresses are lowercased because their case is a checksum, not identity.
    Addresses in any other format are returned with case intact.

    Args:
        address: A contract address as reported by some source.

    Returns:
        The address in canonical form.

    Raises:
        InvalidAssetRefError: If the address is empty or contains whitespace or
            the reserved separator character.
    """
    cleaned = address.strip()
    if not cleaned:
        raise InvalidAssetRefError("address must not be empty")
    if _UID_SEPARATOR in cleaned:
        raise InvalidAssetRefError(
            f"address must not contain {_UID_SEPARATOR!r}, which separates the "
            f"chain from the address in an asset uid: {address!r}"
        )
    if any(character.isspace() for character in cleaned):
        raise InvalidAssetRefError(f"address must not contain whitespace: {address!r}")
    if _EVM_ADDRESS.match(cleaned):
        return cleaned.lower()
    return cleaned


@dataclass(frozen=True, slots=True)
class AssetRef:
    """A chain-and-contract pair that identifies one tokenized asset.

    Instances are normalized on construction, so two references built from
    differently-cased inputs compare equal and hash identically.

    Attributes:
        chain: Lowercased network name, e.g. `ethereum`, `stellar`.
        address: Canonical token contract address on that chain.
    """

    chain: str
    address: str

    def __post_init__(self) -> None:
        """Normalize the fields in place on a frozen dataclass."""
        chain = self.chain.strip().lower()
        if not chain:
            raise InvalidAssetRefError("chain must not be empty")
        if _UID_SEPARATOR in chain:
            raise InvalidAssetRefError(f"chain must not contain {_UID_SEPARATOR!r}: {self.chain!r}")
        if any(character.isspace() for character in chain):
            raise InvalidAssetRefError(f"chain must not contain whitespace: {self.chain!r}")

        # object.__setattr__ is the standard escape hatch for normalizing a
        # frozen dataclass: __post_init__ runs before the instance is handed to
        # the caller, so the value is never observed in its un-normalized form.
        object.__setattr__(self, "chain", chain)
        object.__setattr__(self, "address", canonicalize_address(self.address))

    @property
    def uid(self) -> str:
        """Return the canonical string key, e.g. `ethereum:0xabc...`."""
        return f"{self.chain}{_UID_SEPARATOR}{self.address}"

    @classmethod
    def parse(cls, uid: str) -> AssetRef:
        """Build a reference from a canonical `chain:address` string.

        Args:
            uid: A canonical asset key.

        Returns:
            The parsed reference.

        Raises:
            InvalidAssetRefError: If `uid` is not exactly one chain and one
                address separated by a colon.
        """
        parts = uid.split(_UID_SEPARATOR)
        if len(parts) != 2:  # noqa: PLR2004 -- a uid has exactly two components
            raise InvalidAssetRefError(
                f"asset uid must be 'chain{_UID_SEPARATOR}address', got {uid!r}"
            )
        chain, address = parts
        return cls(chain=chain, address=address)

    def __str__(self) -> str:
        """Return the canonical uid, so f-strings and logs stay readable."""
        return self.uid
