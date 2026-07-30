"""Ethereum JSON-RPC adapter: real on-chain data, no API key.

This is the only source that supplies all three normalized frames, and the only
one whose numbers this package can *verify* rather than trust.

**Why it exists.** Every liquidity metric here needs transfer-level data, and the
providers that sell it need a key. That left the package able to demonstrate its
metrics only on constructed data. Public Ethereum RPC endpoints serve
`eth_getLogs` and `eth_call` without credentials, so the same measurements can be
made directly against the chain.

**Why it is tractable.** Reconstructing holder balances means replaying a token's
entire `Transfer` history from deployment, which sounds prohibitive. It is not,
for exactly the assets this package studies: tokenized funds are thin. BUIDL's
complete history is about 15,000 logs, fetched in nine requests and a few
seconds. A liquid retail token would be hopeless here; a tokenized treasury fund
is not.

**Why it is trustworthy.** After replaying the ledger, the reconstructed balances
are summed and compared against the contract's own `totalSupply()`. If the two
agree to the raw unit, the holder distribution is correct by construction --
there is no provider to take on faith and no truncated top-N list. If they
disagree, something about the token breaks the assumption (a rebasing balance, a
non-standard transfer path) and the adapter says so rather than publishing a
distribution it cannot justify.

That check is the strongest data-integrity property in the package, and it is
only possible because the data is derived rather than fetched.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import polars as pl

from rwa_liquidity.schema.frames import AssetSnapshot, HolderBalance, TransferEvent
from rwa_liquidity.schema.types import ZERO_ADDRESS
from rwa_liquidity.schema.validation import polars_schema, validate
from rwa_liquidity.sources.base import Capability, Source, SourceFetchError
from rwa_liquidity.sources.classify import classify_transfers
from rwa_liquidity.sources.http import CachedJSONClient

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, Sequence
    from datetime import timedelta

    import httpx

    from rwa_liquidity.cache.store import ParquetCache
    from rwa_liquidity.schema.asset import AssetRef

__all__ = ["DEFAULT_RPC_URL", "TRANSFER_TOPIC", "EvmRpcSource"]

logger = logging.getLogger(__name__)

#: A keyless mainnet endpoint that serves `eth_getLogs`. Most public endpoints do
#: not: they answer `eth_blockNumber` and `eth_call` happily and then return 403
#: or a 50-block range cap for log queries. This one was verified on 2026-07-30;
#: override it with `rpc_url` or the `EVM_RPC_URL` environment variable.
DEFAULT_RPC_URL: Final = "https://rpc.mevblocker.io"

#: `keccak256("Transfer(address,address,uint256)")`.
TRANSFER_TOPIC: Final = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Function selectors, i.e. the first four bytes of the keccak hash of each
# signature. Hard-coded rather than computed: adding a keccak implementation to
# hash four constant strings would be a dependency for nothing.
_SELECTOR_DECIMALS: Final = "0x313ce567"  # decimals()
_SELECTOR_TOTAL_SUPPLY: Final = "0x18160ddd"  # totalSupply()
_SELECTOR_SYMBOL: Final = "0x95d89b41"  # symbol()
_SELECTOR_NAME: Final = "0x06fdde03"  # name()

#: An ERC-20 `Transfer` has two indexed parameters, so three topics. ERC-721
#: reuses the same event signature but indexes the token id as well, giving four.
#: Counting a stream of NFT transfers as fungible volume would be nonsense, so
#: four-topic logs are skipped.
_ERC20_TOPIC_COUNT: Final = 3

#: A 256-bit word is 32 bytes, i.e. 64 hex characters.
_WORD_HEX: Final = 64

#: Default ceiling on how many logs a single scan will accept. A tokenized fund
#: is well inside this; a widely traded token is not, and stopping with a clear
#: message beats issuing thousands of requests against a free endpoint.
DEFAULT_MAX_LOGS: Final = 250_000

#: Retries per request. Public endpoints return transient 502/504 under load.
_RETRIES: Final = 3

#: Minimum seconds between requests. A full-history scan issues its requests in
#: a burst, which is exactly what trips a free endpoint's rate limiter; spacing
#: them costs a few seconds and avoids being throttled for minutes.
DEFAULT_MIN_INTERVAL: Final = 0.15

#: Balances below this many raw units are treated as zero. Integer arithmetic
#: makes this exact, so the only reason to have it at all is to drop the dust a
#: rounding-based token can leave behind.
_DUST: Final = 0


def _to_address(topic: str) -> str:
    """Extract an address from a 32-byte indexed topic.

    An indexed address is left-padded to a full word, so the address is the last
    20 bytes. Returned lowercase, which is the canonical form this package uses.
    """
    return "0x" + topic[-40:].lower()


def _decode_uint(raw: str | None) -> int | None:
    """Decode a single `uint256` return value."""
    if not raw or raw == "0x":
        return None
    try:
        return int(raw, 16)
    except ValueError:
        return None


def _decode_string(raw: str | None) -> str | None:
    """Decode a returned string, handling both ABI encodings in the wild.

    A conformant token returns a dynamic `string`: an offset word, a length word,
    then the bytes. Several older tokens return a fixed `bytes32` instead, with
    the text left-aligned and null-padded. Both appear among real RWA tokens, so
    both are handled.
    """
    if not raw or raw == "0x":
        return None
    body = bytes.fromhex(raw[2:])
    if len(body) < 2 * _WORD_HEX // 2:
        # Too short to carry offset and length words: treat as bytes32.
        return body.rstrip(b"\x00").decode("utf-8", "replace").strip() or None
    length = int.from_bytes(body[32:64], "big")
    if 0 < length <= len(body) - 64:
        text = body[64 : 64 + length].decode("utf-8", "replace").strip()
        return text or None
    return body[:32].rstrip(b"\x00").decode("utf-8", "replace").strip() or None


class EvmRpcSource(Source):
    """On-chain transfers, holder balances and supply, straight from a node."""

    name = "evm_rpc"
    capabilities = frozenset(
        {Capability.ASSET_SNAPSHOT, Capability.TRANSFER_EVENT, Capability.HOLDER_BALANCE}
    )

    def __init__(  # noqa: PLR0913 -- keyword-only seams for cache, transport,
        # endpoint, issuer map, scan budget and ttl; none are positional.
        self,
        *,
        cache: ParquetCache | None = None,
        client: httpx.Client | None = None,
        rpc_url: str | None = None,
        issuer_addresses: Mapping[str, Collection[str]] | None = None,
        max_logs: int = DEFAULT_MAX_LOGS,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        ttl: timedelta | None = None,
    ) -> None:
        """Create the adapter.

        Args:
            cache: Cache to read and write through.
            client: An httpx client; tests inject one with a mock transport.
            rpc_url: JSON-RPC endpoint. Defaults to `EVM_RPC_URL` in the
                environment, then to `DEFAULT_RPC_URL`.
            issuer_addresses: Per-asset treasury addresses whose transfers are
                primary rather than secondary, keyed by asset uid.
            max_logs: Refuse a scan that would exceed this many logs.
            min_interval: Minimum seconds between requests, to stay under a free
                endpoint's rate limit.
            ttl: Freshness window for cached responses. On-chain history is
                immutable, so a long or unbounded ttl is safe for old blocks.
        """
        from rwa_liquidity.config import optional_setting  # noqa: PLC0415 -- avoids a cycle

        self._rpc_url = (rpc_url or optional_setting("EVM_RPC_URL") or DEFAULT_RPC_URL).rstrip("/")
        self._issuers = {uid.lower(): tuple(v) for uid, v in (issuer_addresses or {}).items()}
        self._max_logs = max_logs
        self._min_interval = min_interval
        self._last_request = 0.0
        self._ttl = ttl
        self._http = CachedJSONClient(source=self.name, cache=cache, client=client)
        self._request_id = 0

    # -- plumbing -----------------------------------------------------------

    def _rpc(
        self,
        method: str,
        params: Sequence[Any],
        *,
        dataset: str,
        cache_key: str,
        refresh: bool = False,
    ) -> Any:
        """Issue one JSON-RPC call and return its `result`.

        Raises:
            SourceFetchError: On transport failure or a JSON-RPC error object.
        """
        self._request_id += 1
        # Pace only real calls: a cache hit costs the endpoint nothing, and
        # sleeping before one would make a cached run needlessly slow.
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()
        response = self._http.post_json(
            self._rpc_url,
            dataset=dataset,
            body={
                "jsonrpc": "2.0",
                "id": self._request_id,
                "method": method,
                "params": list(params),
            },
            cache_params={"call": cache_key},
            ttl=self._ttl,
            refresh=refresh,
            retries=_RETRIES,
        )
        payload = response.payload
        if not isinstance(payload, dict):
            raise SourceFetchError(f"{self.name}: {method} did not return a JSON object")
        if "error" in payload:
            raise SourceFetchError(f"{self.name}: {method} failed: {payload['error']}")
        return payload.get("result")

    def _call(self, address: str, selector: str, *, refresh: bool = False) -> str | None:
        result = self._rpc(
            "eth_call",
            [{"to": address, "data": selector}, "latest"],
            dataset="eth_call",
            cache_key=f"{address}:{selector}",
            refresh=refresh,
        )
        return result if isinstance(result, str) else None

    def head_block(self, *, refresh: bool = True) -> int:
        """Return the current chain head.

        Defaults to refreshing: a cached head block would silently pin every
        subsequent scan to an old tip.
        """
        result = self._rpc("eth_blockNumber", [], dataset="head", cache_key="head", refresh=refresh)
        block = _decode_uint(result if isinstance(result, str) else None)
        if block is None:
            raise SourceFetchError(f"{self.name}: eth_blockNumber returned {result!r}")
        return block

    def _logs(
        self,
        address: str,
        low: int,
        high: int,
        *,
        collected: list[dict[str, Any]],
        refresh: bool,
    ) -> None:
        """Fetch Transfer logs for `[low, high]`, splitting when the node balks.

        Nodes cap results rather than paginating, and the cap differs between
        providers. Rather than guessing a safe block span, the range is halved
        whenever a query is rejected. That adapts to whatever the endpoint
        allows and costs one wasted request per split.
        """
        self._check_budget(collected)
        try:
            result = self._rpc(
                "eth_getLogs",
                [
                    {
                        "address": address,
                        "topics": [TRANSFER_TOPIC],
                        "fromBlock": hex(low),
                        "toBlock": hex(high),
                    }
                ],
                dataset="eth_getLogs",
                cache_key=f"{address}:{low}:{high}",
                refresh=refresh,
            )
        except SourceFetchError:
            if low >= high:
                raise
            middle = (low + high) // 2
            self._logs(address, low, middle, collected=collected, refresh=refresh)
            self._logs(address, middle + 1, high, collected=collected, refresh=refresh)
            return

        if not isinstance(result, list):
            raise SourceFetchError(f"{self.name}: eth_getLogs returned {type(result).__name__}")
        collected.extend(log for log in result if isinstance(log, dict))
        # Checked again after extending, not only before the request: a node that
        # answers the whole range in one call would otherwise blow the budget
        # without it ever being consulted.
        self._check_budget(collected)

    def _check_budget(self, collected: Sequence[Any]) -> None:
        if len(collected) > self._max_logs:
            raise SourceFetchError(
                f"{self.name}: the scan reached {len(collected):,} logs, past the "
                f"{self._max_logs:,} limit. This token is too active for full-history "
                f"reconstruction against a public endpoint; raise max_logs, or use a "
                f"source that provides holder balances directly."
            )

    def _block_times(self, blocks: Iterable[int], *, refresh: bool) -> dict[int, datetime]:
        """Look up timestamps for blocks whose logs did not carry one.

        Most endpoints now include `blockTimestamp` on each log, which avoids a
        request per block. This is the fallback for those that do not, and it is
        deliberately per-block and cached: an incorrect timestamp would move a
        transfer into or out of its observation window.
        """
        times: dict[int, datetime] = {}
        for number in sorted(set(blocks)):
            result = self._rpc(
                "eth_getBlockByNumber",
                [hex(number), False],
                dataset="eth_getBlockByNumber",
                cache_key=f"block:{number}",
                refresh=refresh,
            )
            stamp = _decode_uint(result.get("timestamp") if isinstance(result, dict) else None)
            if stamp is None:
                raise SourceFetchError(f"{self.name}: block {number} has no timestamp")
            times[number] = datetime.fromtimestamp(stamp, tz=UTC)
        return times

    # -- decoding -----------------------------------------------------------

    def _decode_logs(self, logs: Sequence[Mapping[str, Any]], *, refresh: bool) -> pl.DataFrame:
        """Turn raw logs into rows, resolving each one's block time."""
        rows: list[dict[str, Any]] = []
        missing_times: list[int] = []
        skipped_non_erc20 = 0

        for log in logs:
            topics = log.get("topics")
            if not isinstance(topics, list) or len(topics) != _ERC20_TOPIC_COUNT:
                skipped_non_erc20 += 1
                continue
            block = _decode_uint(log.get("blockNumber"))
            index = _decode_uint(log.get("logIndex"))
            value = _decode_uint(log.get("data")) or 0
            tx_hash = log.get("transactionHash")
            if block is None or index is None or not isinstance(tx_hash, str):
                skipped_non_erc20 += 1
                continue

            stamp = _decode_uint(log.get("blockTimestamp"))
            if stamp is None:
                missing_times.append(block)
            rows.append(
                {
                    "block": block,
                    "log_index": index,
                    "tx_hash": tx_hash,
                    "from_address": _to_address(topics[1]),
                    "to_address": _to_address(topics[2]),
                    "raw_amount": value,
                    "block_time": datetime.fromtimestamp(stamp, tz=UTC) if stamp else None,
                }
            )

        if skipped_non_erc20:
            logger.warning(
                "%s skipped %d log(s) that are not two-parameter ERC-20 transfers "
                "(most likely ERC-721, which reuses the same event signature)",
                self.name,
                skipped_non_erc20,
            )

        if missing_times:
            resolved = self._block_times(missing_times, refresh=refresh)
            for row in rows:
                if row["block_time"] is None:
                    row["block_time"] = resolved[row["block"]]

        return pl.DataFrame(
            rows,
            schema={
                "block": pl.Int64(),
                "log_index": pl.Int64(),
                "tx_hash": pl.String(),
                "from_address": pl.String(),
                "to_address": pl.String(),
                "raw_amount": pl.Int128(),
                "block_time": pl.Datetime("us", "UTC"),
            },
        )

    def _token_facts(self, asset: AssetRef, *, refresh: bool) -> dict[str, Any]:
        """Read decimals, supply, symbol and name straight off the contract."""
        decimals = _decode_uint(self._call(asset.address, _SELECTOR_DECIMALS, refresh=refresh))
        if decimals is None:
            raise SourceFetchError(
                f"{self.name}: {asset.uid} did not answer decimals(); it may not be an "
                f"ERC-20 contract"
            )
        return {
            "decimals": decimals,
            "raw_total_supply": _decode_uint(
                self._call(asset.address, _SELECTOR_TOTAL_SUPPLY, refresh=refresh)
            ),
            "symbol": _decode_string(self._call(asset.address, _SELECTOR_SYMBOL, refresh=refresh)),
            "name": _decode_string(self._call(asset.address, _SELECTOR_NAME, refresh=refresh)),
        }

    # -- public interface ---------------------------------------------------

    def fetch_asset_snapshots(
        self,
        assets: Sequence[AssetRef],
        *,
        refresh: bool = False,
    ) -> pl.DataFrame:
        """Return supply, decimals, symbol and name read from each contract.

        These figures are exact rather than reported: they come from the token's
        own state, not from a provider's index of it. No price is included --
        a node does not know prices, and inventing one is not this adapter's job.
        """
        schema = dict(polars_schema(AssetSnapshot))
        rows: list[dict[str, Any]] = []
        for asset in dict.fromkeys(assets):
            facts = self._token_facts(asset, refresh=refresh)
            scale = 10 ** facts["decimals"]
            raw_supply = facts["raw_total_supply"]
            rows.append(
                {
                    "asset_uid": asset.uid,
                    "source": self.name,
                    "retrieved_at": datetime.now(UTC),
                    # `eth_call` at "latest" describes the chain now, so the
                    # observation time and the retrieval time genuinely coincide.
                    "as_of": datetime.now(UTC),
                    "symbol": facts["symbol"],
                    "name": facts["name"],
                    "decimals": facts["decimals"],
                    "total_supply": None if raw_supply is None else raw_supply / scale,
                    "market_value_usd": None,
                    "price_usd": None,
                    "holder_count": None,
                }
            )
        frame = pl.DataFrame(rows, schema=schema) if rows else pl.DataFrame(schema=schema)
        return validate(AssetSnapshot, frame, origin=self.name)

    def fetch_transfers(
        self,
        asset: AssetRef,
        *,
        start: datetime,
        end: datetime,
        refresh: bool = False,
    ) -> pl.DataFrame:
        """Return classified transfers for `asset` over `[start, end)`.

        The scan runs over blocks and the window is applied to the resulting
        timestamps, because block numbers and wall-clock time are only loosely
        related and guessing a block from a date would silently clip the window.
        """
        facts = self._token_facts(asset, refresh=refresh)
        scale = 10 ** facts["decimals"]
        head = self.head_block()

        collected: list[dict[str, Any]] = []
        self._logs(asset.address, 0, head, collected=collected, refresh=refresh)
        decoded = self._decode_logs(collected, refresh=refresh)

        schema = dict(polars_schema(TransferEvent))
        if decoded.is_empty():
            return validate(TransferEvent, pl.DataFrame(schema=schema), origin=self.name)

        windowed = decoded.filter((pl.col("block_time") >= start) & (pl.col("block_time") < end))
        classified = classify_transfers(
            windowed,
            issuer_addresses=self._issuers.get(asset.uid.lower(), ()),
            asset_uid=asset.uid,
        )
        frame = classified.with_columns(
            pl.lit(asset.uid).alias("asset_uid"),
            pl.lit(self.name).alias("source"),
            pl.lit(datetime.now(UTC)).alias("retrieved_at").cast(pl.Datetime("us", "UTC")),
            (pl.col("raw_amount").cast(pl.Float64) / scale).alias("amount"),
            pl.lit(None, dtype=pl.Float64).alias("amount_usd"),
        ).select(list(schema))
        return validate(TransferEvent, frame, origin=self.name)

    def fetch_holders(
        self,
        asset: AssetRef,
        *,
        as_of: datetime | None = None,
        refresh: bool = False,
    ) -> pl.DataFrame:
        """Return holder balances reconstructed from the full transfer history.

        Every `Transfer` since deployment is replayed as a ledger, and the
        resulting balances are checked against `totalSupply()`. A mismatch is
        reported loudly: it means the token's balances change by some mechanism
        other than transfers, most often rebasing, and a distribution derived
        from transfers alone would then be wrong.

        Args:
            asset: The asset to reconstruct balances for.
            as_of: Label for the snapshot. Balances are always as of the chain
                head; a past instant cannot be served from this method and
                passing one would misdate the rows.
            refresh: Bypass the cache and rescan.

        Returns:
            A validated `HolderBalance` frame, one row per address with a
            positive balance.
        """
        facts = self._token_facts(asset, refresh=refresh)
        scale = 10 ** facts["decimals"]
        head = self.head_block()

        collected: list[dict[str, Any]] = []
        self._logs(asset.address, 0, head, collected=collected, refresh=refresh)
        decoded = self._decode_logs(collected, refresh=refresh)

        ledger: dict[str, int] = defaultdict(int)
        for sender, recipient, amount in decoded.select(
            "from_address", "to_address", "raw_amount"
        ).iter_rows():
            ledger[str(sender)] -= int(amount)
            ledger[str(recipient)] += int(amount)
        ledger.pop(ZERO_ADDRESS, None)

        holders = {address: value for address, value in ledger.items() if value > _DUST}
        self._verify_reconstruction(asset, holders, facts, negative=ledger)

        stamp = as_of if as_of is not None else datetime.now(UTC)
        schema = dict(polars_schema(HolderBalance))
        if not holders:
            return validate(HolderBalance, pl.DataFrame(schema=schema), origin=self.name)

        frame = pl.DataFrame(
            {
                "asset_uid": [asset.uid] * len(holders),
                "source": [self.name] * len(holders),
                "retrieved_at": [datetime.now(UTC)] * len(holders),
                "as_of": [stamp] * len(holders),
                "address": list(holders),
                "balance": [value / scale for value in holders.values()],
                "balance_usd": [None] * len(holders),
            },
            schema=schema,
        )
        return validate(HolderBalance, frame, origin=self.name)

    def _verify_reconstruction(
        self,
        asset: AssetRef,
        holders: Mapping[str, int],
        facts: Mapping[str, Any],
        *,
        negative: Mapping[str, int],
    ) -> None:
        """Check the replayed ledger against the contract's own supply.

        This is the property that makes the reconstruction worth doing. Silence
        here means the distribution is exact.
        """
        below_zero = [address for address, value in negative.items() if value < 0]
        if below_zero:
            logger.warning(
                "%s: %d address(es) ended with a negative balance for %s. The transfer "
                "history is incomplete, so the holder distribution is unreliable.",
                self.name,
                len(below_zero),
                asset.uid,
            )

        reported = facts.get("raw_total_supply")
        if reported is None:
            logger.warning(
                "%s: %s did not answer totalSupply(), so the reconstruction could not be verified",
                self.name,
                asset.uid,
            )
            return

        reconstructed = sum(holders.values())
        if reconstructed != reported:
            scale = 10 ** facts["decimals"]
            logger.warning(
                "%s: reconstructed balances for %s sum to %s but totalSupply() reports %s "
                "(difference %s raw units). Balances change by some mechanism other than "
                "Transfer events -- most often rebasing -- so the holder distribution and "
                "every concentration metric derived from it are unreliable for this token.",
                self.name,
                asset.uid,
                f"{reconstructed / scale:,.6f}",
                f"{reported / scale:,.6f}",
                reconstructed - reported,
            )
        else:
            logger.info(
                "%s: holder reconstruction for %s matches totalSupply() exactly across %d holders",
                self.name,
                asset.uid,
                len(holders),
            )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()
