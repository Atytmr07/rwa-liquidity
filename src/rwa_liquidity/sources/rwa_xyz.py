"""rwa.xyz adapter.

Implemented against the published documentation at docs.rwa.xyz (read
2026-07-29), **not verified against a live API**: the endpoint is gated and no
key was available while this was written. Every assumption that could not be
checked is marked below and in `docs/data-sources.md`. The network-marked tests
skip themselves when no key is present and are the thing to run first once one
is.

Three details of the published schema matter:

* **There is no symbol field.** Tokens carry `name` but no ticker, so `symbol`
  is left null rather than derived from the name.
* **There is no observation timestamp.** The response says what a token is worth
  but not when that was true. `as_of` therefore falls back to the moment we
  asked, which is an upper bound on the figure's age and is recorded as a
  caveat on every row this adapter produces.
* **Metrics are nested objects**, not scalars: `market_value_dollar` is
  `{"val": ..., "val_7d": ..., "chg_7d_pct": ...}`. Only `val` is taken.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Final

import polars as pl

from rwa_liquidity.config import RWA_XYZ_KEY_VAR, api_key
from rwa_liquidity.schema.asset import AssetRef, InvalidAssetRefError
from rwa_liquidity.schema.frames import AssetSnapshot
from rwa_liquidity.schema.validation import polars_schema, validate
from rwa_liquidity.sources.base import Capability, Source, SourceFetchError
from rwa_liquidity.sources.http import CachedJSONClient

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import timedelta

    import httpx

    from rwa_liquidity.cache.store import ParquetCache

__all__ = ["DEFAULT_BASE_URL", "RwaXyzSource"]

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL: Final = "https://api.rwa.xyz/v4"

#: The documentation says perPage "typically caps at 100".
_PAGE_SIZE: Final = 100

#: A guard against paginating forever if the API reports a pageCount it does not
#: honour. The RWA universe is in the low thousands of tokens, so this is far
#: above any legitimate result set.
_MAX_PAGES: Final = 100


def _scalar(record: Mapping[str, Any], field: str) -> float | None:
    """Read `val` out of one of the nested metric objects."""
    value = record.get(field)
    if isinstance(value, dict):
        value = value.get("val")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


class RwaXyzSource(Source):
    """Asset-level metadata and value figures from rwa.xyz."""

    name = "rwa_xyz"
    capabilities = frozenset({Capability.ASSET_SNAPSHOT})

    def __init__(  # noqa: PLR0913 -- keyword-only seams for cache, transport,
        # endpoint, chain aliases, ttl and credential; none are positional.
        self,
        *,
        cache: ParquetCache | None = None,
        client: httpx.Client | None = None,
        base_url: str = DEFAULT_BASE_URL,
        chain_aliases: Mapping[str, str] | None = None,
        ttl: timedelta | None = None,
        key: str | None = None,
    ) -> None:
        """Create the adapter.

        Args:
            cache: Cache to read and write through.
            client: An httpx client; tests inject one with a mock transport. When
                supplied, no credential is read, so tests never need a key.
            base_url: Root of the API.
            chain_aliases: Overrides mapping rwa.xyz `network_name` values to
                canonical chain names. See `_canonical_chain`.
            ttl: Freshness window for cached responses.
            key: API key. Defaults to the `RWA_XYZ_API_KEY` environment variable.

        Raises:
            MissingCredentialError: If no client is injected and no key is set.
        """
        self._base_url = base_url.rstrip("/")
        self._ttl = ttl
        self._aliases = {k.lower(): v for k, v in (chain_aliases or {}).items()}
        headers = None
        if client is None:
            token = key if key is not None else api_key(RWA_XYZ_KEY_VAR, source=self.name)
            headers = {"Authorization": f"Bearer {token}"}
        self._http = CachedJSONClient(source=self.name, cache=cache, client=client, headers=headers)

    def _canonical_chain(self, network_name: str) -> str:
        """Map an rwa.xyz network name onto this package's chain naming.

        The documentation does not state the value format, so the rule is the
        conservative one: lowercase and hyphenate, which turns `Ethereum` into
        `ethereum` and `BNB Chain` into `bnb-chain`. Anything this gets wrong is
        correctable through `chain_aliases` without touching code, and a wrong
        chain produces an asset key that simply fails to match rather than one
        that silently measures the wrong contract.
        """
        cleaned = network_name.strip()
        return self._aliases.get(cleaned.lower(), "-".join(cleaned.lower().split()))

    def fetch_asset_snapshots(
        self,
        assets: Sequence[AssetRef],
        *,
        refresh: bool = False,
    ) -> pl.DataFrame:
        """Return snapshots for `assets`.

        The full token list is paginated and indexed client-side rather than
        filtered server-side. The documented filter syntax could not be verified
        against a live endpoint, and a filter that silently matches nothing is
        indistinguishable from an asset that does not exist. Paginating is more
        requests but the result is checkable, and the responses are cached.

        Args:
            assets: Assets to look up. An empty sequence returns every token
                rwa.xyz publishes.
            refresh: Bypass the cache and refetch.

        Returns:
            A validated `AssetSnapshot` frame.
        """
        wanted = {asset.uid for asset in assets}
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()

        for page in range(1, _MAX_PAGES + 1):
            payload, retrieved_at = self._page(page, refresh=refresh)
            results = payload.get("results")
            if not isinstance(results, list):
                raise SourceFetchError(
                    f"{self.name}: page {page} has no 'results' array; the endpoint "
                    f"shape has changed"
                )

            for record in results:
                row = self._row(record, retrieved_at=retrieved_at)
                if row is None:
                    continue
                uid = str(row["asset_uid"])
                if wanted and uid not in wanted:
                    continue
                if uid in seen:
                    # Two tokens on one contract would break the schema's
                    # uniqueness rule; keep the first and say so.
                    logger.warning(
                        "%s returned %s more than once; keeping the first", self.name, uid
                    )
                    continue
                seen.add(uid)
                rows.append(row)

            if page >= self._page_count(payload):
                break
        else:
            logger.warning(
                "%s stopped after %d pages; the result set is larger than expected",
                self.name,
                _MAX_PAGES,
            )

        missing = sorted(wanted - seen)
        if missing:
            logger.warning(
                "%s published no token for %d of %d requested assets: %s",
                self.name,
                len(missing),
                len(wanted),
                ", ".join(missing),
            )

        frame = (
            pl.DataFrame(rows, schema=dict(polars_schema(AssetSnapshot)))
            if rows
            else (pl.DataFrame(schema=dict(polars_schema(AssetSnapshot))))
        )
        return validate(AssetSnapshot, frame, origin=self.name)

    def _page(self, page: int, *, refresh: bool) -> tuple[Mapping[str, Any], Any]:
        query = json.dumps(
            {"pagination": {"page": page, "perPage": _PAGE_SIZE}},
            separators=(",", ":"),
        )
        response = self._http.get_json(
            f"{self._base_url}/tokens",
            dataset="tokens",
            params={"query": query},
            cache_params={"page": page, "per_page": _PAGE_SIZE},
            ttl=self._ttl,
            refresh=refresh,
        )
        if not isinstance(response.payload, dict):
            raise SourceFetchError(f"{self.name}: /tokens did not return an object")
        return response.payload, response.retrieved_at

    @staticmethod
    def _page_count(payload: Mapping[str, Any]) -> int:
        pagination = payload.get("pagination")
        if isinstance(pagination, dict):
            count = pagination.get("pageCount")
            if isinstance(count, int):
                return count
        # Without a page count there is no way to know whether more exist, so
        # stop rather than loop against an unknown endpoint.
        return 0

    def _row(self, record: Any, *, retrieved_at: Any) -> dict[str, Any] | None:
        """Turn one token record into a snapshot row, or skip it."""
        if not isinstance(record, dict):
            return None
        address = record.get("address")
        network = record.get("network_name")
        if not isinstance(address, str) or not isinstance(network, str):
            # Off-chain or unlisted entries have no contract to key on. They are
            # real records upstream, just not ones this package can measure.
            return None
        try:
            ref = AssetRef(chain=self._canonical_chain(network), address=address)
        except InvalidAssetRefError:
            logger.warning(
                "%s returned an unusable address %r on network %r; skipping",
                self.name,
                address,
                network,
            )
            return None

        decimals = record.get("decimals")
        holders = _scalar(record, "holding_addresses_count")
        return {
            "asset_uid": ref.uid,
            "source": self.name,
            "retrieved_at": retrieved_at,
            # rwa.xyz publishes no observation timestamp. The retrieval time is
            # an upper bound on the figure's age, not the age itself; see the
            # module docstring and docs/data-sources.md.
            "as_of": retrieved_at,
            "symbol": None,
            "name": record.get("name"),
            "decimals": int(decimals) if isinstance(decimals, int) else None,
            "total_supply": _scalar(record, "total_supply_token"),
            "market_value_usd": _scalar(record, "market_value_dollar"),
            "price_usd": None,
            "holder_count": int(holders) if holders is not None else None,
        }

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()
