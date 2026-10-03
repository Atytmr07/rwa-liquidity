"""The DeFiLlama adapters.

Payload shapes here were copied from real responses observed on 2026-07-29, not
invented, including the parts that are awkward: the price endpoint returning
HTTP 200 with an empty object for an unknown asset, and the protocol endpoint
nesting its value series under a capitalised chain display name.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx
import polars as pl
import pytest

from rwa_liquidity.cache import ParquetCache
from rwa_liquidity.schema.asset import AssetRef
from rwa_liquidity.sources import (
    Capability,
    DeFiLlamaPricesSource,
    DeFiLlamaProtocolTvlSource,
    RegistryEntry,
    SourceFetchError,
    UnsupportedCapabilityError,
)

BUIDL = AssetRef.parse("ethereum:0x7712c34205737192402172409a8f7ccef8aa2aec")
PAXG = AssetRef.parse("ethereum:0x45804880de22913dafe09f4980848ece6ecbaf78")
UNKNOWN = AssetRef.parse("ethereum:0x" + "9" * 40)

# The timestamp carried by the observed BUIDL price record. The expected UTC
# instant is worked out by hand rather than taken from the code under test:
# 1785275713 = 20662 days + 78913 seconds. Day 20662 is 208 days past
# 1970-01-01 + 56 years (14 leap days), i.e. 2026-07-28; 78913 s is 21:55:13.
PRICE_TIMESTAMP = 1785275713
PRICE_AS_OF = datetime(2026, 7, 28, 21, 55, 13, tzinfo=UTC)

PRICE_RECORDS = {
    BUIDL.uid: {
        "decimals": 6,
        "symbol": "BUIDL",
        "price": 1,
        "timestamp": PRICE_TIMESTAMP,
        "confidence": 0.99,
    },
    PAXG.uid: {
        "decimals": 18,
        "symbol": "PAXG",
        "price": 4010.512762258206,
        "timestamp": PRICE_TIMESTAMP,
        "confidence": 0.99,
    },
}


def price_handler(seen: list[httpx.Request]) -> httpx.MockTransport:
    """Serve the price endpoint, echoing back only the keys it recognises."""

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        requested = request.url.path.rsplit("/", 1)[-1].split(",")
        return httpx.Response(
            200,
            json={"coins": {uid: PRICE_RECORDS[uid] for uid in requested if uid in PRICE_RECORDS}},
        )

    return httpx.MockTransport(handle)


def prices(cache_root: Path, seen: list[httpx.Request] | None = None) -> DeFiLlamaPricesSource:
    return DeFiLlamaPricesSource(
        cache=ParquetCache(cache_root),
        client=httpx.Client(transport=price_handler(seen if seen is not None else [])),
    )


def test_price_response_becomes_a_valid_snapshot_frame(cache_root: Path) -> None:
    frame = prices(cache_root).fetch_asset_snapshots([BUIDL, PAXG])

    assert frame.height == 2
    row = frame.filter(pl.col("asset_uid") == BUIDL.uid).row(0, named=True)
    assert row["symbol"] == "BUIDL"
    assert row["decimals"] == 6
    assert row["price_usd"] == 1.0
    assert row["source"] == "defillama_prices"


def test_as_of_comes_from_the_providers_timestamp_not_the_fetch_time(
    cache_root: Path,
) -> None:
    # DeFiLlama says when it observed the price. Using the fetch time instead
    # would silently shift every observation window by the age of the quote.
    frame = prices(cache_root).fetch_asset_snapshots([BUIDL])
    assert frame["as_of"].item() == PRICE_AS_OF
    assert frame["retrieved_at"].item() > PRICE_AS_OF


def test_unknown_asset_is_omitted_and_reported(
    cache_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # The endpoint answers HTTP 200 with an empty object for a key it does not
    # know, so silent omission is the default behaviour and has to be caught.
    with caplog.at_level(logging.WARNING):
        frame = prices(cache_root).fetch_asset_snapshots([BUIDL, UNKNOWN])

    assert frame.height == 1
    assert UNKNOWN.uid in caplog.text


def test_no_assets_means_no_request(cache_root: Path) -> None:
    seen: list[httpx.Request] = []
    frame = prices(cache_root, seen).fetch_asset_snapshots([])

    assert seen == []
    assert frame.is_empty()
    # An empty result still has the full schema, so concatenating it with a
    # populated frame from another source cannot fail.
    assert "market_value_usd" in frame.columns


def test_repeated_assets_collapse_to_one_row(cache_root: Path) -> None:
    # Two spellings of one asset would otherwise produce two rows and trip the
    # schema's uniqueness constraint.
    upper = AssetRef("Ethereum", BUIDL.address.upper().replace("0X", "0x"))
    frame = prices(cache_root).fetch_asset_snapshots([BUIDL, upper])
    assert frame.height == 1


def test_large_requests_are_chunked(cache_root: Path) -> None:
    seen: list[httpx.Request] = []
    many = [AssetRef("ethereum", f"0x{index:040x}") for index in range(120)]
    prices(cache_root, seen).fetch_asset_snapshots(many)

    assert len(seen) == 3  # 120 assets at 50 per request


def test_second_call_is_served_from_cache(cache_root: Path) -> None:
    seen: list[httpx.Request] = []
    source = prices(cache_root, seen)
    source.fetch_asset_snapshots([BUIDL])
    source.fetch_asset_snapshots([BUIDL])

    assert len(seen) == 1


def test_refresh_bypasses_the_cache(cache_root: Path) -> None:
    seen: list[httpx.Request] = []
    source = prices(cache_root, seen)
    source.fetch_asset_snapshots([BUIDL])
    source.fetch_asset_snapshots([BUIDL], refresh=True)

    assert len(seen) == 2


def test_asset_order_does_not_split_the_cache_entry(cache_root: Path) -> None:
    seen: list[httpx.Request] = []
    source = prices(cache_root, seen)
    source.fetch_asset_snapshots([BUIDL, PAXG])
    source.fetch_asset_snapshots([PAXG, BUIDL])

    assert len(seen) == 1


def test_unexpected_payload_shape_is_an_error(cache_root: Path) -> None:
    # A silently changed endpoint shape must not become an empty result, which
    # would read downstream as "this asset does not exist".
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"data": []}))
    source = DeFiLlamaPricesSource(
        cache=ParquetCache(cache_root), client=httpx.Client(transport=transport)
    )
    with pytest.raises(SourceFetchError, match="coins"):
        source.fetch_asset_snapshots([BUIDL])


def test_http_error_is_reported_with_the_body(cache_root: Path) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(429, text="rate limited"))
    source = DeFiLlamaPricesSource(
        cache=ParquetCache(cache_root), client=httpx.Client(transport=transport)
    )
    with pytest.raises(SourceFetchError, match="429"):
        source.fetch_asset_snapshots([BUIDL])


def test_prices_source_declares_only_what_it_can_answer(cache_root: Path) -> None:
    source = prices(cache_root)
    assert source.supports(Capability.ASSET_SNAPSHOT)
    assert not source.supports(Capability.TRANSFER_EVENT)

    with pytest.raises(UnsupportedCapabilityError, match="transfer_event"):
        source.fetch_transfers(BUIDL, start=PRICE_AS_OF, end=PRICE_AS_OF)


# ---------------------------------------------------------------------------
# Protocol TVL
# ---------------------------------------------------------------------------

PROTOCOL_ENTRY = RegistryEntry(
    ref=BUIDL,
    symbol="BUIDL",
    name="BlackRock USD Institutional Digital Liquidity Fund",
    defillama_slug="blackrock-buidl",
    defillama_chain="Ethereum",
)

# Shape copied from the real protocol/blackrock-buidl response: a per-chain
# `tvl` series of {date, totalLiquidityUSD}, alongside chains we must not use.
PROTOCOL_PAYLOAD = {
    "name": "BlackRock BUIDL",
    "chainTvls": {
        "Ethereum": {
            "tvl": [
                {"date": PRICE_TIMESTAMP - 86400, "totalLiquidityUSD": 1_100_000_000},
                {"date": PRICE_TIMESTAMP, "totalLiquidityUSD": 1_158_286_022},
            ]
        },
        "Solana": {"tvl": [{"date": PRICE_TIMESTAMP, "totalLiquidityUSD": 654_448_555}]},
    },
    "tvl": [{"date": PRICE_TIMESTAMP, "totalLiquidityUSD": 3_443_574_869}],
}


def tvl_source(
    cache_root: Path,
    payload: object = PROTOCOL_PAYLOAD,
    registry: list[RegistryEntry] | None = None,
) -> DeFiLlamaProtocolTvlSource:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    return DeFiLlamaProtocolTvlSource(
        cache=ParquetCache(cache_root),
        client=httpx.Client(transport=transport),
        registry=registry if registry is not None else [PROTOCOL_ENTRY],
    )


def test_chain_specific_value_is_used_not_the_multichain_total(cache_root: Path) -> None:
    # This is the whole point of the source. BUIDL's multi-chain total is about
    # three times its Ethereum value; using the total would overstate the
    # Ethereum contract by that factor while looking perfectly successful.
    frame = tvl_source(cache_root).fetch_asset_snapshots([BUIDL])

    assert frame["market_value_usd"].item() == 1_158_286_022.0
    assert frame["market_value_usd"].item() != 3_443_574_869.0


def test_latest_point_in_the_series_is_taken(cache_root: Path) -> None:
    frame = tvl_source(cache_root).fetch_asset_snapshots([BUIDL])
    assert frame["as_of"].item() == PRICE_AS_OF


def test_asset_without_a_registry_entry_is_skipped_and_reported(
    cache_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # DeFiLlama's own address field points at a governance token for several RWA
    # protocols, so guessing a slug is worse than declining to.
    with caplog.at_level(logging.WARNING):
        frame = tvl_source(cache_root).fetch_asset_snapshots([PAXG])

    assert frame.is_empty()
    assert PAXG.uid in caplog.text


def test_missing_chain_is_skipped_and_reported(
    cache_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    entry = RegistryEntry(
        ref=BUIDL,
        symbol="BUIDL",
        name="BlackRock",
        defillama_slug="blackrock-buidl",
        defillama_chain="Aptos",  # present on the real protocol, absent here
    )
    with caplog.at_level(logging.WARNING):
        frame = tvl_source(cache_root, registry=[entry]).fetch_asset_snapshots([BUIDL])

    assert frame.is_empty()
    assert "Aptos" in caplog.text


def test_malformed_series_point_is_skipped_not_coerced(
    cache_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    payload = {"chainTvls": {"Ethereum": {"tvl": [{"date": PRICE_TIMESTAMP}]}}}
    with caplog.at_level(logging.WARNING):
        frame = tvl_source(cache_root, payload=payload).fetch_asset_snapshots([BUIDL])

    assert frame.is_empty()
    assert "malformed" in caplog.text


def test_response_without_chain_tvls_is_an_error(cache_root: Path) -> None:
    with pytest.raises(SourceFetchError, match="chainTvls"):
        tvl_source(cache_root, payload={"name": "x"}).fetch_asset_snapshots([BUIDL])


def test_registry_notes_survive_onto_the_source(cache_root: Path) -> None:
    # The notes are the record of what is imprecise about a mapping, so they
    # have to remain reachable from the adapter that used them.
    source = tvl_source(cache_root)
    assert source.registry[0].defillama_slug == "blackrock-buidl"
