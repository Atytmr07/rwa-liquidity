"""The hand-maintained asset registry."""

from __future__ import annotations

from typing import Any

import pytest

from rwa_liquidity.sources.registry import RegistryError, _parse, load_defillama_registry

ENTRY: dict[str, Any] = {
    "uid": "ethereum:0x7712c34205737192402172409a8f7ccef8aa2aec",
    "symbol": "BUIDL",
    "name": "BlackRock USD Institutional Digital Liquidity Fund",
    "defillama_slug": "blackrock-buidl",
    "defillama_chain": "Ethereum",
    "notes": "multi-chain protocol",
}

VALID: dict[str, Any] = {"schema_version": 1, "asset": [ENTRY]}


def test_shipped_registry_loads() -> None:
    # Also proves the TOML data file made it into the wheel, which a src layout
    # plus a build backend that only collects .py files would quietly break.
    entries = load_defillama_registry()
    assert entries
    assert all(entry.defillama_slug for entry in entries)


def test_shipped_registry_uids_are_canonical() -> None:
    # AssetRef normalizes on construction, so a uid that changes when parsed was
    # written in a form that would not join against adapter output.
    for entry in load_defillama_registry():
        assert entry.ref.uid == entry.ref.uid.strip()
        assert entry.ref.chain.islower()


def test_shipped_registry_documents_its_imprecise_entries() -> None:
    # The OUSG mapping points at an umbrella protocol covering several products.
    # An undocumented entry like that is how a wrong number gets published.
    entries = {entry.symbol: entry for entry in load_defillama_registry()}
    assert "imprecision" in entries["OUSG"].notes.lower()


def test_entries_parse_into_asset_refs() -> None:
    entry = _parse(VALID)[0]
    assert entry.ref.chain == "ethereum"
    assert entry.symbol == "BUIDL"
    assert entry.notes == "multi-chain protocol"


def test_wrong_schema_version_is_refused() -> None:
    with pytest.raises(RegistryError, match="schema_version"):
        _parse({**VALID, "schema_version": 99})


def test_duplicate_asset_is_refused() -> None:
    # Two entries for one asset would make the resolved slug depend on file
    # order, which is the kind of quiet ambiguity this file exists to remove.
    with pytest.raises(RegistryError, match="duplicate"):
        _parse({**VALID, "asset": [ENTRY, ENTRY]})


@pytest.mark.parametrize("field", ["uid", "symbol", "name", "defillama_slug", "defillama_chain"])
def test_missing_required_field_is_refused(field: str) -> None:
    incomplete = {key: value for key, value in ENTRY.items() if key != field}
    with pytest.raises(RegistryError, match=field):
        _parse({**VALID, "asset": [incomplete]})


def test_empty_registry_is_refused() -> None:
    with pytest.raises(RegistryError, match="no \\[\\[asset\\]\\]"):
        _parse({**VALID, "asset": []})
