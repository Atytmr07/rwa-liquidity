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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import polars as pl

from rwa_liquidity.schema.frames import AssetSnapshot, HolderBalance, TransferEvent
from rwa_liquidity.schema.types import BURN_ADDRESSES
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

__all__ = ["DEFAULT_RPC_URL", "TRANSFER_TOPIC", "EvmRpcSource", "IssuanceProfile"]

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

#: Longest contract-supplied label kept; see `_sanitize`.
_MAX_LABEL_LENGTH: Final = 80

#: Padding byte on the older bytes32 string encoding.
NUL_BYTE: Final = b"\x00"

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


@dataclass(frozen=True, slots=True)
class IssuanceProfile:
    """What a token's complete history says about how it issues.

    The point of this is to replace a blanket caveat with a per-asset fact. The
    zero-address rule can only see issuance that goes through the zero address;
    whether a given token's issuance does is answerable from its own history.

    Attributes:
        asset_uid: The asset described.
        transfers: Every classifiable transfer in its history.
        mints: Transfers out of the zero or a burn address.
        burns: Transfers into one.
        minted_supply: Total ever minted, human-scaled.
        first_mint_block: Where issuance began, if it is visible at all.
        largest_recipient: The address that received the most minted supply. A
            candidate treasury when issuance is not visible, offered for review
            rather than applied: guessing an issuer address wrong would move real
            trading into the primary bucket.
        largest_recipient_share: That address's share of everything minted.
    """

    asset_uid: str
    transfers: int
    mints: int
    burns: int
    minted_supply: float
    first_mint_block: int | None
    largest_recipient: str | None
    largest_recipient_share: float | None

    @property
    def issuance_is_visible(self) -> bool:
        """Return whether any issuance passes through the zero address."""
        return self.mints > 0

    def caveat(self) -> str | None:
        """Return what this profile means for the asset's secondary figures."""
        if self.issuance_is_visible:
            return None
        share = self.largest_recipient_share
        suffix = ""
        if self.largest_recipient is not None and share is not None:
            suffix = (
                f" The largest recipient of supply is {self.largest_recipient}, holding "
                f"{share:.1%} of everything issued; if that is the issuer's own address, "
                f"passing it as an issuer address would reclassify its distributions."
            )
        return (
            "no issuance passes through the zero address anywhere in this token's "
            "history, so the zero-address rule cannot see how it is issued. Some of "
            "what is counted as secondary trading may be distribution from an issuer, "
            "which makes every secondary figure for this asset an upper bound." + suffix
        )


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


def _sanitize(text: str) -> str | None:
    """Make a contract-supplied string safe to print and to put in a table.

    A token's `symbol()` and `name()` are whatever its deployer chose to write.
    They travel unaltered into a terminal, a CSV and a LaTeX table, so they are
    treated as untrusted input rather than as labels:

    * Control characters are dropped. A newline breaks table alignment -- one
      registry asset really does return a symbol containing whitespace that
      wrecked the rendered output -- and an ANSI escape sequence inside a
      `name()` would be acted on by the terminal it is printed to.
    * Runs of whitespace collapse to one space, and the result is trimmed.
    * An over-long value is truncated. A symbol is a ticker; a contract
      returning a paragraph is not describing one, and a very long string is a
      cheap way to disrupt any table it lands in.
    """
    kept = "".join(character for character in text if character.isprintable())
    collapsed = " ".join(kept.split())
    if not collapsed:
        return None
    if len(collapsed) > _MAX_LABEL_LENGTH:
        return collapsed[:_MAX_LABEL_LENGTH].rstrip() + "..."
    return collapsed


def _decode_string(raw: str | None) -> str | None:
    """Decode a returned string, handling both ABI encodings in the wild.

    A conformant token returns a dynamic `string`: an offset word, a length word,
    then the bytes. Several older tokens return a fixed `bytes32` instead, with
    the text left-aligned and null-padded. Both appear among real RWA tokens, so
    both are handled. The result is sanitized before it is returned; see
    `_sanitize` for why that is not paranoia.
    """
    if not raw or raw == "0x":
        return None
    body = bytes.fromhex(raw[2:])
    if len(body) < 2 * _WORD_HEX // 2:
        # Too short to carry offset and length words: treat as bytes32.
        return _sanitize(body.rstrip(NUL_BYTE).decode("utf-8", "replace"))
    length = int.from_bytes(body[32:64], "big")
    if 0 < length <= len(body) - 64:
        return _sanitize(body[64 : 64 + length].decode("utf-8", "replace"))
    return _sanitize(body[:32].rstrip(NUL_BYTE).decode("utf-8", "replace"))


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

    def _call(
        self, address: str, selector: str, *, block: int | None = None, refresh: bool = False
    ) -> str | None:
        """Read contract state, optionally at a specific block.

        Pinning matters for `totalSupply()`: the reconstruction check compares a
        ledger replayed up to some block against the supply, and reading the
        supply at "latest" instead would let activity between the two show up as
        a reconstruction failure. Not every public endpoint serves historical
        calls, so a rejection falls back to "latest" and the check becomes
        approximate rather than unavailable.
        """
        target = "latest" if block is None else hex(block)
        try:
            result = self._rpc(
                "eth_call",
                [{"to": address, "data": selector}, target],
                dataset="eth_call",
                cache_key=f"{address}:{selector}:{target}",
                refresh=refresh,
            )
        except SourceFetchError:
            if block is None:
                raise
            logger.info(
                "%s: %s does not serve historical eth_call; reading %s at latest instead",
                self.name,
                self._rpc_url,
                selector,
            )
            return self._call(address, selector, refresh=refresh)
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

    def _decode_logs(
        self, logs: Sequence[Mapping[str, Any]], *, refresh: bool
    ) -> list[dict[str, Any]]:
        """Decode raw logs into records, resolving each one's block time.

        Amounts stay Python integers here rather than going straight into a
        frame. A real token emits values that do not fit any fixed-width integer
        type -- CACHE Gold has a `Transfer` of 1.1e40 raw units against a supply
        of 100,771 -- and building a frame from those raises rather than
        producing a wrong number. Python's unbounded integers carry them through
        to the plausibility check below, which is where such a value belongs.
        """
        records: list[dict[str, Any]] = []
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
            records.append(
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
            for record in records:
                if record["block_time"] is None:
                    record["block_time"] = resolved[record["block"]]

        records.sort(key=lambda record: (record["block"], record["log_index"]))
        return records

    def _drop_implausible(
        self, records: list[dict[str, Any]], asset: AssetRef
    ) -> list[dict[str, Any]]:
        """Remove transfers that move more than the supply in existence.

        This is an invariant of ERC-20 rather than a threshold: outside of a
        mint, a transfer cannot move more tokens than exist at that moment. The
        running supply is tracked chronologically through the same log stream, so
        the bound is exact at every point rather than compared against today's
        figure -- a fund that has since shrunk legitimately has historical
        transfers larger than its current supply, and those must not be touched.

        Contracts do emit logs that violate this. CACHE Gold has three, the
        largest 1.1e40 raw units against a supply of about 1e13. Left in, a
        single such value would dominate every volume metric and make the output
        meaningless; the sum is not robust to one absurd term.
        """
        kept: list[dict[str, Any]] = []
        supply = 0
        dropped: list[int] = []
        for record in records:
            amount = int(record["raw_amount"])
            minting = record["from_address"] in BURN_ADDRESSES
            if minting:
                supply += amount
            elif amount > supply:
                dropped.append(amount)
                continue
            elif record["to_address"] in BURN_ADDRESSES:
                supply -= amount
            kept.append(record)

        if dropped:
            logger.warning(
                "%s dropped %d transfer(s) for %s that move more than the supply in "
                "existence, the largest %.3g raw units. A transfer cannot move tokens "
                "that do not exist, so these are contract artifacts rather than "
                "activity; one such value left in the sum would dominate every volume "
                "metric.",
                self.name,
                len(dropped),
                asset.uid,
                max(dropped),
            )
        return kept

    @staticmethod
    def _to_frame(records: Sequence[Mapping[str, Any]], *, scale: int) -> pl.DataFrame:
        """Build a frame of human-scaled amounts from decoded records."""
        return pl.DataFrame(
            {
                "block_time": [record["block_time"] for record in records],
                "tx_hash": [record["tx_hash"] for record in records],
                "log_index": [record["log_index"] for record in records],
                "from_address": [record["from_address"] for record in records],
                "to_address": [record["to_address"] for record in records],
                # Scaled to a float here, after the plausibility check has run on
                # the exact integers.
                "amount": [int(record["raw_amount"]) / scale for record in records],
            },
            schema={
                "block_time": pl.Datetime("us", "UTC"),
                "tx_hash": pl.String(),
                "log_index": pl.Int64(),
                "from_address": pl.String(),
                "to_address": pl.String(),
                "amount": pl.Float64(),
            },
        )

    def _token_facts(
        self, asset: AssetRef, *, refresh: bool, block: int | None = None
    ) -> dict[str, Any]:
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
                self._call(asset.address, _SELECTOR_TOTAL_SUPPLY, block=block, refresh=refresh)
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
        head = self.head_block()
        for asset in dict.fromkeys(assets):
            facts = self._token_facts(asset, refresh=refresh, block=head)
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
        head = self.head_block()
        facts = self._token_facts(asset, refresh=refresh, block=head)
        scale = 10 ** facts["decimals"]

        collected: list[dict[str, Any]] = []
        self._logs(asset.address, 0, head, collected=collected, refresh=refresh)
        records = self._drop_implausible(self._decode_logs(collected, refresh=refresh), asset)

        schema = dict(polars_schema(TransferEvent))
        if not records:
            return validate(TransferEvent, pl.DataFrame(schema=schema), origin=self.name)

        decoded = self._to_frame(records, scale=scale)
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
        head = self.head_block()
        facts = self._token_facts(asset, refresh=refresh, block=head)
        scale = 10 ** facts["decimals"]

        collected: list[dict[str, Any]] = []
        self._logs(asset.address, 0, head, collected=collected, refresh=refresh)
        records = self._drop_implausible(self._decode_logs(collected, refresh=refresh), asset)

        ledger: dict[str, int] = defaultdict(int)
        for record in records:
            amount = int(record["raw_amount"])
            ledger[str(record["from_address"])] -= amount
            ledger[str(record["to_address"])] += amount
        for burn_address in BURN_ADDRESSES:
            ledger.pop(burn_address, None)

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

    def holder_snapshots(
        self,
        asset: AssetRef,
        instants: Sequence[datetime],
        *,
        refresh: bool = False,
    ) -> pl.DataFrame:
        """Return `HolderBalance` rows giving the distribution at each instant.

        Concentration and dormancy for a past window need the holders as they
        stood then. Using the present distribution is not an approximation but an
        error: balances that sum to more than the supply of an earlier window
        produce a share above 1, which the metrics correctly refuse, leaving the
        series full of holes.

        Replaying the ledger to each instant removes the problem rather than
        working around it. One walk serves every instant.

        Args:
            asset: The asset to reconstruct distributions for.
            instants: Moments to snapshot. Order does not matter.
            refresh: Bypass the cache and rescan.

        Returns:
            A validated `HolderBalance` frame, one row per address with a positive
            balance at each instant.
        """
        head = self.head_block()
        facts = self._token_facts(asset, refresh=refresh, block=head)
        scale = 10 ** facts["decimals"]

        collected: list[dict[str, Any]] = []
        self._logs(asset.address, 0, head, collected=collected, refresh=refresh)
        records = self._drop_implausible(self._decode_logs(collected, refresh=refresh), asset)

        wanted = sorted(set(instants))
        ledger: dict[str, int] = defaultdict(int)
        captured: dict[datetime, dict[str, int]] = {}
        position = 0

        def capture() -> dict[str, int]:
            return {
                address: value
                for address, value in ledger.items()
                if value > _DUST and address not in BURN_ADDRESSES
            }

        for record in records:
            moment = record["block_time"]
            while position < len(wanted) and wanted[position] < moment:
                captured[wanted[position]] = capture()
                position += 1
            amount = int(record["raw_amount"])
            ledger[str(record["from_address"])] -= amount
            ledger[str(record["to_address"])] += amount
        for remaining in wanted[position:]:
            captured[remaining] = capture()

        rows: list[dict[str, Any]] = []
        retrieved = datetime.now(UTC)
        for moment in wanted:
            for address, value in captured[moment].items():
                rows.append(
                    {
                        "asset_uid": asset.uid,
                        "source": self.name,
                        "retrieved_at": retrieved,
                        "as_of": moment,
                        "address": address,
                        "balance": value / scale,
                        "balance_usd": None,
                    }
                )

        schema = dict(polars_schema(HolderBalance))
        frame = pl.DataFrame(rows, schema=schema) if rows else pl.DataFrame(schema=schema)
        return validate(HolderBalance, frame, origin=self.name)

    def supply_snapshots(
        self,
        asset: AssetRef,
        instants: Sequence[datetime],
        *,
        refresh: bool = False,
    ) -> pl.DataFrame:
        """Return `AssetSnapshot` rows giving supply at each of `instants`.

        Supply is accumulated from the transfer ledger -- mints less burns, in
        block order -- so each figure is the supply as it actually stood at that
        moment rather than today's applied backwards. That distinction matters:
        BUIDL has minted roughly ten times its current supply over its life, so a
        turnover ratio for a window a year ago divided by today's supply would be
        wrong by that factor.

        The walk is the same one `fetch_holders` uses and shares its cache, and
        the last point is checked against `totalSupply()` on the way past.

        Args:
            asset: The asset to build a supply history for.
            instants: Moments to report supply at. Order does not matter.
            refresh: Bypass the cache and rescan.

        Returns:
            A validated `AssetSnapshot` frame, one row per instant, carrying only
            the fields a ledger can justify: supply, decimals, symbol and name.
        """
        head = self.head_block()
        facts = self._token_facts(asset, refresh=refresh, block=head)
        scale = 10 ** facts["decimals"]

        collected: list[dict[str, Any]] = []
        self._logs(asset.address, 0, head, collected=collected, refresh=refresh)
        records = self._drop_implausible(self._decode_logs(collected, refresh=refresh), asset)

        # One pass over the ledger, emitting the running supply as each requested
        # instant is passed. Records are already in block order.
        wanted = sorted(set(instants))
        supply = 0
        at_instant: dict[datetime, int] = {}
        position = 0
        for record in records:
            moment = record["block_time"]
            while position < len(wanted) and wanted[position] < moment:
                at_instant[wanted[position]] = supply
                position += 1
            amount = int(record["raw_amount"])
            if record["from_address"] in BURN_ADDRESSES:
                supply += amount
            elif record["to_address"] in BURN_ADDRESSES:
                supply -= amount
        for remaining in wanted[position:]:
            at_instant[remaining] = supply

        reported = facts.get("raw_total_supply")
        if reported is not None and supply != reported:
            logger.warning(
                "%s: the supply history for %s ends at %s but totalSupply() reports %s. "
                "Supply changes by some mechanism other than mint and burn events, so "
                "every historical supply figure for this token is unreliable.",
                self.name,
                asset.uid,
                f"{supply / scale:,.6f}",
                f"{reported / scale:,.6f}",
            )

        schema = dict(polars_schema(AssetSnapshot))
        frame = pl.DataFrame(
            {
                "asset_uid": [asset.uid] * len(wanted),
                "source": [self.name] * len(wanted),
                "retrieved_at": [datetime.now(UTC)] * len(wanted),
                "as_of": list(wanted),
                "symbol": [facts["symbol"]] * len(wanted),
                "name": [facts["name"]] * len(wanted),
                "decimals": [facts["decimals"]] * len(wanted),
                "total_supply": [at_instant[moment] / scale for moment in wanted],
                "market_value_usd": [None] * len(wanted),
                "price_usd": [None] * len(wanted),
                "holder_count": [None] * len(wanted),
            },
            schema=schema,
        )
        return validate(AssetSnapshot, frame, origin=self.name)

    def describe_issuance(self, asset: AssetRef, *, refresh: bool = False) -> IssuanceProfile:
        """Summarise how `asset` issues, from its complete transfer history.

        Uses the same cached scan as `fetch_holders`, so calling both costs one
        history walk rather than two.

        Args:
            asset: The asset to profile.
            refresh: Bypass the cache and rescan.

        Returns:
            The profile. `caveat()` on the result says what it implies for the
            asset's secondary figures.
        """
        head = self.head_block()
        facts = self._token_facts(asset, refresh=refresh, block=head)
        scale = 10 ** facts["decimals"]

        collected: list[dict[str, Any]] = []
        self._logs(asset.address, 0, head, collected=collected, refresh=refresh)
        records = self._drop_implausible(self._decode_logs(collected, refresh=refresh), asset)

        received: dict[str, int] = defaultdict(int)
        minted = 0
        mints = burns = 0
        first_mint: int | None = None
        for record in records:
            amount = int(record["raw_amount"])
            if record["from_address"] in BURN_ADDRESSES:
                mints += 1
                minted += amount
                received[str(record["to_address"])] += amount
                if first_mint is None:
                    first_mint = int(record["block"])
            elif record["to_address"] in BURN_ADDRESSES:
                burns += 1

        # With no visible issuance, fall back to who received the most supply
        # overall: on a token pre-minted in its constructor, that is whoever the
        # initial allocation went to.
        if not received:
            for record in records:
                received[str(record["to_address"])] += int(record["raw_amount"])

        largest = max(received.items(), key=lambda item: item[1], default=None)
        total = sum(received.values())
        return IssuanceProfile(
            asset_uid=asset.uid,
            transfers=len(records),
            mints=mints,
            burns=burns,
            minted_supply=minted / scale,
            first_mint_block=first_mint,
            largest_recipient=None if largest is None else largest[0],
            largest_recipient_share=(None if largest is None or total <= 0 else largest[1] / total),
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()
