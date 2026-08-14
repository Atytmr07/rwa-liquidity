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
import polars as pl
import pytest

from rwa_liquidity.cache import ParquetCache
from rwa_liquidity.schema.asset import AssetRef
from rwa_liquidity.schema.types import ZERO_ADDRESS, TransferKind
from rwa_liquidity.sources import (
    Capability,
    EvmRpcSource,
    SourceFetchError,
    SourceTransportError,
    evm_rpc,
)
from rwa_liquidity.sources.evm_rpc import _MIN_BLOCK_STEP, TRANSFER_TOPIC

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
        deployed_at: int = 0,
        span_limit: int | None = None,
    ) -> None:
        self.deployed_at = deployed_at
        self.span_limit = span_limit
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
        if method == "eth_getCode":
            # "0x" before the contract existed, bytecode from then on.
            at = HEAD if params[1] == "latest" else int(params[1], 16)
            return ok("0x60806040" if at >= self.deployed_at else "0x")
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
        wanted = str(query["address"]).lower()
        selected = [
            e
            for e in self.logs
            if low <= int(e["blockNumber"], 16) <= high and e["address"].lower() == wanted
        ]
        if self.span_limit is not None and high - low + 1 > self.span_limit:
            # What public endpoints actually enforce: a cap on the block span,
            # regardless of how many results the query would return.
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32602,
                        "message": f"range {high - low + 1} exceeds limit of {self.span_limit}",
                    },
                },
            )
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


def funded(*entries: dict[str, Any], amount: float = 1_000_000.0) -> list[dict[str, Any]]:
    """Prepend a mint so the senders in `entries` actually hold something.

    A token's first log cannot be a holder-to-holder transfer: there would be
    nothing to send. Fixtures that skipped this modelled an impossible chain and
    are now correctly rejected by the supply-invariant check.
    """
    mint = log(sender=ZERO_ADDRESS, recipient=ALICE, amount=amount, block=20_000_000, index=0)
    return [mint, *entries]


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
    node = Node(
        funded(log(sender=ALICE, recipient=BOB, amount=100.0, index=1)),
        total_supply=1_000_000.0,
    )
    frame = source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)
    trade = frame.filter(pl.col("kind") == TransferKind.SECONDARY.value)

    assert trade["from_address"].item() == ALICE
    assert trade["to_address"].item() == BOB


def test_amounts_are_scaled_by_the_tokens_decimals(cache_root: Path) -> None:
    node = Node(
        funded(log(sender=ALICE, recipient=BOB, amount=1_234.5, index=1)),
        total_supply=1_000_000.0,
    )
    frame = source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)
    trade = frame.filter(pl.col("kind") == TransferKind.SECONDARY.value)
    assert trade["amount"].item() == pytest.approx(1_234.5)


def test_erc721_logs_are_skipped(cache_root: Path, caplog: pytest.LogCaptureFixture) -> None:
    # ERC-721 reuses the ERC-20 Transfer signature but indexes the token id,
    # giving four topics. Counting NFT movements as fungible volume is nonsense.
    node = Node(
        funded(
            log(sender=ALICE, recipient=BOB, amount=100.0, index=1),
            log(sender=ALICE, recipient=BOB, amount=999.0, index=2, extra_topic=True),
        ),
        total_supply=1_000_000.0,
    )
    with caplog.at_level(logging.WARNING):
        frame = source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)

    trades = frame.filter(pl.col("kind") == TransferKind.SECONDARY.value)
    assert trades.height == 1
    assert trades["amount"].item() == pytest.approx(100.0)
    assert "ERC-721" in caplog.text


def test_transfers_outside_the_window_are_dropped(cache_root: Path) -> None:
    node = Node(
        [
            log(
                sender=ZERO_ADDRESS,
                recipient=ALICE,
                amount=1_000_000.0,
                block=20_000_000,
                index=0,
                timestamp=OUTSIDE,
            ),
            log(sender=ALICE, recipient=BOB, amount=100.0, index=1, timestamp=INSIDE),
            log(sender=ALICE, recipient=BOB, amount=999.0, index=2, timestamp=OUTSIDE),
        ],
        total_supply=1_000_000.0,
    )
    frame = source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)
    assert frame["amount"].to_list() == [pytest.approx(100.0)]


def test_missing_block_timestamp_falls_back_to_a_block_lookup(cache_root: Path) -> None:
    # Not every endpoint puts blockTimestamp on the log. Guessing would move a
    # transfer into or out of its observation window.
    node = Node(
        funded(
            log(
                sender=ALICE,
                recipient=BOB,
                amount=100.0,
                block=21_000_042,
                index=1,
                timestamp=None,
            )
        ),
        total_supply=1_000_000.0,
        block_timestamps={21_000_042: INSIDE},
    )
    frame = source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)

    assert frame.filter(pl.col("kind") == TransferKind.SECONDARY.value).height == 1
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
    node = Node(
        [
            log(
                sender=ZERO_ADDRESS,
                recipient=TREASURY,
                amount=1_000.0,
                block=20_000_000,
                index=0,
            ),
            log(sender=TREASURY, recipient=ALICE, amount=500.0, index=1),
        ],
        total_supply=1_000.0,
    )
    frame = source(cache_root, node, issuer_addresses={ASSET.uid: [TREASURY]}).fetch_transfers(
        ASSET, start=START, end=END
    )
    # Both the zero-address mint and the treasury distribution are primary.
    assert set(frame["kind"].to_list()) == {TransferKind.MINT.value}


# ---------------------------------------------------------------------------
# Range splitting and budget
# ---------------------------------------------------------------------------


def test_a_rejected_range_is_halved_rather_than_guessed(cache_root: Path) -> None:
    # Nodes cap results instead of paginating, and the cap differs by provider.
    # Halving on rejection adapts to whatever the endpoint allows.
    entries = [
        log(
            sender=ZERO_ADDRESS,
            recipient=ALICE,
            amount=1.0,
            block=1_000_000 * (i + 1),
            index=i,
        )
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


def test_a_network_failure_does_not_split_the_range(cache_root: Path) -> None:
    # The bug this guards against cost seven hours of wall clock. A dropped
    # connection carries no verdict on the block span, but the splitter treated
    # it as one, so every half was retried as two narrower queries that failed
    # the same way and split again. The endpoint here answers everything except
    # the log queries, so the scan reaches the splitter with a live connection
    # to the node -- exactly the shape of the real incident, where the machine
    # lost DNS part-way through a walk.
    node = Node(
        funded(log(sender=ALICE, recipient=BOB, amount=1.0, index=1)),
        total_supply=1_000_000.0,
    )
    spans: list[tuple[int, int]] = []

    def drop_log_queries(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "eth_getLogs":
            query = body["params"][0]
            spans.append((int(query["fromBlock"], 16), int(query["toBlock"], 16)))
            raise httpx.ConnectError("getaddrinfo failed", request=request)
        return node.handle(request)

    adapter = EvmRpcSource(
        cache=ParquetCache(cache_root),
        client=httpx.Client(transport=httpx.MockTransport(drop_log_queries)),
        rpc_url="https://node.invalid",
        min_interval=0.0,
    )
    with pytest.raises(SourceTransportError, match="getaddrinfo"):
        adapter.fetch_transfers(ASSET, start=START, end=END)

    # Repeats of one span are the retry budget doing its job. More than one
    # *distinct* span means the range was subdivided, which is the fault: the
    # node never said anything about the range, so there was nothing to react to.
    assert len(set(spans)) == 1, f"a network fault was mistaken for a rejection: {set(spans)}"


def test_the_request_budget_bounds_a_runaway_scan(cache_root: Path) -> None:
    # A backstop for the whole class of fault rather than the one instance of
    # it: whatever makes a scan split without converging, it stops being an
    # unbounded wait and becomes an error naming the cause. A rejection that
    # never resolves does terminate on its own once the span reaches one block,
    # so the budget is set below that depth here to reach the guard at all.
    node = Node(
        [
            log(sender=ZERO_ADDRESS, recipient=ALICE, amount=1.0, block=1_000 * (i + 1), index=i)
            for i in range(40)
        ],
        total_supply=40.0,
        # Reject every query: no span is ever small enough to satisfy the node.
        log_limit=0,
    )
    with pytest.raises(SourceFetchError, match="eth_getLogs calls"):
        source(cache_root, node, max_log_requests=5).fetch_transfers(ASSET, start=START, end=END)


def test_a_span_capped_endpoint_costs_requests_proportional_to_the_token(
    cache_root: Path,
) -> None:
    # The reason a scan of this registry took hours. Public endpoints cap a log
    # query by block span, not by result count, so a walk from genesis costs one
    # request per 10,000 blocks of *chain* -- thousands of them -- however
    # inactive the token is. A token deployed near the tip should cost requests
    # proportional to its own history, not to Ethereum's.
    deployed = HEAD - 30_000
    node = Node(
        [log(sender=ZERO_ADDRESS, recipient=ALICE, amount=5.0, block=deployed + 10, index=0)],
        total_supply=5.0,
        deployed_at=deployed,
        span_limit=10_000,
    )
    frame = source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)

    assert frame.height == 1
    queries = sum(1 for method, _ in node.calls if method == "eth_getLogs")
    # Genesis to head at 10,000 blocks a query would be over 2,500. The token's
    # own 30,000 blocks are four windows, plus the span discovery.
    assert queries < 30, f"{queries} log queries for a token 30,000 blocks old"


def test_a_dense_stretch_does_not_shrink_the_window_for_everything_after_it(
    cache_root: Path,
) -> None:
    # This one cost five hours of wall clock. BUIDL crowds 11,622 mints into a
    # few million blocks, so a window sized to the endpoint's span limit holds
    # more logs than it will return. Narrowing the shared step in response
    # treated one token's density as a fact about the endpoint: the step fell to
    # its floor and every window afterwards, for every remaining asset, asked for
    # 500 blocks at a time. The dense stretch has to be split on its own.
    deployed = HEAD - 100_000
    crowd = [
        log(
            sender=ZERO_ADDRESS, recipient=ALICE, amount=1.0, block=deployed + 10 + i * 200, index=i
        )
        for i in range(40)
    ]
    node = Node(
        crowd,
        total_supply=40.0,
        deployed_at=deployed,
        span_limit=10_000,
        # The span is acceptable; what it contains is not.
        log_limit=20,
    )
    adapter = source(cache_root, node)
    frame = adapter.fetch_transfers(ASSET, start=START, end=END)

    assert frame.height == 40
    spans = [
        int(params[0]["toBlock"], 16) - int(params[0]["fromBlock"], 16) + 1
        for method, params in node.calls
        if method == "eth_getLogs"
    ]
    # The narrow queries belong to the crowded window. Everything after it must
    # go back to asking for the full span the endpoint allows.
    assert max(spans[-3:]) == adapter._step, f"the step never recovered: {spans[-6:]}"
    assert len(spans) < 60, f"{len(spans)} queries for a token 100,000 blocks old"


def test_throttling_is_waited_out_rather_than_fatal(
    cache_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The pause is real seconds against a real endpoint and nothing against a
    # mock, which has no load to relieve.
    monkeypatch.setattr(evm_rpc, "_OVERLOAD_PAUSE", 0.0)
    # The endpoint throttles with -32603 over HTTP 200, which the transport's own
    # retry budget never sees: it inspects status codes, and this arrives as a
    # success. Without a retry here a scan that is momentarily asked to slow down
    # loses the whole asset.
    node = Node(funded(), total_supply=1_000_000.0)
    refusals = 2

    def throttle_then_serve(request: httpx.Request) -> httpx.Response:
        nonlocal refusals
        body = json.loads(request.content)
        if body["method"] == "eth_getLogs" and refusals > 0:
            refusals -= 1
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {"code": -32603, "message": "service temporarily unavailable"},
                },
            )
        return node.handle(request)

    adapter = EvmRpcSource(
        cache=ParquetCache(cache_root),
        client=httpx.Client(transport=httpx.MockTransport(throttle_then_serve)),
        rpc_url="https://node.invalid",
        min_interval=0.0,
    )
    frame = adapter.fetch_transfers(ASSET, start=START, end=END)

    assert frame.height == 1
    assert refusals == 0


def test_an_overloaded_node_is_not_answered_by_splitting_the_range(
    cache_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(evm_rpc, "_OVERLOAD_PAUSE", 0.0)
    # The endpoint returns {"code": -32603, "message": "service temporarily
    # unavailable"} over HTTP 200 when it is struggling. Read as a refusal of the
    # range, that makes the scanner split and send two queries where it sent one,
    # to a node that is already overloaded -- so the scan feeds the condition it
    # is reacting to. JSON-RPC defines -32603 as a fault in the server, which is
    # exactly the distinction needed.
    node = Node(funded(), total_supply=1_000_000.0)
    seen: list[tuple[int, int]] = []

    def overloaded(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "eth_getLogs":
            query = body["params"][0]
            seen.append((int(query["fromBlock"], 16), int(query["toBlock"], 16)))
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {"code": -32603, "message": "service temporarily unavailable"},
                },
            )
        return node.handle(request)

    adapter = EvmRpcSource(
        cache=ParquetCache(cache_root),
        client=httpx.Client(transport=httpx.MockTransport(overloaded)),
        rpc_url="https://node.invalid",
        min_interval=0.0,
    )
    with pytest.raises(SourceTransportError, match="unavailable"):
        adapter.fetch_transfers(ASSET, start=START, end=END)

    assert len(set(seen)) == 1, f"an overloaded node was answered by splitting: {set(seen)}"


def test_the_span_limit_is_read_from_the_node_rather_than_searched_for(
    cache_root: Path,
) -> None:
    # The node states its limit outright. Bisecting for it instead settled on
    # 6,236 against a real limit of 10,000, because a probe refused for any
    # other reason -- a rate limit, most likely -- reads as "too wide" and drags
    # the estimate down for every window afterwards.
    node = Node(funded(), total_supply=1_000_000.0, span_limit=10_000)
    adapter = source(cache_root, node)
    adapter.fetch_transfers(ASSET, start=START, end=END)

    assert adapter._step == 10_000
    probes = sum(
        1
        for method, params in node.calls
        if method == "eth_getLogs" and params[0]["address"] == ZERO_ADDRESS
    )
    assert probes == 1, f"{probes} probes to read a number the node volunteered"


def test_an_endpoint_that_states_no_limit_is_bisected_for(cache_root: Path) -> None:
    # The fallback, for a node that refuses without saying why. Approximate is
    # acceptable here: a scan that asks for less than it could is slow, not
    # wrong.
    node = Node(funded(), total_supply=1_000_000.0, span_limit=10_000)

    def strip_the_reason(request: httpx.Request) -> httpx.Response:
        response = node.handle(request)
        body = response.json()
        if "error" in body and "limit of" in str(body["error"]):
            body["error"] = {"code": -32602, "message": "query failed"}
            return httpx.Response(200, json=body)
        return response

    adapter = EvmRpcSource(
        cache=ParquetCache(cache_root),
        client=httpx.Client(transport=httpx.MockTransport(strip_the_reason)),
        rpc_url="https://node.invalid",
        min_interval=0.0,
    )
    adapter.fetch_transfers(ASSET, start=START, end=END)

    assert adapter._step is not None
    assert _MIN_BLOCK_STEP <= adapter._step <= 10_000


def test_a_generous_endpoint_is_not_punished_for_it(cache_root: Path) -> None:
    # The mirror of the test above: an endpoint with no span cap should answer
    # the whole history in one query. A fixed window size would have issued
    # thousands here, which is how the first attempt at this was caught.
    node = Node(funded(), total_supply=1_000_000.0)
    source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)

    # Counted for the token itself: the span probe is one more query, against the
    # zero address, and it is answered on the first try when nothing is capped.
    for_token = [
        params[0]
        for method, params in node.calls
        if method == "eth_getLogs" and params[0]["address"].lower() == ASSET.address
    ]
    assert len(for_token) == 1


def test_a_node_without_history_is_scanned_from_genesis(cache_root: Path) -> None:
    # Deployment detection is an optimisation, and it fails safe: an endpoint
    # that will not answer eth_getCode historically gets the slow, complete walk
    # rather than a truncated one, because missing early blocks would silently
    # drop the mints a reconstruction depends on.
    node = Node(funded(), total_supply=1_000_000.0)

    def refuse_get_code(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "eth_getCode":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {"code": -32000, "message": "no"},
                },
            )
        return node.handle(request)

    adapter = EvmRpcSource(
        cache=ParquetCache(cache_root),
        client=httpx.Client(transport=httpx.MockTransport(refuse_get_code)),
        rpc_url="https://node.invalid",
        min_interval=0.0,
    )
    frame = adapter.fetch_holders(ASSET)

    assert frame.height == 1
    spans = [params[0] for method, params in node.calls if method == "eth_getLogs"]
    assert int(spans[0]["fromBlock"], 16) == 0


def test_the_request_budget_is_per_scan_not_per_source(cache_root: Path) -> None:
    # One source object serves every asset in the registry, so a budget that
    # accumulated across scans would fail the later assets for work the earlier
    # ones did.
    node = Node(funded(), total_supply=1_000_000.0)
    adapter = source(cache_root, node)

    adapter.fetch_transfers(ASSET, start=START, end=END)
    # Reading the private counter is the point of the test: the reset is not
    # observable any other way until a scan is long enough to exhaust a budget.
    first = adapter._requests
    adapter.fetch_transfers(ASSET, start=START, end=END, refresh=True)

    # No larger than the first scan, so nothing accumulated. Smaller is expected
    # rather than suspicious: the first scan pays to discover the endpoint's
    # span limit and every scan after it reuses the answer.
    assert 0 < adapter._requests <= first


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
    # BOB sends 50 having never received anything. The transfer is within the
    # supply that exists, so the invariant check passes it, but the ledger it
    # produces is impossible -- which means logs are missing.
    node = Node(
        funded(log(sender=BOB, recipient=TREASURY, amount=50.0, index=1), amount=100.0),
        total_supply=100.0,
    )
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


def test_a_transfer_larger_than_the_supply_in_existence_is_dropped(
    cache_root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # CACHE Gold really does emit one of these: 1.1e40 raw units against a supply
    # of about 1e13. Left in the sum, a single such term would dominate every
    # volume metric. Outside a mint, a transfer cannot move tokens that do not
    # exist, so the bound is an ERC-20 invariant rather than a chosen threshold.
    node = Node(
        funded(log(sender=ALICE, recipient=BOB, amount=1e30, index=1), amount=1_000.0),
        total_supply=1_000.0,
    )
    with caplog.at_level(logging.WARNING):
        frame = source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)

    assert frame.filter(pl.col("kind") == TransferKind.SECONDARY.value).is_empty()
    assert "more than the supply in existence" in caplog.text


def test_a_historical_transfer_larger_than_current_supply_is_kept(
    cache_root: Path,
) -> None:
    # The bound is the supply at the time, not today's. A fund that has since
    # shrunk legitimately has historical transfers bigger than its current
    # supply -- FDIT and the Hamilton Lane feeder both do -- and dropping those
    # would erase real activity.
    node = Node(
        [
            log(sender=ZERO_ADDRESS, recipient=ALICE, amount=1_000.0, block=20_000_000, index=0),
            log(sender=ALICE, recipient=BOB, amount=900.0, block=20_000_001, index=1),
            log(sender=BOB, recipient=ZERO_ADDRESS, amount=950.0, block=20_000_002, index=2),
        ],
        total_supply=50.0,
    )
    frame = source(cache_root, node).fetch_transfers(ASSET, start=START, end=END)
    trade = frame.filter(pl.col("kind") == TransferKind.SECONDARY.value)
    assert trade["amount"].item() == pytest.approx(900.0)


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("ZTLN\n\n   ", "ZTLN"),
        ("  BUIDL  ", "BUIDL"),
        ("Two   spaces", "Two spaces"),
        ("\x1b[31mRED\x1b[0m", "[31mRED[0m"),
        ("\x00\x01\x02", None),
    ],
)
def test_contract_supplied_labels_are_sanitized(
    cache_root: Path, supplied: str, expected: str | None
) -> None:
    # symbol() and name() are whatever the deployer wrote, and they reach a
    # terminal, a CSV and a LaTeX table. A newline wrecks table alignment -- one
    # real registry asset returns exactly that -- and an ANSI escape in a name()
    # would be executed by the terminal printing it.
    node = Node(total_supply=1.0, symbol=supplied)
    frame = source(cache_root, node).fetch_asset_snapshots([ASSET])
    assert frame["symbol"].item() == expected


def test_an_absurdly_long_label_is_truncated(cache_root: Path) -> None:
    node = Node(total_supply=1.0, symbol="X" * 500)
    frame = source(cache_root, node).fetch_asset_snapshots([ASSET])
    symbol = frame["symbol"].item()
    assert symbol is not None
    assert len(symbol) < 100
    assert symbol.endswith("...")
