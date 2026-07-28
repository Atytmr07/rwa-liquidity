"""Canonical asset identity."""

from __future__ import annotations

import pytest

from rwa_liquidity.schema.asset import AssetRef, InvalidAssetRefError, canonicalize_address

CHECKSUMMED = "0x7712C34205737192402172409a8F7ccef8aA2AEc"
LOWERCASED = "0x7712c34205737192402172409a8f7ccef8aa2aec"

# A real Solana mint address. Base58 is case-sensitive, so this must survive
# canonicalization untouched.
SOLANA_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def test_evm_address_is_lowercased() -> None:
    # EIP-55 mixed case is a checksum, not part of the identity.
    assert canonicalize_address(CHECKSUMMED) == LOWERCASED


def test_non_evm_address_keeps_its_case() -> None:
    # Lowercasing a base58 address would produce a different, invalid address.
    assert canonicalize_address(SOLANA_MINT) == SOLANA_MINT


def test_differently_cased_evm_refs_are_the_same_asset() -> None:
    assert AssetRef("Ethereum", CHECKSUMMED) == AssetRef("ethereum", LOWERCASED)


def test_refs_are_hashable_so_they_can_key_a_dict() -> None:
    seen = {AssetRef("ethereum", CHECKSUMMED): "buidl"}
    assert seen[AssetRef("ETHEREUM", LOWERCASED)] == "buidl"


def test_uid_round_trips() -> None:
    ref = AssetRef("ethereum", CHECKSUMMED)
    assert ref.uid == f"ethereum:{LOWERCASED}"
    assert AssetRef.parse(ref.uid) == ref


def test_solana_uid_round_trips_without_losing_case() -> None:
    ref = AssetRef("solana", SOLANA_MINT)
    assert AssetRef.parse(ref.uid).address == SOLANA_MINT


@pytest.mark.parametrize(
    ("chain", "address"),
    [
        ("", LOWERCASED),
        ("   ", LOWERCASED),
        ("ethereum", ""),
        ("ether eum", LOWERCASED),
        ("ethereum", "0xab cd"),
        ("ether:eum", LOWERCASED),
        ("ethereum", "0x:abcd"),
    ],
)
def test_malformed_components_are_rejected(chain: str, address: str) -> None:
    with pytest.raises(InvalidAssetRefError):
        AssetRef(chain, address)


@pytest.mark.parametrize("uid", ["ethereum", "a:b:c", "", "ethereum:"])
def test_malformed_uid_is_rejected(uid: str) -> None:
    with pytest.raises(InvalidAssetRefError):
        AssetRef.parse(uid)


def test_str_is_the_uid_so_log_messages_stay_readable() -> None:
    assert f"{AssetRef('ethereum', LOWERCASED)}" == f"ethereum:{LOWERCASED}"
