"""Cached JSON transport shared by every adapter.

The cache stores the provider's **raw response text**, not the normalized frame
built from it. That costs a JSON parse on every cache hit and buys two things
worth far more:

* A change to the normalized schema does not invalidate the cache. Re-deriving
  frames from responses already on disk means a bug in an adapter can be fixed
  without spending another paid API call, which is the whole point of caching a
  metered service.
* The bytes behind a published number are still on disk months later, so a
  result can be audited rather than merely re-run.

Responses are held as a single-row frame carrying the response text, the final
URL, and the status code, which keeps everything in the one parquet cache rather
than introducing a second storage format.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

import httpx
import polars as pl

from rwa_liquidity.cache.store import CacheKey, ParquetCache
from rwa_liquidity.sources.base import SourceFetchError, SourceTransportError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_liquidity.cache.store import ParamValue

__all__ = ["CachedJSONClient", "JSONResponse"]

_DEFAULT_TIMEOUT: Final = 30.0

# httpx retries only connection failures, not HTTP status codes. That is the
# right split here: a 500 from a data provider usually means the query is wrong
# rather than the network is flaky, and silently retrying it wastes quota.
_DEFAULT_CONNECT_RETRIES: Final = 2

_USER_AGENT: Final = "rwa-liquidity (+https://github.com/atytmr07/rwa-liquidity)"

_RESPONSE_COLUMN: Final = "response_text"
_URL_COLUMN: Final = "url"
_STATUS_COLUMN: Final = "status_code"

# Longest error body worth quoting back. Providers sometimes return an HTML
# error page, and pasting all of it into an exception helps nobody.
_ERROR_EXCERPT: Final = 200

# Status codes at or above this are the server's fault and worth retrying.
_SERVER_ERROR: Final = 500

#: Rate limiting. Retryable, but it is the server asking for a pause rather than
#: a transient fault, so it gets a longer one.
_TOO_MANY_REQUESTS: Final = 429

#: Seconds between retry attempts, multiplied by the attempt number.
_RETRY_PAUSE: Final = 1.0

#: Base pause after a rate-limit response. Longer, because retrying quickly is
#: what caused it.
_THROTTLE_PAUSE: Final = 3.0


class _Unset:
    """Sentinel type.

    `None` is a meaningful value for `ttl` -- it means "accept an entry of any
    age" -- so a distinct sentinel is needed to express "the caller did not say".
    A class rather than a bare `object()` so that mypy can narrow on it.
    """

    __slots__ = ()


_UNSET: Final = _Unset()


class JSONResponse:
    """A decoded provider response together with when it was obtained.

    Attributes:
        payload: The decoded JSON.
        retrieved_at: When the provider was actually asked. On a cache hit this
            is the original fetch time, not the time of the hit, which is what
            makes `as_of` on a cached frame mean the same thing as on a fresh
            one.
        from_cache: Whether this came off disk.
    """

    __slots__ = ("from_cache", "payload", "retrieved_at")

    def __init__(self, payload: Any, retrieved_at: datetime, *, from_cache: bool) -> None:
        """Store the decoded payload and its retrieval context."""
        self.payload = payload
        self.retrieved_at = retrieved_at
        self.from_cache = from_cache


class CachedJSONClient:
    """An HTTP client that reads through the parquet cache."""

    def __init__(
        self,
        *,
        source: str,
        cache: ParquetCache | None = None,
        client: httpx.Client | None = None,
        headers: Mapping[str, str] | None = None,
        default_ttl: timedelta | None = timedelta(hours=12),
    ) -> None:
        """Create a client for one adapter.

        Args:
            source: Adapter name, used to namespace cache entries.
            cache: Cache to read and write. Defaults to the standard location.
            client: An httpx client, injected by tests to supply a mock
                transport. Defaults to one configured with a timeout, a retrying
                connection transport, and an identifying user agent.
            headers: Extra headers, typically authentication. Applied only to a
                client this instance creates; an injected client is left alone
                so a test's transport is never handed a real credential.
            default_ttl: How long an entry stays fresh when the caller does not
                say. Twelve hours suits the daily-ish cadence at which these
                providers actually update.
        """
        self.source = source
        self.cache = cache if cache is not None else ParquetCache()
        self.default_ttl = default_ttl
        self._owns_client = client is None
        self._client = client if client is not None else self._build_client(headers)

    @staticmethod
    def _build_client(headers: Mapping[str, str] | None = None) -> httpx.Client:
        return httpx.Client(
            timeout=_DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/json",
                **(dict(headers) if headers else {}),
            },
            transport=httpx.HTTPTransport(retries=_DEFAULT_CONNECT_RETRIES),
        )

    def get_json(  # noqa: PLR0913 -- every one of these is a distinct axis of
        # the request: where to go, how to key the cache, how stale is
        # acceptable, and whether to skip the read. Bundling them into a config
        # object would make every call site longer, not shorter.
        self,
        url: str,
        *,
        dataset: str,
        params: Mapping[str, ParamValue] | None = None,
        cache_params: Mapping[str, ParamValue] | None = None,
        ttl: timedelta | _Unset | None = _UNSET,
        refresh: bool = False,
    ) -> JSONResponse:
        """GET `url` and decode the response as JSON, reading through the cache.

        Args:
            url: Absolute URL to fetch.
            dataset: Cache namespace within this source, e.g. `prices`.
            params: Query string parameters.
            cache_params: What to key the cache entry on. Defaults to the URL and
                `params`. Supply this when the URL itself carries the query --
                DeFiLlama puts a comma-joined asset list in the path -- so that
                the key stays readable and independent of argument order.
            ttl: Maximum acceptable age. Omit for the client default; pass `None`
                explicitly to accept an entry of any age.
            refresh: Skip the read, fetch, and overwrite.

        Returns:
            The decoded response.

        Raises:
            SourceFetchError: On a network failure, a non-success status, or a
                body that is not valid JSON.
        """
        key = self._key(url, dataset=dataset, params=params, cache_params=cache_params)
        effective_ttl: timedelta | None = self.default_ttl if isinstance(ttl, _Unset) else ttl

        if not refresh:
            entry = self.cache.get(key, ttl=effective_ttl)
            if entry is not None:
                text = entry.frame[_RESPONSE_COLUMN].item()
                return JSONResponse(
                    payload=self._decode(str(text), url),
                    retrieved_at=entry.retrieved_at,
                    from_cache=True,
                )

        retrieved_at = datetime.now(UTC)
        try:
            response = self._client.get(url, params=dict(params) if params else None)
        except httpx.HTTPError as error:
            raise SourceTransportError(
                f"{self.source}: request to {url} failed: {error}"
            ) from error

        if response.is_error:
            raise SourceFetchError(
                f"{self.source}: {url} returned HTTP {response.status_code}: "
                f"{response.text[:_ERROR_EXCERPT]}"
            )

        payload = self._decode(response.text, url)
        self.cache.put(
            key,
            pl.DataFrame(
                {
                    _URL_COLUMN: [str(response.url)],
                    _STATUS_COLUMN: [response.status_code],
                    _RESPONSE_COLUMN: [response.text],
                }
            ),
            retrieved_at=retrieved_at,
        )
        return JSONResponse(payload=payload, retrieved_at=retrieved_at, from_cache=False)

    def post_json(  # noqa: PLR0913 -- same distinct axes as get_json, plus the
        # retry budget, which only the RPC caller needs.
        self,
        url: str,
        *,
        dataset: str,
        body: Mapping[str, Any],
        cache_params: Mapping[str, ParamValue],
        ttl: timedelta | _Unset | None = _UNSET,
        refresh: bool = False,
        retries: int = 0,
    ) -> JSONResponse:
        """POST `body` as JSON, reading through the cache.

        JSON-RPC needs POST, so the cache key cannot be derived from the URL --
        every request goes to the same endpoint. `cache_params` is therefore
        required rather than optional: the caller must say what makes this
        request distinct.

        Args:
            url: Absolute URL to post to.
            dataset: Cache namespace within this source.
            body: The JSON-RPC envelope.
            cache_params: What identifies this request.
            ttl: Maximum acceptable age. Omit for the client default.
            refresh: Skip the read, fetch, and overwrite.
            retries: Extra attempts on a 5xx or a timeout. Public RPC endpoints
                return transient gateway errors under load, which is worth
                retrying; a 4xx means the request is wrong and is not retried.

        Returns:
            The decoded response.

        Raises:
            SourceFetchError: On a network failure, a non-success status that
                survived the retries, or a body that is not valid JSON.
        """
        key = CacheKey(source=self.source, dataset=dataset, params=dict(cache_params))
        effective_ttl: timedelta | None = self.default_ttl if isinstance(ttl, _Unset) else ttl

        if not refresh:
            entry = self.cache.get(key, ttl=effective_ttl)
            if entry is not None:
                return JSONResponse(
                    payload=self._decode(str(entry.frame[_RESPONSE_COLUMN].item()), url),
                    retrieved_at=entry.retrieved_at,
                    from_cache=True,
                )

        retrieved_at = datetime.now(UTC)
        last_error = ""
        # Whether the endpoint ever rendered a verdict on this request. A
        # connection that never landed, a 429, and a 5xx all leave the request
        # unjudged, which callers that reformulate a rejected request need to
        # tell apart from an actual rejection.
        unreachable = True
        for attempt in range(retries + 1):
            pause = _RETRY_PAUSE
            try:
                response = self._client.post(url, json=dict(body))
            except httpx.HTTPError as error:
                last_error = f"request failed: {error}"
            else:
                if not response.is_error:
                    payload = self._decode(response.text, url)
                    self.cache.put(
                        key,
                        pl.DataFrame(
                            {
                                _URL_COLUMN: [str(response.url)],
                                _STATUS_COLUMN: [response.status_code],
                                _RESPONSE_COLUMN: [response.text],
                            }
                        ),
                        retrieved_at=retrieved_at,
                    )
                    return JSONResponse(
                        payload=payload, retrieved_at=retrieved_at, from_cache=False
                    )
                last_error = f"HTTP {response.status_code}: {response.text[:_ERROR_EXCERPT]}"
                if response.status_code == _TOO_MANY_REQUESTS:
                    # The server is asking for a pause rather than reporting a
                    # fault, so it gets a longer one than a transient 5xx.
                    pause = _THROTTLE_PAUSE
                elif response.status_code < _SERVER_ERROR:
                    # Any other 4xx means the request itself is wrong. Retrying
                    # it wastes another call and cannot succeed. This is the one
                    # branch where the endpoint has actually judged the request.
                    unreachable = False
                    break
            if attempt < retries:
                # Linear rather than exponential: these endpoints recover in
                # about a second, and a long backoff would stall a scan that
                # issues thousands of requests.
                time.sleep(pause * (attempt + 1))

        error_type = SourceTransportError if unreachable else SourceFetchError
        raise error_type(f"{self.source}: {url} {last_error}")

    def _key(
        self,
        url: str,
        *,
        dataset: str,
        params: Mapping[str, ParamValue] | None,
        cache_params: Mapping[str, ParamValue] | None,
    ) -> CacheKey:
        if cache_params is not None:
            resolved: dict[str, ParamValue] = dict(cache_params)
        else:
            resolved = {"url": url, **dict(params or {})}
        return CacheKey(source=self.source, dataset=dataset, params=resolved)

    def _decode(self, text: str, url: str) -> Any:
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise SourceFetchError(
                f"{self.source}: {url} returned a body that is not JSON: {text[:_ERROR_EXCERPT]}"
            ) from error

    def close(self) -> None:
        """Close the underlying client, if this instance created it."""
        if self._owns_client:
            self._client.close()
