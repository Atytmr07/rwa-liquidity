"""Dune Analytics adapter.

Implemented against the published API reference at docs.dune.com (read
2026-07-29), **not verified against a live API**: no key was available while
this was written. The network-marked tests skip themselves when no key is
present and are the thing to run first once one is.

Dune has no fixed schema. It runs whatever SQL a user saved, so this adapter
cannot know what columns will come back and instead states a **column contract**
that a saved query must satisfy. The required SQL is in `docs/data-sources.md`.
A query that does not satisfy the contract fails immediately with a message
naming the missing columns, rather than producing an empty frame that would read
downstream as "this asset did not trade".

Results are read from `GET /query/{id}/results`, which returns the last cached
execution and does **not** trigger a new one. Executing a query costs
substantially more credits, and a research workflow rarely needs the query rerun
on every call. Refreshing the underlying data is a deliberate act performed in
Dune, not a side effect of asking this package a question.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

import polars as pl

from rwa_liquidity.config import (
    DUNE_HOLDERS_QUERY_VAR,
    DUNE_KEY_VAR,
    DUNE_TRANSFERS_QUERY_VAR,
    api_key,
    optional_setting,
)
from rwa_liquidity.schema.frames import HolderBalance, TransferEvent
from rwa_liquidity.schema.validation import polars_schema, validate
from rwa_liquidity.sources.base import Capability, Source, SourceFetchError
from rwa_liquidity.sources.classify import classify_transfers
from rwa_liquidity.sources.http import CachedJSONClient

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence
    from datetime import timedelta

    import httpx

    from rwa_liquidity.cache.store import ParquetCache
    from rwa_liquidity.schema.asset import AssetRef

__all__ = [
    "DEFAULT_BASE_URL",
    "HOLDER_COLUMNS",
    "TRANSFER_COLUMNS",
    "DuneSource",
]

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL: Final = "https://api.dune.com/api/v1"

#: Columns a saved transfers query must produce. `amount_usd` is optional; when
#: absent, USD-denominated metrics report themselves undefined rather than
#: guessing a price.
TRANSFER_COLUMNS: Final = (
    "block_time",
    "tx_hash",
    "log_index",
    "contract_address",
    "from_address",
    "to_address",
    "amount",
)

#: Columns a saved holders query must produce. `balance_usd` is optional.
HOLDER_COLUMNS: Final = ("contract_address", "address", "balance")

_PAGE_SIZE: Final = 10_000
_MAX_PAGES: Final = 200
_COMPLETED: Final = "QUERY_STATE_COMPLETED"


def _to_utc(frame: pl.DataFrame, column: str, *, source: str) -> pl.DataFrame:
    """Return `frame` with `column` as timezone-aware UTC microseconds.

    Dune sends timestamps as JSON strings, in a format that has varied between
    plain ISO and a trailing ` UTC` suffix. Parsing is attempted by inference
    first and then with the suffix stripped, and a value that survives neither is
    an error rather than a null: a silently dropped block time would remove a
    transfer from its window instead of failing.
    """
    dtype = frame.schema[column]
    if dtype == pl.String:
        before = frame[column].null_count()
        # Formats are tried explicitly rather than inferred: polars raises when
        # inference fails for a whole column, and `strict=False` only nulls
        # individual values once a format is fixed. The `T`, `Z` and ` UTC`
        # decorations are stripped first, all three meaning UTC.
        cleaned = (
            pl.col(column)
            .str.strip_chars()
            .str.strip_suffix(" UTC")
            .str.replace("T", " ", literal=True)
            .str.strip_suffix("Z")
        )
        parsed = frame.with_columns(
            pl.coalesce(
                [
                    cleaned.str.to_datetime(format=fmt, time_unit="us", strict=False)
                    for fmt in ("%Y-%m-%d %H:%M:%S%.f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
                ]
            ).alias(column)
        )
        unparsed = parsed[column].null_count() - before
        if unparsed:
            sample = (
                frame.filter(parsed[column].is_null() & pl.col(column).is_not_null())[column]
                .head(3)
                .to_list()
            )
            raise SourceFetchError(
                f"{source}: {unparsed} value(s) in {column!r} could not be read as a "
                f"timestamp (e.g. {sample}). A dropped block time would silently remove "
                f"a transfer from its observation window. Timestamps carrying an explicit "
                f"UTC offset are not handled; adjust the saved query to emit plain UTC."
            )
        frame = parsed
        dtype = frame.schema[column]

    if not isinstance(dtype, pl.Datetime):
        raise SourceFetchError(f"{source}: {column!r} is {dtype}, not a timestamp")

    if dtype.time_zone is None:
        # Dune documents its timestamps as UTC, so an unlabelled one is relabelled
        # rather than converted. An already-aware column is converted instead;
        # relabelling that would shift the instant by its offset.
        return frame.with_columns(pl.col(column).dt.replace_time_zone("UTC"))
    return frame.with_columns(pl.col(column).dt.convert_time_zone("UTC"))


class DuneSource(Source):
    """Transfer-level and holder-level data from saved Dune queries."""

    name = "dune"
    capabilities = frozenset({Capability.TRANSFER_EVENT, Capability.HOLDER_BALANCE})

    def __init__(  # noqa: PLR0913 -- every option is an independent seam:
        # cache, transport, endpoint, two query ids, issuer map, ttl, credential.
        # All are keyword-only and all but the first two are rarely passed.
        self,
        *,
        cache: ParquetCache | None = None,
        client: httpx.Client | None = None,
        base_url: str = DEFAULT_BASE_URL,
        transfers_query_id: str | None = None,
        holders_query_id: str | None = None,
        issuer_addresses: Mapping[str, Collection[str]] | None = None,
        ttl: timedelta | None = None,
        key: str | None = None,
    ) -> None:
        """Create the adapter.

        Args:
            cache: Cache to read and write through.
            client: An httpx client; tests inject one with a mock transport. When
                supplied, no credential is read, so tests never need a key.
            base_url: Root of the Dune API.
            transfers_query_id: Saved query returning `TRANSFER_COLUMNS`.
                Defaults to `DUNE_TRANSFERS_QUERY_ID`.
            holders_query_id: Saved query returning `HOLDER_COLUMNS`. Defaults to
                `DUNE_HOLDERS_QUERY_ID`.
            issuer_addresses: Per-asset treasury addresses whose transfers are
                primary rather than secondary, keyed by asset uid. Getting this
                wrong is the single largest source of error in the package, so
                it is explicit rather than inferred.
            ttl: Freshness window for cached responses.
            key: API key. Defaults to the `DUNE_API_KEY` environment variable.

        Raises:
            MissingCredentialError: If no client is injected and no key is set.
        """
        self._base_url = base_url.rstrip("/")
        self._ttl = ttl
        self._transfers_query = transfers_query_id or optional_setting(DUNE_TRANSFERS_QUERY_VAR)
        self._holders_query = holders_query_id or optional_setting(DUNE_HOLDERS_QUERY_VAR)
        self._issuers = {uid.lower(): tuple(v) for uid, v in (issuer_addresses or {}).items()}
        headers = None
        if client is None:
            token = key if key is not None else api_key(DUNE_KEY_VAR, source=self.name)
            headers = {"X-Dune-Api-Key": token}
        self._http = CachedJSONClient(source=self.name, cache=cache, client=client, headers=headers)

    # -- fetching -----------------------------------------------------------

    def _rows(
        self, query_id: str, *, dataset: str, refresh: bool
    ) -> tuple[list[dict[str, Any]], datetime]:
        """Page through a saved query's cached results.

        Returns the rows and the moment the first page was retrieved. On a cache
        hit that is the original fetch time, not now, so `retrieved_at` means the
        same thing whether or not the response came off disk.
        """
        rows: list[dict[str, Any]] = []
        retrieved_at = datetime.now(UTC)
        offset = 0
        for _ in range(_MAX_PAGES):
            response = self._http.get_json(
                f"{self._base_url}/query/{query_id}/results",
                dataset=dataset,
                params={"limit": _PAGE_SIZE, "offset": offset},
                cache_params={"query_id": query_id, "limit": _PAGE_SIZE, "offset": offset},
                ttl=self._ttl,
                refresh=refresh,
            )
            if offset == 0:
                retrieved_at = response.retrieved_at
            payload = response.payload
            if not isinstance(payload, dict):
                raise SourceFetchError(f"{self.name}: query {query_id} did not return an object")

            state = payload.get("state")
            if state != _COMPLETED:
                error = payload.get("error")
                raise SourceFetchError(
                    f"{self.name}: query {query_id} is in state {state!r}, not {_COMPLETED}"
                    + (f": {error}" if error else "")
                )

            result = payload.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("rows"), list):
                raise SourceFetchError(
                    f"{self.name}: query {query_id} returned no 'result.rows' array"
                )
            rows.extend(row for row in result["rows"] if isinstance(row, dict))

            next_offset = payload.get("next_offset")
            if not isinstance(next_offset, int):
                break
            offset = next_offset
        else:
            logger.warning(
                "%s stopped paginating query %s after %d pages", self.name, query_id, _MAX_PAGES
            )
        return rows, retrieved_at

    def _require_query(self, query_id: str | None, *, variable: str, what: str) -> str:
        if not query_id:
            raise SourceFetchError(
                f"{self.name}: no saved query configured for {what}. Set {variable} to "
                f"the id of a Dune query returning the columns documented in "
                f"docs/data-sources.md."
            )
        return query_id

    def _check_columns(self, frame: pl.DataFrame, required: Sequence[str], what: str) -> None:
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise SourceFetchError(
                f"{self.name}: the saved {what} query is missing required column(s) "
                f"{', '.join(missing)}. It returned: {', '.join(frame.columns) or '(nothing)'}. "
                f"See docs/data-sources.md for the SQL this adapter expects."
            )

    # -- transfers ----------------------------------------------------------

    def fetch_transfers(
        self,
        asset: AssetRef,
        *,
        start: datetime,
        end: datetime,
        refresh: bool = False,
    ) -> pl.DataFrame:
        """Return classified transfers for `asset` over `[start, end)`.

        Rows are filtered to the asset and window here rather than in SQL, so one
        saved query can serve many assets and windows off a single cached
        execution.

        Args:
            asset: The asset to fetch transfers for.
            start: Inclusive start of the window.
            end: Exclusive end of the window.
            refresh: Bypass the cache and refetch.

        Returns:
            A validated `TransferEvent` frame, empty if the asset did not move.
        """
        query_id = self._require_query(
            self._transfers_query, variable=DUNE_TRANSFERS_QUERY_VAR, what="transfers"
        )
        rows, retrieved_at = self._rows(query_id, dataset="transfers", refresh=refresh)
        schema = dict(polars_schema(TransferEvent))

        if not rows:
            return validate(TransferEvent, pl.DataFrame(schema=schema), origin=self.name)

        raw = pl.DataFrame(rows, infer_schema_length=None)
        self._check_columns(raw, TRANSFER_COLUMNS, "transfers")

        scoped = _to_utc(raw, "block_time", source=self.name)
        scoped = scoped.with_columns(pl.col("contract_address").str.to_lowercase()).filter(
            (pl.col("contract_address") == asset.address.lower())
            & (pl.col("block_time") >= start)
            & (pl.col("block_time") < end)
        )

        classified = classify_transfers(
            scoped,
            issuer_addresses=self._issuers.get(asset.uid.lower(), ()),
            asset_uid=asset.uid,
        )

        frame = classified.with_columns(
            pl.lit(asset.uid).alias("asset_uid"),
            pl.lit(self.name).alias("source"),
            pl.lit(retrieved_at).alias("retrieved_at").cast(pl.Datetime("us", "UTC")),
            (
                pl.col("amount_usd")
                if "amount_usd" in classified.columns
                else pl.lit(None, dtype=pl.Float64).alias("amount_usd")
            ),
        ).select(list(schema))

        return validate(TransferEvent, frame, origin=self.name)

    # -- holders ------------------------------------------------------------

    def fetch_holders(
        self,
        asset: AssetRef,
        *,
        as_of: datetime | None = None,
        refresh: bool = False,
    ) -> pl.DataFrame:
        """Return holder balances for `asset`.

        Dune's saved query produces a snapshot as of its last execution. There is
        no way to ask it for a historical instant, so `as_of` labels the rows
        rather than selecting them; passing a value the query was not executed
        for would misdate the data.

        Args:
            asset: The asset to fetch balances for.
            as_of: The instant to label the snapshot with. Defaults to the
                moment the response was retrieved.
            refresh: Bypass the cache and refetch.

        Returns:
            A validated `HolderBalance` frame.
        """
        query_id = self._require_query(
            self._holders_query, variable=DUNE_HOLDERS_QUERY_VAR, what="holders"
        )
        rows, retrieved_at = self._rows(query_id, dataset="holders", refresh=refresh)
        schema = dict(polars_schema(HolderBalance))

        if not rows:
            return validate(HolderBalance, pl.DataFrame(schema=schema), origin=self.name)

        raw = pl.DataFrame(rows, infer_schema_length=None)
        self._check_columns(raw, HOLDER_COLUMNS, "holders")

        scoped = raw.with_columns(pl.col("contract_address").str.to_lowercase()).filter(
            pl.col("contract_address") == asset.address.lower()
        )

        stamp = as_of if as_of is not None else retrieved_at
        frame = scoped.with_columns(
            pl.lit(asset.uid).alias("asset_uid"),
            pl.lit(self.name).alias("source"),
            pl.lit(retrieved_at).alias("retrieved_at").cast(pl.Datetime("us", "UTC")),
            pl.lit(stamp).alias("as_of").cast(pl.Datetime("us", "UTC")),
            (
                pl.col("balance_usd")
                if "balance_usd" in scoped.columns
                else pl.lit(None, dtype=pl.Float64).alias("balance_usd")
            ),
        ).select(list(schema))

        return validate(HolderBalance, frame, origin=self.name)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()
