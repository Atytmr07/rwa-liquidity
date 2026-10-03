"""DeFiLlama adapters.

DeFiLlama publishes two things this package can use, and they are *not* the same
measurement, so they are exposed as two sources rather than merged into one row:

`DeFiLlamaPricesSource`
    Reads `coins.llama.fi/prices/current`, which is keyed by `chain:address` --
    the same canonical key this package uses -- and returns price, symbol, and
    decimals for one specific token contract. Precise and unambiguous.

`DeFiLlamaProtocolTvlSource`
    Reads `api.llama.fi/protocol/{slug}`, which reports the value of a *protocol*
    on a chain. A protocol frequently covers more than one token: BlackRock's
    covers both BUIDL and BUIDL-I, and Ondo's umbrella covers several products.
    Its figure is therefore an upper bound on any single contract, not a
    measurement of it.

Merging the two into a single row would silently attribute a protocol-wide value
to one contract. Keeping them apart means the reconcile layer compares them like
any other pair of disagreeing sources, and the disagreement stays visible.

Neither source can see transfers or holders, so neither declares those
capabilities. That is what makes it safe for a metric to read an empty transfer
frame as "this asset did not trade".
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import polars as pl

from rwa_liquidity.schema.frames import AssetSnapshot
from rwa_liquidity.schema.validation import polars_schema, validate
from rwa_liquidity.sources.base import Capability, Source, SourceFetchError
from rwa_liquidity.sources.http import CachedJSONClient
from rwa_liquidity.sources.registry import RegistryEntry, load_defillama_registry

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence
    from datetime import timedelta

    import httpx

    from rwa_liquidity.cache.store import ParquetCache
    from rwa_liquidity.schema.asset import AssetRef

__all__ = [
    "COINS_BASE_URL",
    "DEFAULT_API_BASE_URL",
    "DeFiLlamaPricesSource",
    "DeFiLlamaProtocolTvlSource",
]

logger = logging.getLogger(__name__)

COINS_BASE_URL: Final = "https://coins.llama.fi"
DEFAULT_API_BASE_URL: Final = "https://api.llama.fi"

# The price endpoint takes its keys in the URL path. Long paths are rejected by
# intermediaries at sizes that vary, so requests are chunked well below any of
# them; each chunk is cached independently, which also means adding one asset to
# a query does not invalidate the others.
_MAX_KEYS_PER_REQUEST: Final = 50


def _chunks(items: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _api_base_url() -> str:
    """Return the api.llama.fi base URL, overridable for testing against a mock."""
    return os.environ.get("DEFILLAMA_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")


def _snapshot_frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    """Build an `AssetSnapshot`-shaped frame, empty or not, with fixed dtypes.

    Deriving the dtypes from the schema means an empty result has exactly the
    same columns and types as a populated one, so a caller that concatenates
    several sources cannot be broken by one of them happening to return nothing.
    """
    schema = dict(polars_schema(AssetSnapshot))
    if not rows:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(rows, schema=schema)


class DeFiLlamaPricesSource(Source):
    """Asset-level price, symbol, and decimals from `coins.llama.fi`.

    This source reports no supply, market value, or holder count: DeFiLlama's
    price endpoint does not publish them, and inventing them would defeat the
    purpose of validating at the boundary.
    """

    name = "defillama_prices"
    capabilities = frozenset({Capability.ASSET_SNAPSHOT})

    def __init__(
        self,
        *,
        cache: ParquetCache | None = None,
        client: httpx.Client | None = None,
        base_url: str = COINS_BASE_URL,
        ttl: timedelta | None = None,
    ) -> None:
        """Create the adapter.

        Args:
            cache: Cache to read and write through.
            client: An httpx client; tests inject one with a mock transport.
            base_url: Root of the coins API.
            ttl: Freshness window for cached responses. Omit for the client
                default.
        """
        self._base_url = base_url.rstrip("/")
        self._ttl = ttl
        self._http = CachedJSONClient(source=self.name, cache=cache, client=client)

    def fetch_asset_snapshots(
        self,
        assets: Sequence[AssetRef],
        *,
        refresh: bool = False,
    ) -> pl.DataFrame:
        """Return current price data for `assets`.

        Assets DeFiLlama does not know about are absent from the result and
        logged at warning level. The endpoint returns HTTP 200 with an empty
        object for an unknown key rather than an error, so a silent omission is
        the default failure mode and has to be detected deliberately.

        Args:
            assets: Assets to look up.
            refresh: Bypass the cache and refetch.

        Returns:
            A validated `AssetSnapshot` frame with one row per asset found.
        """
        if not assets:
            return _snapshot_frame([])

        # Deduplicate while preserving order; AssetRef is hashable and already
        # normalized, so two spellings of one asset collapse here rather than
        # producing two rows that violate the schema's uniqueness constraint.
        uids = list(dict.fromkeys(asset.uid for asset in assets))

        rows: list[dict[str, Any]] = []
        found: set[str] = set()
        for chunk in _chunks(uids, _MAX_KEYS_PER_REQUEST):
            joined = ",".join(chunk)
            response = self._http.get_json(
                f"{self._base_url}/prices/current/{joined}",
                dataset="prices_current",
                # Key on the sorted asset list rather than the URL, so the same
                # set of assets requested in a different order is one entry.
                cache_params={"assets": ",".join(sorted(chunk))},
                ttl=self._ttl,
                refresh=refresh,
            )
            coins = self._coins(response.payload)
            for uid, record in coins.items():
                found.add(uid)
                rows.append(self._row(uid, record, retrieved_at=response.retrieved_at))

        missing = [uid for uid in uids if uid not in found]
        if missing:
            logger.warning(
                "%s returned no price for %d of %d assets: %s",
                self.name,
                len(missing),
                len(uids),
                ", ".join(missing),
            )

        return validate(AssetSnapshot, _snapshot_frame(rows), origin=self.name)

    def _coins(self, payload: Any) -> Mapping[str, Any]:
        if not isinstance(payload, dict) or "coins" not in payload:
            got = sorted(payload) if isinstance(payload, dict) else type(payload).__name__
            raise SourceFetchError(
                f"{self.name}: response has no 'coins' object; the endpoint shape "
                f"has changed. Got: {got}"
            )
        coins = payload["coins"]
        if not isinstance(coins, dict):
            raise SourceFetchError(f"{self.name}: 'coins' is not an object")
        return coins

    def _row(self, uid: str, record: Any, *, retrieved_at: datetime) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise SourceFetchError(f"{self.name}: entry for {uid!r} is not an object")

        timestamp = record.get("timestamp")
        if not isinstance(timestamp, int | float):
            raise SourceFetchError(f"{self.name}: entry for {uid!r} has no usable timestamp")

        return {
            "asset_uid": uid,
            "source": self.name,
            "retrieved_at": retrieved_at,
            # DeFiLlama's timestamp is the moment the price was observed, which
            # is not the moment we asked. Both are kept.
            "as_of": datetime.fromtimestamp(float(timestamp), tz=UTC),
            # Symbol casing is inconsistent upstream (`BUIDL` but `xaut`). It is
            # passed through unchanged: normalizing it would hide a property of
            # the source, and nothing joins on it.
            "symbol": record.get("symbol"),
            "name": None,
            "decimals": record.get("decimals"),
            "total_supply": None,
            "market_value_usd": None,
            "price_usd": record.get("price"),
            "holder_count": None,
        }

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()


class DeFiLlamaProtocolTvlSource(Source):
    """Protocol-level value from `api.llama.fi`, per chain.

    The chain-specific figure is used rather than the multi-chain total. For
    BUIDL those differ by roughly a factor of three, and using the total would
    overstate the Ethereum contract's value by that much.

    Read the `notes` on each registry entry before treating a figure here as a
    measurement of one contract. Several protocols cover more than one token.
    """

    name = "defillama_protocol_tvl"
    capabilities = frozenset({Capability.ASSET_SNAPSHOT})

    def __init__(
        self,
        *,
        cache: ParquetCache | None = None,
        client: httpx.Client | None = None,
        base_url: str | None = None,
        registry: Sequence[RegistryEntry] | None = None,
        ttl: timedelta | None = None,
    ) -> None:
        """Create the adapter.

        Args:
            cache: Cache to read and write through.
            client: An httpx client; tests inject one with a mock transport.
            base_url: Root of the protocol API. Defaults to the
                `DEFILLAMA_BASE_URL` environment variable, then to the public
                endpoint.
            registry: Asset-to-slug mapping. Defaults to the one shipped with
                the package.
            ttl: Freshness window for cached responses.
        """
        self._base_url = (base_url or _api_base_url()).rstrip("/")
        self._ttl = ttl
        self._registry = (
            tuple(registry) if registry is not None else tuple(load_defillama_registry())
        )
        self._by_uid = {entry.ref.uid: entry for entry in self._registry}
        self._http = CachedJSONClient(source=self.name, cache=cache, client=client)

    @property
    def registry(self) -> Sequence[RegistryEntry]:
        """Return the asset-to-slug mapping in use."""
        return self._registry

    def fetch_asset_snapshots(
        self,
        assets: Sequence[AssetRef],
        *,
        refresh: bool = False,
    ) -> pl.DataFrame:
        """Return the latest chain-specific protocol value for `assets`.

        Args:
            assets: Assets to look up. Any not present in the registry are
                skipped and logged; there is no way to derive their slug.
            refresh: Bypass the cache and refetch.

        Returns:
            A validated `AssetSnapshot` frame with one row per asset resolved.
        """
        rows: list[dict[str, Any]] = []
        for asset in dict.fromkeys(assets):
            entry = self._by_uid.get(asset.uid)
            if entry is None:
                logger.warning(
                    "%s has no registry entry for %s; DeFiLlama's own address field is "
                    "not reliable enough to derive one, so the asset is skipped",
                    self.name,
                    asset.uid,
                )
                continue
            row = self._fetch_one(entry, refresh=refresh)
            if row is not None:
                rows.append(row)

        return validate(AssetSnapshot, _snapshot_frame(rows), origin=self.name)

    def _fetch_one(self, entry: RegistryEntry, *, refresh: bool) -> dict[str, Any] | None:
        response = self._http.get_json(
            f"{self._base_url}/protocol/{entry.defillama_slug}",
            dataset="protocol",
            cache_params={"slug": entry.defillama_slug},
            ttl=self._ttl,
            refresh=refresh,
        )
        payload = response.payload
        if not isinstance(payload, dict):
            raise SourceFetchError(
                f"{self.name}: protocol/{entry.defillama_slug} did not return an object"
            )

        series = self._chain_series(payload, entry)
        if not series:
            logger.warning(
                "%s: protocol %r reports no value series for chain %r; skipping %s",
                self.name,
                entry.defillama_slug,
                entry.defillama_chain,
                entry.ref.uid,
            )
            return None

        latest = series[-1]
        value = latest.get("totalLiquidityUSD")
        date = latest.get("date")
        if not isinstance(value, int | float) or not isinstance(date, int | float):
            logger.warning(
                "%s: latest point for %r is malformed (%r); skipping %s",
                self.name,
                entry.defillama_slug,
                latest,
                entry.ref.uid,
            )
            return None

        return {
            "asset_uid": entry.ref.uid,
            "source": self.name,
            "retrieved_at": response.retrieved_at,
            "as_of": datetime.fromtimestamp(float(date), tz=UTC),
            "symbol": entry.symbol,
            "name": entry.name,
            "decimals": None,
            "total_supply": None,
            "market_value_usd": float(value),
            "price_usd": None,
            "holder_count": None,
        }

    def _chain_series(self, payload: Mapping[str, Any], entry: RegistryEntry) -> list[Any]:
        chain_tvls = payload.get("chainTvls")
        if not isinstance(chain_tvls, dict):
            raise SourceFetchError(
                f"{self.name}: protocol/{entry.defillama_slug} has no 'chainTvls' object"
            )
        chain = chain_tvls.get(entry.defillama_chain)
        if not isinstance(chain, dict):
            return []
        series = chain.get("tvl")
        if not isinstance(series, list):
            return []
        return [point for point in series if isinstance(point, dict)]

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()
