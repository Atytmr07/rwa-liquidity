"""Known non-investor addresses: DeFi contracts and issuer/treasury addresses."""

from __future__ import annotations

from typing import Any

import pytest

from rwa_liquidity.sources.known_addresses import (
    KnownAddressesError,
    _parse,
    excluded_contracts,
    issuer_addresses,
    load_known_addresses,
)

ENTRY: dict[str, Any] = {
    "uid": "ethereum:0x1b19c19393e2d034d8ff31ff34c81252fcbbee92",
    "excluded_contracts": ["0x1dD7950c266fB1be96180a8FDb0591F70200E018"],
    "issuer_addresses": [],
    "notes": "Flux Finance: fOUSG Token, a lending vault.",
}

VALID: dict[str, Any] = {"schema_version": 1, "asset": [ENTRY]}


def test_shipped_file_loads() -> None:
    # Also proves the TOML data file made it into the wheel, which a src layout
    # plus a build backend that only collects .py files would quietly break.
    entries = load_known_addresses()
    assert entries
    assert all(entry.notes for entry in entries)


def test_shipped_file_uids_are_canonical() -> None:
    for entry in load_known_addresses():
        assert entry.ref.uid == entry.ref.uid.strip()
        assert entry.ref.chain.islower()


def test_empty_file_is_allowed() -> None:
    # Unlike the DeFiLlama registry, an empty [[asset]] list is legitimate here:
    # nothing has been checked for any asset yet is a valid starting state.
    assert _parse({"schema_version": 1, "asset": []}) == ()


def test_missing_asset_key_is_allowed() -> None:
    assert _parse({"schema_version": 1}) == ()


def test_entries_parse_into_asset_refs() -> None:
    entry = _parse(VALID)[0]
    assert entry.ref.chain == "ethereum"
    assert entry.excluded_contracts == ("0x1dd7950c266fb1be96180a8fdb0591f70200e018",)
    assert entry.issuer_addresses == ()
    assert "flux finance" in entry.notes.lower()


def test_wrong_schema_version_is_refused() -> None:
    with pytest.raises(KnownAddressesError, match="schema_version"):
        _parse({**VALID, "schema_version": 99})


def test_duplicate_asset_is_refused() -> None:
    with pytest.raises(KnownAddressesError, match="duplicate"):
        _parse({**VALID, "asset": [ENTRY, ENTRY]})


def test_addresses_without_notes_are_refused() -> None:
    # An exclusion with no citation is indistinguishable from a guess.
    incomplete = {**ENTRY, "notes": ""}
    with pytest.raises(KnownAddressesError, match="notes"):
        _parse({**VALID, "asset": [incomplete]})


def test_notes_alone_with_no_addresses_is_allowed() -> None:
    # A note-only entry (nothing excluded, no issuer found yet) is a legitimate
    # record of "checked, found nothing to flag."
    checked = {**ENTRY, "excluded_contracts": [], "notes": "checked, nothing found"}
    entry = _parse({**VALID, "asset": [checked]})[0]
    assert entry.excluded_contracts == ()


def test_excluded_contracts_flattens_across_assets() -> None:
    other = {
        "uid": "ethereum:0x01995a697752266d8e748738aaa3f06464b8350b",
        "excluded_contracts": ["0x151f7c3fB28Bc6f858d67a5e298B7b4f57592b54"],
        "notes": "Uniswap V2: CANA-AJNA pool.",
    }
    entries = _parse({**VALID, "asset": [ENTRY, other]})
    flat = excluded_contracts(entries)
    assert flat == {
        "0x1dd7950c266fb1be96180a8fdb0591f70200e018",
        "0x151f7c3fb28bc6f858d67a5e298b7b4f57592b54",
    }


def test_issuer_addresses_keys_by_uid_and_skips_empty() -> None:
    with_issuer = {
        "uid": "ethereum:0x01995a697752266d8e748738aaa3f06464b8350b",
        "issuer_addresses": ["0x000000000000000000000000000000000000dEaD"],
        "notes": "hypothetical treasury address for a test.",
    }
    entries = _parse({**VALID, "asset": [ENTRY, with_issuer]})
    mapping = issuer_addresses(entries)
    # ENTRY has no issuer_addresses, so it must not appear at all.
    assert set(mapping) == {"ethereum:0x01995a697752266d8e748738aaa3f06464b8350b"}
    assert mapping["ethereum:0x01995a697752266d8e748738aaa3f06464b8350b"] == (
        "0x000000000000000000000000000000000000dead",
    )
