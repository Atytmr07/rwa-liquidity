"""The rwa.xyz adapter.

Payloads follow the shape documented at docs.rwa.xyz. Like the Dune tests, these
were built from documentation rather than observed responses, because the
endpoint is gated and no key was available. They prove the adapter handles the
documented shape; they are not evidence it works against the live API.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest

from rwa_liquidity.cache import ParquetCache
from rwa_liquidity.config import MissingCredentialError
from rwa_liquidity.schema.asset import AssetRef
from rwa_liquidity.sources import Capability, RwaXyzSource, SourceFetchError

BUIDL = AssetRef.parse("ethereum:0x7712c34205737192402172409a8f7ccef8aa2aec")
ABSENT = AssetRef.parse("ethereum:0x" + "9" * 40)


def token(
    *,
    address: str = "0x7712C34205737192402172409a8F7ccef8aA2AEc",
    network: str = "Ethereum",
    name: str = "BlackRock USD Institutional Digital Liquidity Fund",
) -> dict[str, object]:
    """One token record, with metrics nested as the documentation shows."""
    return {
        "id": 1,
        "asset_id": 10,
        "name": name,
        "address": address,
        "decimals": 6,
        "standards": ["ERC-20"],
        "network_name": network,
        "protocol_name": "Securitize",
        "transferability_type": "restricted",
        "market_value_dollar": {"val": 1_158_286_022.0, "val_7d": 1.1e9, "chg_7d_pct": 3.0},
        "total_supply_token": {"val": 1_158_286_022.0, "val_7d": 1.1e9},
        "holding_addresses_count": {"val": 75, "val_7d": 70, "chg_7d_pct": 7.1},
    }


def page(
    records: list[dict[str, object]], *, page_number: int = 1, page_count: int = 1
) -> dict[str, object]:
    return {
        "results": records,
        "pagination": {
            "page": page_number,
            "perPage": 100,
            "pageCount": page_count,
            "resultCount": len(records),
        },
    }


def source(
    cache_root: Path,
    payload: object,
    *,
    seen: list[httpx.Request] | None = None,
    aliases: dict[str, str] | None = None,
) -> RwaXyzSource:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=payload)

    return RwaXyzSource(
        cache=ParquetCache(cache_root),
        client=httpx.Client(transport=httpx.MockTransport(handle)),
        chain_aliases=aliases,
    )


def test_token_record_becomes_a_valid_snapshot(cache_root: Path) -> None:
    frame = source(cache_root, page([token()])).fetch_asset_snapshots([BUIDL])

    assert frame.height == 1
    row = frame.row(0, named=True)
    assert row["asset_uid"] == BUIDL.uid
    assert row["total_supply"] == 1_158_286_022.0
    assert row["market_value_usd"] == 1_158_286_022.0
    assert row["holder_count"] == 75
    assert row["decimals"] == 6


def test_nested_metric_objects_are_unwrapped_to_their_current_value(
    cache_root: Path,
) -> None:
    # The documented shape is {"val": ..., "val_7d": ...}. Taking the object
    # itself, or the wrong key, would put a week-old figure in a current column.
    frame = source(cache_root, page([token()])).fetch_asset_snapshots([BUIDL])
    assert frame["market_value_usd"].item() != 1.1e9


def test_checksummed_address_matches_the_canonical_key(cache_root: Path) -> None:
    # rwa.xyz returns EIP-55 mixed case; the canonical key is lowercase. Without
    # normalization nothing would ever join.
    frame = source(cache_root, page([token()])).fetch_asset_snapshots([BUIDL])
    assert frame["asset_uid"].item() == BUIDL.uid


def test_symbol_is_null_because_the_source_publishes_none(cache_root: Path) -> None:
    # Deriving a ticker from the fund's name would be inventing data.
    frame = source(cache_root, page([token()])).fetch_asset_snapshots([BUIDL])
    assert frame["symbol"].item() is None


def test_as_of_falls_back_to_the_retrieval_time(cache_root: Path) -> None:
    # rwa.xyz publishes no observation timestamp, so the fetch time is an upper
    # bound on the figure's age. Both columns therefore hold the same instant.
    frame = source(cache_root, page([token()])).fetch_asset_snapshots([BUIDL])
    assert frame["as_of"].item() == frame["retrieved_at"].item()


def test_network_name_is_lowercased_and_hyphenated(cache_root: Path) -> None:
    frame = source(
        cache_root, page([token(network="BNB Chain", address="0x" + "1" * 40)])
    ).fetch_asset_snapshots([])
    assert frame["asset_uid"].item().startswith("bnb-chain:")


def test_chain_aliases_override_the_default_rule(cache_root: Path) -> None:
    # The documentation does not state the value format, so the mapping has to
    # be correctable without a code change.
    frame = source(
        cache_root,
        page([token(network="BNB Chain", address="0x" + "1" * 40)]),
        aliases={"bnb chain": "bsc"},
    ).fetch_asset_snapshots([])
    assert frame["asset_uid"].item().startswith("bsc:")


def test_assets_not_requested_are_filtered_out(cache_root: Path) -> None:
    records = [token(), token(address="0x" + "2" * 40, name="Something Else")]
    frame = source(cache_root, page(records)).fetch_asset_snapshots([BUIDL])
    assert frame.height == 1


def test_empty_request_returns_every_token(cache_root: Path) -> None:
    records = [token(), token(address="0x" + "2" * 40, name="Something Else")]
    frame = source(cache_root, page(records)).fetch_asset_snapshots([])
    assert frame.height == 2


def test_asset_the_source_does_not_publish_is_reported(
    cache_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        frame = source(cache_root, page([token()])).fetch_asset_snapshots([BUIDL, ABSENT])

    assert frame.height == 1
    assert ABSENT.uid in caplog.text


def test_record_without_a_contract_address_is_skipped(cache_root: Path) -> None:
    # Off-chain entries are real records upstream, just not measurable here.
    offchain = {k: v for k, v in token().items() if k != "address"}
    frame = source(cache_root, page([offchain])).fetch_asset_snapshots([])
    assert frame.is_empty()


def test_unusable_address_is_skipped_with_a_warning(
    cache_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        frame = source(cache_root, page([token(address="  ")])).fetch_asset_snapshots([])
    assert frame.is_empty()
    assert "unusable address" in caplog.text


def test_pagination_follows_page_count(cache_root: Path) -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        query = json.loads(request.url.params["query"])
        number = query["pagination"]["page"]
        address = "0x" + f"{number:040x}"
        return httpx.Response(
            200, json=page([token(address=address)], page_number=number, page_count=3)
        )

    frame = RwaXyzSource(
        cache=ParquetCache(cache_root),
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    ).fetch_asset_snapshots([])

    assert len(seen) == 3
    assert frame.height == 3


def test_missing_results_array_is_an_error(cache_root: Path) -> None:
    with pytest.raises(SourceFetchError, match="results"):
        source(cache_root, {"data": []}).fetch_asset_snapshots([BUIDL])


def test_capabilities_exclude_transfers_and_holders(cache_root: Path) -> None:
    adapter = source(cache_root, page([token()]))
    assert adapter.supports(Capability.ASSET_SNAPSHOT)
    assert not adapter.supports(Capability.TRANSFER_EVENT)
    assert not adapter.supports(Capability.HOLDER_BALANCE)


def test_missing_key_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # A stranger with no keys must get a sentence they can act on, not a 401.
    monkeypatch.delenv("RWA_XYZ_API_KEY", raising=False)
    monkeypatch.setattr("rwa_liquidity.config.load_dotenv", lambda **_: None)
    with pytest.raises(MissingCredentialError, match="RWA_XYZ_API_KEY"):
        RwaXyzSource()
