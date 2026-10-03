"""Live checks for the keyed sources, skipped when no credential is present.

The rwa.xyz and Dune adapters were written against published documentation and
have never run against the real APIs. These tests are the first thing to run
once a key exists. Until then they skip, which keeps the absence visible in the
test report rather than hidden.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import polars as pl
import pytest

from rwa_liquidity.cache import ParquetCache
from rwa_liquidity.config import (
    DUNE_HOLDERS_QUERY_VAR,
    DUNE_KEY_VAR,
    DUNE_TRANSFERS_QUERY_VAR,
    RWA_XYZ_KEY_VAR,
    load_environment,
)
from rwa_liquidity.schema.asset import AssetRef
from rwa_liquidity.sources import DuneSource, RwaXyzSource

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.network

BUIDL = AssetRef.parse("ethereum:0x7712c34205737192402172409a8f7ccef8aa2aec")


def requires(*variables: str) -> None:
    """Skip unless every named environment variable is set."""
    load_environment()
    missing = [name for name in variables if not os.environ.get(name, "").strip()]
    if missing:
        pytest.skip(f"needs {', '.join(missing)}")


def test_live_rwa_xyz_matches_the_documented_shape(cache_root: Path) -> None:
    requires(RWA_XYZ_KEY_VAR)

    source = RwaXyzSource(cache=ParquetCache(cache_root))
    try:
        frame = source.fetch_asset_snapshots([BUIDL])
    finally:
        source.close()

    # If this fails, the documented response shape and the real one differ, and
    # the adapter's docstring assumptions need revisiting rather than patching.
    assert frame.height == 1
    assert frame["total_supply"].item() is not None
    assert frame["holder_count"].item() is not None


def test_live_rwa_xyz_network_names_map_onto_canonical_chains(cache_root: Path) -> None:
    requires(RWA_XYZ_KEY_VAR)

    source = RwaXyzSource(cache=ParquetCache(cache_root))
    try:
        everything = source.fetch_asset_snapshots([])
    finally:
        source.close()

    # The lowercase-and-hyphenate rule is an unverified guess. Seeing the real
    # chain names is what turns it into either a fact or a `chain_aliases` entry.
    chains = sorted({uid.split(":")[0] for uid in everything["asset_uid"].to_list()})
    assert "ethereum" in chains, f"chain naming rule needs adjusting; observed: {chains}"


def test_live_dune_transfers_satisfy_the_column_contract(cache_root: Path) -> None:
    requires(DUNE_KEY_VAR, DUNE_TRANSFERS_QUERY_VAR)

    source = DuneSource(cache=ParquetCache(cache_root))
    end = datetime.now(UTC)
    try:
        frame = source.fetch_transfers(BUIDL, start=end - timedelta(days=30), end=end)
    finally:
        source.close()

    # An empty frame is a legitimate finding, so the assertion is about shape.
    assert frame.schema["block_time"] == pl.Datetime("us", "UTC")


def test_live_dune_holders_satisfy_the_column_contract(cache_root: Path) -> None:
    requires(DUNE_KEY_VAR, DUNE_HOLDERS_QUERY_VAR)

    source = DuneSource(cache=ParquetCache(cache_root))
    try:
        frame = source.fetch_holders(BUIDL)
    finally:
        source.close()

    assert "balance" in frame.columns
    if not frame.is_empty():
        assert all(balance >= 0 for balance in frame["balance"].to_list())
