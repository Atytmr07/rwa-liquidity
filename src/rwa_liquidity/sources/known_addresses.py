"""Known non-investor addresses: DeFi aggregation contracts and issuer treasuries.

Two different confusions, one root cause: a bare address reveals nothing about
what stands behind it.

On the **holder** side, `top_10_holder_share`, `holder_hhi` and `dormancy`
treat every address with a balance as one holder, because that is all an
`eth_getLogs` scan can see. A Uniswap pool or a lending vault is
indistinguishable from an investor's wallet at that level. This is not a
theoretical worry: counting one lending vault as a single holder reversed the
direction of a published concentration trend (`docs/findings.md`).

On the **transfer** side, `classify_transfers` reads issuance off the ERC-20
zero-address convention, which is blind to an issuer that mints one tranche
and then distributes from a treasury. Those distributions look exactly like
secondary trading, and counting them as such overstates liquidity -- the error
this package exists to prevent.

Both need information no scan can produce: a human checking a block explorer's
labels. This module reads the record of that checking. Behaviour selects
candidates; an independent label confirms them. An address that merely *looks*
like a treasury is left out, because configuring it would reclassify real
transfers on a guess.

Deliberately separate from `registry.py`: the DeFiLlama registry states what an
asset *is* and is required for every entry, while this file states what is
*known* about an asset, which is optional and grows as assets are checked by
hand. An asset absent here has not been checked, which is different from
checked and found clean.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

from rwa_liquidity.schema.asset import AssetRef, canonicalize_address

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "KnownAddressesEntry",
    "KnownAddressesError",
    "excluded_contracts",
    "issuer_addresses",
    "load_known_addresses",
]

_DATA_PACKAGE: Final = "rwa_liquidity.sources.data"
_FILE: Final = "known_addresses.toml"

#: Bumped when the file layout changes incompatibly.
_SUPPORTED_SCHEMA_VERSION: Final = 1


class KnownAddressesError(Exception):
    """The known-addresses file is missing, malformed, or of an unsupported version."""


@dataclass(frozen=True, slots=True)
class KnownAddressesEntry:
    """What is known about one asset's non-investor addresses.

    Attributes:
        ref: The canonical asset key.
        excluded_contracts: Addresses to drop from the holder distribution
            before computing concentration and dormancy metrics -- AMM pools,
            lending vaults, and similar contracts that aggregate many
            end-holders behind one balance.
        issuer_addresses: Treasury or distributor addresses whose transfers
            are primary rather than secondary, per `classify_transfers`.
        notes: Why each address is here and what is still unverified. Never
            empty -- an exclusion without a citation is indistinguishable from
            a guess.
    """

    ref: AssetRef
    excluded_contracts: tuple[str, ...]
    issuer_addresses: tuple[str, ...]
    notes: str


def _addresses(raw: Mapping[str, Any], field: str, index: int) -> tuple[str, ...]:
    value = raw.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise KnownAddressesError(
            f"{_FILE}: asset #{index + 1}'s {field!r} must be a list of strings"
        )
    return tuple(canonicalize_address(item) for item in value)


def _parse(document: Mapping[str, Any]) -> tuple[KnownAddressesEntry, ...]:
    version = document.get("schema_version")
    if version != _SUPPORTED_SCHEMA_VERSION:
        raise KnownAddressesError(
            f"{_FILE}: schema_version is {version!r}, expected {_SUPPORTED_SCHEMA_VERSION}"
        )

    assets = document.get("asset", [])
    if not isinstance(assets, list):
        raise KnownAddressesError(f"{_FILE}: [[asset]] must be a list of tables")

    entries: list[KnownAddressesEntry] = []
    seen: set[str] = set()
    for index, raw in enumerate(assets):
        if not isinstance(raw, dict):
            raise KnownAddressesError(f"{_FILE}: asset #{index + 1} is not a table")
        uid = raw.get("uid")
        if not isinstance(uid, str) or not uid.strip():
            raise KnownAddressesError(f"{_FILE}: asset #{index + 1} is missing a non-empty 'uid'")
        if uid in seen:
            raise KnownAddressesError(f"{_FILE}: duplicate entry for {uid!r}")
        seen.add(uid)
        notes = str(raw.get("notes", "")).strip()
        excluded = _addresses(raw, "excluded_contracts", index)
        issuers = _addresses(raw, "issuer_addresses", index)
        if (excluded or issuers) and not notes:
            raise KnownAddressesError(
                f"{_FILE}: {uid!r} lists addresses but has no notes explaining them"
            )
        entries.append(
            KnownAddressesEntry(
                ref=AssetRef.parse(uid),
                excluded_contracts=excluded,
                issuer_addresses=issuers,
                notes=notes,
            )
        )
    return tuple(entries)


def load_known_addresses() -> Sequence[KnownAddressesEntry]:
    """Read and validate the known-addresses file shipped with the package.

    Returns:
        Every entry in file order. May be empty.

    Raises:
        KnownAddressesError: If the file is absent, unparseable, of the wrong
            schema version, contains a duplicate or unexplained entry.
    """
    try:
        text = resources.files(_DATA_PACKAGE).joinpath(_FILE).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as error:
        raise KnownAddressesError(
            f"{_FILE} is not present in the installed package; the wheel was built "
            f"without its data files"
        ) from error

    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise KnownAddressesError(f"{_FILE} is not valid TOML: {error}") from error

    return _parse(document)


def excluded_contracts(entries: Sequence[KnownAddressesEntry]) -> frozenset[str]:
    """Flatten every entry's `excluded_contracts` into one address set.

    `build_report`'s `exclude` parameter is not per-asset -- it is applied to
    every asset in one pass -- which is safe here because contract addresses
    are globally unique: one asset's pool address will never coincide with
    another asset's holder.
    """
    return frozenset(address for entry in entries for address in entry.excluded_contracts)


def issuer_addresses(entries: Sequence[KnownAddressesEntry]) -> dict[str, tuple[str, ...]]:
    """Return each asset's `issuer_addresses`, keyed by uid, for `EvmRpcSource`."""
    return {entry.ref.uid: entry.issuer_addresses for entry in entries if entry.issuer_addresses}
