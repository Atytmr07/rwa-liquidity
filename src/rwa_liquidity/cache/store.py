"""Parquet-backed response cache.

A development loop must never bill a paid API twice for the same query, and a
result published in a paper must be reproducible after the upstream figures have
moved on. Both needs are served by writing every response to disk alongside the
moment it was retrieved.

The retrieval timestamp and the query that produced it are stored in the parquet
file's own key-value metadata rather than in a sidecar JSON file. That keeps
each entry a single self-describing artifact: it cannot be separated from its
provenance by a stray copy, and `parquet-tools` or `pyarrow` can read the whole
story out of it without this package present.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Final
from uuid import uuid4

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["CacheEntry", "CacheKey", "CorruptCacheEntryError", "ParquetCache"]

#: Bumped when the on-disk layout changes in a way older entries cannot satisfy.
#: Entries written by a different version are treated as a miss rather than
#: being read with the wrong assumptions.
CACHE_FORMAT_VERSION: Final = "1"

_METADATA_PREFIX: Final = "rwa_liquidity."
_DEFAULT_CACHE_DIRNAME: Final = ".rwa-cache"
_CACHE_DIR_ENV_VAR: Final = "RWA_LIQUIDITY_CACHE_DIR"

# 16 hex characters is 64 bits. Collisions are not a practical concern for the
# number of distinct queries a research workflow issues, and short names keep
# the cache directory readable when inspecting it by hand.
_DIGEST_LENGTH: Final = 16

ParamValue = str | int | float | bool | None


#: How many times to retry a rename that Windows refuses because another
#: process holds the destination open. The locks in question are held for the
#: length of a file read, so a handful of short retries clears them; a longer
#: schedule would only delay reporting a genuine permission problem.
_REPLACE_ATTEMPTS: Final = 5
_REPLACE_BACKOFF_SECONDS: Final = 0.05


class CorruptCacheEntryError(Exception):
    """A cache file exists but cannot be read as an entry this package wrote."""


#: Windows error codes that mean "another handle has this file open" rather
#: than a real permission problem. 5 is access-denied, the one Python maps to
#: `PermissionError` on its own; 32 is a sharing violation, which does not
#: always arrive as `PermissionError` -- some antivirus/indexer interference
#: surfaces it as a plain `OSError` instead. Both are worth retrying; nothing
#: else is.
_WINDOWS_SHARING_ERRORS: Final = frozenset({5, 32})


def _replace_atomically(temporary: Path, path: Path) -> bool:
    """Rename `temporary` onto `path`, tolerating a lost race on Windows.

    POSIX lets a rename replace a file that another process has open, so two
    writers of the same key simply produce "last one wins" and both results are
    complete. Windows does not: `os.replace` raises `PermissionError`
    (`WinError 5`) while any other handle to the destination is open, which a
    concurrent reader or writer of the same entry will routinely hold. Two
    `rwa-liquidity` commands scanning the same asset at once is enough to hit
    it, and it surfaced as a mid-scan crash rather than as anything cache-shaped.

    Losing this race is harmless and must not be an error. Entries are addressed
    by a digest of the request, so whoever won wrote the response to the *same*
    query; the point of the write is that the entry exists, not that this
    process is the one that created it.

    A short retry loop clears the common case, where the holder is a reader that
    finishes in milliseconds -- contention here is held for the length of one
    file read, not a growing amount of work, so the backoff is flat rather than
    increasing. If the destination exists after that, the write is treated as
    satisfied by whoever won. Only a failure with no file in place is re-raised
    -- that is a read-only directory or a scanner holding the whole tree, which
    is a real problem and not a race.

    Returns:
        `True` if this call's own write is what is now on disk at `path`,
        `False` if it lost the race and accepted someone else's write instead.
        A caller that reports what got persisted needs to know which one it
        was for; it is never itself `path`'s content.
    """
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            temporary.replace(path)
        except OSError as error:
            transient = isinstance(error, PermissionError) or (
                getattr(error, "winerror", None) in _WINDOWS_SHARING_ERRORS
            )
            if not transient:
                raise
            if attempt < _REPLACE_ATTEMPTS - 1:
                time.sleep(_REPLACE_BACKOFF_SECONDS)
                continue
            if not path.exists():
                raise
            # Someone else wrote this key while we were working. Their copy
            # answers the same request, so ours is redundant.
            temporary.unlink(missing_ok=True)
            return False
        return True
    return True  # pragma: no cover -- unreachable, _REPLACE_ATTEMPTS is >= 1


@dataclass(frozen=True, slots=True)
class CacheKey:
    """Identifies one provider query.

    Attributes:
        source: Adapter name, e.g. `defillama`.
        dataset: What was asked for, e.g. `protocol_tvl`.
        params: The query parameters. Order is irrelevant; two keys with the
            same parameters in a different order address the same entry.
    """

    source: str
    dataset: str
    params: Mapping[str, ParamValue] = field(default_factory=dict)

    def canonical_params(self) -> str:
        """Return the parameters as order-independent, stable JSON."""
        # sort_keys makes the digest independent of insertion order;
        # separators removes whitespace so formatting cannot change the hash.
        return json.dumps(dict(self.params), sort_keys=True, separators=(",", ":"), default=str)

    def digest(self) -> str:
        """Return the short hash that names this entry's file on disk."""
        payload = f"{self.source}|{self.dataset}|{self.canonical_params()}"
        return hashlib.sha256(payload.encode()).hexdigest()[:_DIGEST_LENGTH]

    def __str__(self) -> str:
        """Return a readable identifier for log and error messages."""
        return f"{self.source}/{self.dataset}({self.canonical_params()})"


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """A cached response and the circumstances under which it was obtained."""

    key: CacheKey
    frame: pl.DataFrame
    retrieved_at: datetime
    path: Path

    def age(self, *, now: datetime | None = None) -> timedelta:
        """Return how long ago this entry was retrieved."""
        return (now or datetime.now(UTC)) - self.retrieved_at

    def is_expired(self, ttl: timedelta | None, *, now: datetime | None = None) -> bool:
        """Return whether this entry is older than `ttl`. `None` never expires."""
        if ttl is None:
            return False
        return self.age(now=now) > ttl


class ParquetCache:
    """A directory of parquet files, one per provider query.

    Entries are laid out as `<root>/<source>/<dataset>/<digest>.parquet`, so the
    cache can be inspected, partially deleted, or committed as a fixture without
    this package being involved.
    """

    def __init__(self, root: Path | None = None) -> None:
        """Create a cache rooted at `root`.

        Args:
            root: Directory to store entries in. Defaults to the
                `RWA_LIQUIDITY_CACHE_DIR` environment variable, or `.rwa-cache`
                in the current working directory.
        """
        if root is None:
            configured = os.environ.get(_CACHE_DIR_ENV_VAR)
            root = Path(configured) if configured else Path.cwd() / _DEFAULT_CACHE_DIRNAME
        self.root = root

    def path_for(self, key: CacheKey) -> Path:
        """Return the file this key maps to, whether or not it exists."""
        return self.root / key.source / key.dataset / f"{key.digest()}.parquet"

    def get(
        self,
        key: CacheKey,
        *,
        ttl: timedelta | None = None,
        now: datetime | None = None,
    ) -> CacheEntry | None:
        """Read an entry, or return `None` on a miss.

        A miss and an expiry are reported the same way, because a caller that
        has to refetch does not care which happened.

        Args:
            key: The query to look up.
            ttl: Maximum acceptable age. `None` accepts any age.
            now: Reference time, for tests.

        Returns:
            The entry, or `None` if it is absent or older than `ttl`.

        Raises:
            CorruptCacheEntryError: If the file exists but is unreadable or was
                not written by this cache. This is deliberately not treated as a
                miss: silently overwriting a file we do not understand is how a
                cache quietly loses data it was trusted with.
        """
        path = self.path_for(key)
        if not path.is_file():
            return None

        entry = self._read(key, path)
        if entry.is_expired(ttl, now=now):
            return None
        return entry

    def put(
        self,
        key: CacheKey,
        frame: pl.DataFrame,
        *,
        retrieved_at: datetime | None = None,
    ) -> CacheEntry:
        """Write an entry, replacing any existing one for the same key.

        Args:
            key: The query this response answers.
            frame: The response, already normalized.
            retrieved_at: When the provider was asked. Defaults to now.

        Returns:
            The entry now on disk at this key. Ordinarily that is `frame`
            unchanged, but if a concurrent writer won the rename race (see
            `_replace_atomically`), it is whatever *they* wrote instead --
            answering the same query, but not necessarily byte-for-byte what
            this call was given. A caller that inspects the return value sees
            what is actually cached, not just what it asked to store.

        Raises:
            ValueError: If `retrieved_at` is timezone-naive. An unlabelled
                timestamp would make TTL comparisons wrong by the local UTC
                offset without any visible symptom.
        """
        moment = retrieved_at or datetime.now(UTC)
        if moment.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")

        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        table = frame.to_arrow().replace_schema_metadata(
            {
                f"{_METADATA_PREFIX}format_version": CACHE_FORMAT_VERSION,
                f"{_METADATA_PREFIX}source": key.source,
                f"{_METADATA_PREFIX}dataset": key.dataset,
                f"{_METADATA_PREFIX}params": key.canonical_params(),
                f"{_METADATA_PREFIX}retrieved_at": moment.astimezone(UTC).isoformat(),
            }
        )

        # Write to a temporary file in the destination directory and rename it
        # into place. A rename within one directory is atomic, so an interrupted
        # write leaves the previous entry intact rather than a truncated file
        # that would fail to parse on the next run. The uuid suffix keeps two
        # concurrent writers of the same key from clobbering each other's
        # temporary file.
        temporary = path.with_name(f".{path.stem}-{uuid4().hex}.tmp")
        try:
            pq.write_table(table, temporary, compression="zstd")
            wrote = _replace_atomically(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

        if wrote:
            return CacheEntry(key=key, frame=frame, retrieved_at=moment, path=path)
        # Lost the race: `path` holds someone else's write, not this call's
        # `frame`. Read back what is actually there rather than claiming the
        # data this call never persisted.
        return self._read(key, path)

    def clear(self, *, source: str | None = None) -> int:
        """Delete cached entries and return how many files were removed.

        Args:
            source: Limit deletion to one adapter. `None` clears everything.
        """
        target = self.root if source is None else self.root / source
        if not target.is_dir():
            return 0
        removed = 0
        for path in target.rglob("*.parquet"):
            path.unlink()
            removed += 1
        return removed

    def _read(self, key: CacheKey, path: Path) -> CacheEntry:
        """Read one entry, verifying it was written by a compatible version."""
        try:
            table = pq.read_table(path)
        except (pa.ArrowInvalid, OSError) as error:
            raise CorruptCacheEntryError(
                f"cache entry for {key} at {path} could not be read: {error}"
            ) from error

        raw = table.schema.metadata or {}
        metadata = {k.decode(): v.decode() for k, v in raw.items()}

        version = metadata.get(f"{_METADATA_PREFIX}format_version")
        if version != CACHE_FORMAT_VERSION:
            raise CorruptCacheEntryError(
                f"cache entry at {path} has format version {version!r}, expected "
                f"{CACHE_FORMAT_VERSION!r}. Delete the cache directory to rebuild it."
            )

        stamp = metadata.get(f"{_METADATA_PREFIX}retrieved_at")
        if stamp is None:
            raise CorruptCacheEntryError(
                f"cache entry at {path} is missing its retrieval timestamp"
            )
        try:
            retrieved_at = datetime.fromisoformat(stamp)
        except ValueError as error:
            raise CorruptCacheEntryError(
                f"cache entry at {path} has an unparseable retrieval timestamp {stamp!r}"
            ) from error

        frame = pl.from_arrow(table)
        if not isinstance(frame, pl.DataFrame):  # pragma: no cover
            # An arrow Table always converts to a DataFrame; this narrows the
            # `DataFrame | Series` return type rather than casting blindly.
            raise CorruptCacheEntryError(f"cache entry at {path} is not a table")

        return CacheEntry(key=key, frame=frame, retrieved_at=retrieved_at, path=path)
