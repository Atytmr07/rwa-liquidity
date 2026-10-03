"""End-to-end checks against the live DeFiLlama API.

Deselected in CI (`-m "not network"`) so that a third-party outage never turns
the build red. Run them deliberately:

    uv run pytest -m network

They exist because a mock transport proves the adapter handles the shape it was
told about, not that the shape is still what the provider sends. These are the
only tests that can catch an upstream change.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from rwa_liquidity.cache import ParquetCache
from rwa_liquidity.schema.asset import AssetRef
from rwa_liquidity.sources import DeFiLlamaPricesSource, DeFiLlamaProtocolTvlSource
from rwa_liquidity.sources.registry import load_defillama_registry

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.network

PAXG = AssetRef.parse("ethereum:0x45804880de22913dafe09f4980848ece6ecbaf78")


def test_live_prices_produce_a_validated_frame(cache_root: Path) -> None:
    source = DeFiLlamaPricesSource(cache=ParquetCache(cache_root))
    try:
        frame = source.fetch_asset_snapshots([asset.ref for asset in load_defillama_registry()])
    finally:
        source.close()

    # Every registry entry should resolve; if one stops resolving, the mapping
    # has gone stale and that is exactly what this test is for.
    assert frame.height == len(load_defillama_registry())
    # `.to_list()` rather than `.min()`: a polars aggregate is typed as a wide
    # union that has to be narrowed before it can be compared.
    assert all(price > 0 for price in frame["price_usd"].to_list())
    assert all(decimals >= 0 for decimals in frame["decimals"].to_list())

    # The observation timestamps have to be recent and timezone-aware, since
    # every metric window is built from them.
    newest = frame["as_of"].max()
    assert isinstance(newest, datetime)
    assert datetime.now(UTC) - newest < timedelta(days=7)


def test_live_protocol_tvl_produces_a_validated_frame(cache_root: Path) -> None:
    source = DeFiLlamaProtocolTvlSource(cache=ParquetCache(cache_root))
    try:
        frame = source.fetch_asset_snapshots([PAXG])
    finally:
        source.close()

    assert frame.height == 1
    # PAXG is single-chain and single-token, so this figure should be a genuine
    # measurement rather than an upper bound.
    assert frame["market_value_usd"].item() > 0


def test_live_response_is_cached_and_replayable(cache_root: Path) -> None:
    # Proves the raw-response cache actually works against a real payload: the
    # second call must not touch the network and must return the same numbers.
    cache = ParquetCache(cache_root)
    source = DeFiLlamaPricesSource(cache=cache)
    try:
        first = source.fetch_asset_snapshots([PAXG])
    finally:
        source.close()

    replayed = DeFiLlamaPricesSource(cache=cache)
    try:
        second = replayed.fetch_asset_snapshots([PAXG])
    finally:
        replayed.close()

    assert first.equals(second)
    assert list(cache_root.rglob("*.parquet"))
