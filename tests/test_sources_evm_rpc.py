"""The Ethereum JSON-RPC adapter.

Fixtures reproduce real response shapes observed against a public endpoint on
2026-07-30, including the parts that bite: addresses arriving left-padded to a
full word, ERC-721 logs sharing the ERC-20 event signature, and nodes rejecting
a log query rather than paginating it.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from rwa_liquidity.cache import ParquetCache
from rwa_liquidity.schema.asset import AssetRef
from rwa_liquidity.schema.types import ZERO_ADDRESS, TransferKind
from rwa_liquidity.sources import Capability, EvmRpcSource, SourceFetchError
from rwa_liquidity.sources.evm_rpc import TRANSFER_TOPIC

ASSET = AssetRef.parse("ethereum:0x7712c34205737192402172409a8f7ccef8aa2aec")
ALICE = "0x" + "a" * 40
BOB = "0x" + "b" * 40
TREASURY = "0x" + "7" * 40

HEAD = 25_641_620
START = datetime(2026, 6, 1, tzinfo=UTC)
END = datetime(2026, 7, 1, tzinfo=UTC)
INSIDE = int(datetime(2026, 6, 15, 12, 0, tzinfo=UTC).timestamp())
OUTSIDE = int(datetime(2026, 5, 15, 12, 0, tzinfo=UTC).timestamp())

DECIMALS = 6
SCALE = 10**DECIMALS


def word(value: int) -> str:
    return f"{value:064x}"


def padded(address: str) -> str:
    """An indexed address as a node returns it: left-padded to 32 bytes."""
    return "0x" + address[2:].rjust(64, "0")


def dynamic_string(text: str) -> str:
    """ABI-encode a dynamic string return value."""
    raw = text.encode()
    body = raw + b"\x00" * ((32 - len(raw) % 32) % 32)
    return "0x" + word(32) + word(len(raw)) + body.hex()


def bytes32_string(text: str) -> str:
    """The older, non-conformant encoding some tokens still use."""
    return "0x" + text.encode().ljust(32, b"\x00").hex()


def log(  # noqa: PLR0913 -- one parameter per field of a log entry
    *,
    sender: str,
    recipient: str,
    amount: float,
    block: int = 21_000_000,
    index: int = 0,
    timestamp: int | None = INSIDE,
    extra_topic: bool = False,
) -> dict[str, Any]:
    topics = [TRANSFER_TOPIC, padded(sender), padded(recipient)]
    if extra_topic:
        # ERC-721 indexes the token id too, producing a fourth topic.
        topics.append(word(1))
    entry: dict[str, Any] = {
        "address": ASSET.address,
        "topics": topics,
        "data": "0x" + word(int(amount * SCALE)),
        "blockNumber": hex(block),
        "logIndex": hex(index),
        "transactionHash": "0x" + word(index)[24:],
    }
    if timestamp is not None:
        entry["blockTimestamp"] = hex(timestamp)
    return entry


class Node:
    """A mock JSON-RPC node with recorded behaviour and a call log."""

    def __init__(  # noqa: PLR0913 -- one knob per behaviour the tests exercise
        self,
        logs: list[dict[str, Any]] | None = None,
        *,
        total_supply: float | None = None,
        symbol: str = "BUIDL",
        symbol_encoding: str = "dynamic",
        log_limit: int | None = None,
        block_timestamps: dict[int, int] | None = None,
    ) -> None:
        self.logs = logs if logs is not None else []
        self.total_supply = total_supply
        self.symbol = symbol
        self.symbol_encoding = symbol_encoding
        self.log_limit = log_limit
        self.block_timestamps = block_timestamps or {}
        self.calls: list[tuple[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method, params = body["method"], body.get("params", [])
        self.calls.append((method, params))

        def ok(result: Any) -> httpx.Response:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        if method == "eth_blockNumber":
            return ok(hex(HEAD))
        if method == "eth_getBlockByNumber":
            number = int(params[0], 16)
            return ok({"timestamp": hex(self.block_timestamps.get(number, INSIDE))})
        if method == "eth_call":
            return ok(self._call(params[0]["data"]))
        if method == "eth_getLogs":
            return self._get_logs(params[0], body["id"])
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "error": "unknown"})

    def _call(self, selector: str) -> str:
        if selector == "0x313ce567":  # decimals()
            return "0x" + word(DECIMALS)
        if selector == "0x18160ddd":  # totalSupply()
            supply = (
                self.total_supply
                if self.total_supply is not None
                else sum(
                    int(entry["data"], 16)
                    for entry in self.logs
                    if entry["topics"][1] == padded(ZERO_ADDRESS)
                )
                / SCALE
            )
            return "0x" + word(int(supply * SCALE))
        if selector == "0x95d89b41":  # symbol()
            return (
                dynamic_string(self.symbol)
                if self.symbol_encoding == "dynamic"
                else bytes32_string(self.symbol)
            )
        if selector == "0x06fdde03":  # name()
            return dynamic_string("BlackRock USD Institutional Digital Liquidity Fund")
        return "0x"

    def _get_logs(self, query: dict[str, Any], request_id: int) -> httpx.Response:
        low, high = int(query["fromBlock"], 16), int(query["toBlock"], 16)
        selected = [e for e in self.logs if low <= int(e["blockNumber"], 16) <= high]
        if self.log_limit is not None and len(selected) > self.log_limit:
            # Real nodes reject rather than paginate, and say so in an error.
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32005, "message": "query returned more than N results"},
                },
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": request_id, "result": selected})


def source(cache_root: Path, node: Node, **kwargs: Any) -> EvmRpcSource:
    return EvmRpcSource(
        cache=ParquetCache(cache_root),
        client=httpx.Client(transport=httpx.MockTransport(node.handle)),
        rpc_url="https://node.invalid",
        # No pacing against a mock: the throttle exists to stay under a real
        # endpoint's rate limit, and honouring it here just slows the suite.
        min_interval=0.0,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Contract reads
# ---------------------------------------------------------------------------


def test_snapshot_reads_supply_and_metadata_off_the_contract(cache_root: Path) -> None:
    # These are exact rather than reported: they come from the token's own state.
    node = Node(total_supply=224_830_404.130349)
    frame = source(cache_root, node).fetch_asset_snapshots([ASSET])

    row = frame.row(0, named=True)
    assert row["symbol"] == "BUIDL"
    assert row["decimals"] == DECIMALS
    assert row["total_supply"] == pytest.approx(224_830_404.130349)
    # A node does not know prices, and inventing one is not this adapter's job.
    assert row["price_usd"] is None


def test_bytes32_symbol_encoding_is_decoded(cache_root: Path) -> None:
    # Several older tokens return a fixed bytes32 instead of a dynamic string.
    node = Node(total_supply=1.0, symbol="PAXG", symbol_encoding="bytes32")
    frame = source(cache_root, node).fetch_asset_snapshots([ASSET])
    assert frame["symbol"].item() == "PAXG"


class SilentNode(Node):
    """A contract that answers every call with empty data, as a non-ERC-20 would."""

    def _call(self, selector: str) -> str:  # noqa: ARG002 -- answers nothing by design
        return "0x"


def test_a_contract_without_decimals_is_refused(cache_root: Path) -> None:
    node = SilentNode(total_supply=1.0)
    with pytest.raises(SourceFetchError, match="decimals"):
        source(cache_root, node).fetch_asset_snapshots([ASSET])


# ---------------------------------------------------------------------------
# Log decoding
# ---------------------------------------------------------------------------


def test_padded_topics_decode_back_to_addresses(cache_root: Path) -> None:
    # Indexed addresses arrive left-padded to a full 32-byte word. Taking the
    # whole word would produce an address that matches nothing.
    node = Node([log(sender=ALICE, recipient=BOB, amount=100.0)], total_supply=100.0)
    frame = source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)

    assert frame["from_address"].item() == ALICE
    assert frame["to_address"].item() == BOB


def test_amounts_are_scaled_by_the_tokens_decimals(cache_root: Path) -> None:
    node = Node([log(sender=ALICE, recipient=BOB, amount=1_234.5)], total_supply=1.0)
    frame = source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)
    assert frame["amount"].item() == pytest.approx(1_234.5)


def test_erc721_logs_are_skipped(cache_root: Path, caplog: pytest.LogCaptureFixture) -> None:
    # ERC-721 reuses the ERC-20 Transfer signature but indexes the token id,
    # giving four topics. Counting NFT movements as fungible volume is nonsense.
    node = Node(
        [
            log(sender=ALICE, recipient=BOB, amount=100.0, index=0),
            log(sender=ALICE, recipient=BOB, amount=999.0, index=1, extra_topic=True),
        ],
        total_supply=100.0,
    )
    with caplog.at_level(logging.WARNING):
        frame = source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)

    assert frame.height == 1
    assert frame["amount"].item() == pytest.approx(100.0)
    assert "ERC-721" in caplog.text


def test_transfers_outside_the_window_are_dropped(cache_root: Path) -> None:
    node = Node(
        [
            log(sender=ALICE, recipient=BOB, amount=100.0, index=0, timestamp=INSIDE),
            log(sender=ALICE, recipient=BOB, amount=999.0, index=1, timestamp=OUTSIDE),
        ],
        total_supply=100.0,
    )
    frame = source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)
    assert frame["amount"].to_list() == [pytest.approx(100.0)]


def test_missing_block_timestamp_falls_back_to_a_block_lookup(cache_root: Path) -> None:
    # Not every endpoint puts blockTimestamp on the log. Guessing would move a
    # transfer into or out of its observation window.
    node = Node(
        [log(sender=ALICE, recipient=BOB, amount=100.0, block=21_000_042, timestamp=None)],
        total_supply=100.0,
        block_timestamps={21_000_042: INSIDE},
    )
    frame = source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)

    assert frame.height == 1
    assert any(method == "eth_getBlockByNumber" for method, _ in node.calls)


def test_transfers_are_classified_against_the_primary_market(cache_root: Path) -> None:
    node = Node(
        [
            log(sender=ZERO_ADDRESS, recipient=ALICE, amount=500.0, index=0),
            log(sender=ALICE, recipient=BOB, amount=100.0, index=1),
            log(sender=BOB, recipient=ZERO_ADDRESS, amount=50.0, index=2),
        ],
        total_supply=450.0,
    )
    frame = source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)
    counts = dict(zip(frame["kind"].to_list(), frame["amount"].to_list(), strict=True))

    assert counts[TransferKind.MINT.value] == pytest.approx(500.0)
    assert counts[TransferKind.SECONDARY.value] == pytest.approx(100.0)
    assert counts[TransferKind.BURN.value] == pytest.approx(50.0)


def test_issuer_addresses_reclassify_treasury_distribution(cache_root: Path) -> None:
    node = Node([log(sender=TREASURY, recipient=ALICE, amount=500.0)], total_supply=500.0)
    frame = source(cache_root, node, issuer_addresses={ASSET.uid: [TREASURY]}).fetch_transfers(
        ASSET, start=START, end=END
    )
    assert frame["kind"].item() == TransferKind.MINT.value


# ---------------------------------------------------------------------------
# Range splitting and budget
# ---------------------------------------------------------------------------


def test_a_rejected_range_is_halved_rather_than_guessed(cache_root: Path) -> None:
    # Nodes cap results instead of paginating, and the cap differs by provider.
    # Halving on rejection adapts to whatever the endpoint allows.
    entries = [
        log(sender=ALICE, recipient=BOB, amount=1.0, block=1_000_000 * (i + 1), index=i)
        for i in range(8)
    ]
    node = Node(entries, total_supply=8.0, log_limit=3)
    frame = source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)

    assert frame.height == 8
    rejections = sum(1 for method, _ in node.calls if method == "eth_getLogs")
    assert rejections > 1, "the range should have been split"


def test_an_over_budget_scan_stops_with_an_explanation(cache_root: Path) -> None:
    # A widely traded token is hopeless against a free endpoint. Saying so beats
    # issuing thousands of requests.
    entries = [
        log(sender=ALICE, recipient=BOB, amount=1.0, block=21_000_000 + i, index=i)
        for i in range(40)
    ]
    node = Node(entries, total_supply=40.0)
    with pytest.raises(SourceFetchError, match="too active"):
        source(cache_root, node, max_logs=10).fetch_transfers(ASSET, start=START, end=END)


def test_a_persistent_rpc_error_is_reported(cache_root: Path) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "nope"}}
        )
    )
    adapter = EvmRpcSource(
        cache=ParquetCache(cache_root),
        client=httpx.Client(transport=transport),
        rpc_url="https://node.invalid",
        min_interval=0.0,
    )
    with pytest.raises(SourceFetchError, match="nope"):
        adapter.fetch_asset_snapshots([ASSET])


# ---------------------------------------------------------------------------
# Holder reconstruction -- the point of the adapter
# ---------------------------------------------------------------------------


def ledger_node(total_supply: float | None = None) -> Node:
    """A history that leaves ALICE with 400 and BOB with 100."""
    return Node(
        [
            log(sender=ZERO_ADDRESS, recipient=ALICE, amount=500.0, index=0),
            log(sender=ALICE, recipient=BOB, amount=150.0, index=1),
            log(sender=BOB, recipient=ZERO_ADDRESS, amount=50.0, index=2),
            log(sender=ALICE, recipient=BOB, amount=0.0, index=3),
        ],
        total_supply=total_supply if total_supply is not None else 450.0,
    )


def test_balances_are_replayed_from_the_full_transfer_history(cache_root: Path) -> None:
    # Minted 500 to ALICE, ALICE sent 150 to BOB, BOB burned 50.
    # ALICE = 350, BOB = 100, total = 450.
    frame = source(cache_root, ledger_node()).fetch_holders(ASSET)
    balances = dict(zip(frame["address"].to_list(), frame["balance"].to_list(), strict=True))

    assert balances[ALICE] == pytest.approx(350.0)
    assert balances[BOB] == pytest.approx(100.0)
    assert frame["balance"].sum() == pytest.approx(450.0)


def test_the_zero_address_is_not_a_holder(cache_root: Path) -> None:
    frame = source(cache_root, ledger_node()).fetch_holders(ASSET)
    assert ZERO_ADDRESS not in frame["address"].to_list()


def test_a_matching_reconstruction_is_reported_as_exact(
    cache_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # The property that makes deriving balances worth doing at all.
    with caplog.at_level(logging.INFO):
        source(cache_root, ledger_node()).fetch_holders(ASSET)
    assert "matches totalSupply() exactly" in caplog.text


def test_a_mismatch_against_total_supply_is_flagged_loudly(
    cache_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # A rebasing token changes balances without emitting transfers, so a
    # distribution derived from transfers alone is wrong. It has to be said.
    with caplog.at_level(logging.WARNING):
        source(cache_root, ledger_node(total_supply=900.0)).fetch_holders(ASSET)

    assert "rebasing" in caplog.text
    assert "unreliable" in caplog.text


def test_an_incomplete_history_producing_negative_balances_is_flagged(
    cache_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # A sender with no prior credit means logs are missing.
    node = Node([log(sender=ALICE, recipient=BOB, amount=100.0)], total_supply=100.0)
    with caplog.at_level(logging.WARNING):
        source(cache_root, node).fetch_holders(ASSET)
    assert "negative balance" in caplog.text


def test_zero_value_transfers_do_not_create_phantom_holders(cache_root: Path) -> None:
    # The fourth log in the fixture moves 0 tokens. It must not add an address
    # with a zero balance to the distribution.
    frame = source(cache_root, ledger_node()).fetch_holders(ASSET)
    assert frame.height == 2


# ---------------------------------------------------------------------------
# Contract and caching
# ---------------------------------------------------------------------------


def test_the_adapter_declares_all_three_capabilities(cache_root: Path) -> None:
    # The only source that can answer every question, and it needs no key.
    adapter = source(cache_root, Node(total_supply=1.0))
    assert adapter.supports(Capability.ASSET_SNAPSHOT)
    assert adapter.supports(Capability.TRANSFER_EVENT)
    assert adapter.supports(Capability.HOLDER_BALANCE)


def test_repeated_reads_are_served_from_cache(cache_root: Path) -> None:
    node = ledger_node()
    adapter = source(cache_root, node)
    adapter.fetch_holders(ASSET)
    before = len(node.calls)
    adapter.fetch_holders(ASSET)

    # The head block is deliberately refetched; everything else comes off disk.
    new_calls = [method for method, _ in node.calls[before:]]
    assert new_calls == ["eth_blockNumber"]
