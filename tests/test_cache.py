"""The parquet cache."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest

from rwa_liquidity.cache import SHARD_PREFIX_LENGTH, CacheKey, CorruptCacheEntryError, ParquetCache

from .conftest import NOW

KEY = CacheKey(source="defillama", dataset="protocol_tvl", params={"slug": "buidl"})


def test_round_trip_preserves_values_and_dtypes(cache_root: Path, snapshots: pl.DataFrame) -> None:
    cache = ParquetCache(cache_root)
    cache.put(KEY, snapshots, retrieved_at=NOW)

    entry = cache.get(KEY)
    assert entry is not None
    assert entry.retrieved_at == NOW
    # Timezone and time unit survive the parquet round trip. If they did not,
    # every observation window computed from a cached frame would be wrong.
    assert entry.frame.schema == snapshots.schema
    assert entry.frame.equals(snapshots)


def test_miss_returns_none(cache_root: Path) -> None:
    assert ParquetCache(cache_root).get(KEY) is None


def test_entry_within_ttl_is_returned(cache_root: Path, snapshots: pl.DataFrame) -> None:
    cache = ParquetCache(cache_root)
    cache.put(KEY, snapshots, retrieved_at=NOW)

    entry = cache.get(KEY, ttl=timedelta(hours=6), now=NOW + timedelta(hours=1))
    assert entry is not None


def test_entry_past_ttl_is_a_miss(cache_root: Path, snapshots: pl.DataFrame) -> None:
    cache = ParquetCache(cache_root)
    cache.put(KEY, snapshots, retrieved_at=NOW)

    assert cache.get(KEY, ttl=timedelta(hours=6), now=NOW + timedelta(hours=7)) is None


def test_no_ttl_means_an_entry_never_expires(cache_root: Path, snapshots: pl.DataFrame) -> None:
    # Reproducing a published figure means reading a year-old response back
    # exactly as it was, so an unbounded read has to be possible.
    cache = ParquetCache(cache_root)
    cache.put(KEY, snapshots, retrieved_at=NOW)

    assert cache.get(KEY, ttl=None, now=NOW + timedelta(days=365)) is not None


def test_parameter_order_does_not_change_the_key() -> None:
    a = CacheKey("dune", "transfers", {"asset": "buidl", "days": 30})
    b = CacheKey("dune", "transfers", {"days": 30, "asset": "buidl"})
    assert a.digest() == b.digest()


def test_different_parameters_are_different_entries(
    cache_root: Path, snapshots: pl.DataFrame
) -> None:
    cache = ParquetCache(cache_root)
    thirty = CacheKey("dune", "transfers", {"days": 30})
    ninety = CacheKey("dune", "transfers", {"days": 90})

    cache.put(thirty, snapshots, retrieved_at=NOW)

    assert cache.get(thirty) is not None
    assert cache.get(ninety) is None


def test_datasets_and_sources_are_separated_on_disk(cache_root: Path) -> None:
    path = ParquetCache(cache_root).path_for(KEY)
    assert path.parent.parent == cache_root / "defillama" / "protocol_tvl"
    assert path.parent.name == KEY.digest()[:SHARD_PREFIX_LENGTH]
    assert path.suffix == ".parquet"


def test_entries_are_sharded_by_digest_prefix(cache_root: Path, snapshots: pl.DataFrame) -> None:
    # A dataset with many entries must not collect them all into one flat
    # directory -- see SHARD_PREFIX_LENGTH's docstring for why.
    cache = ParquetCache(cache_root)
    cache.put(KEY, snapshots, retrieved_at=NOW)

    path = cache.path_for(KEY)
    assert path.name == f"{KEY.digest()}.parquet"
    assert len(path.parent.name) == SHARD_PREFIX_LENGTH
    assert path.is_file()


def test_put_overwrites_the_previous_entry(cache_root: Path, snapshots: pl.DataFrame) -> None:
    cache = ParquetCache(cache_root)
    cache.put(KEY, snapshots, retrieved_at=NOW)
    later = NOW + timedelta(days=1)
    cache.put(KEY, snapshots.with_columns(total_supply=pl.lit(2.0)), retrieved_at=later)

    entry = cache.get(KEY)
    assert entry is not None
    assert entry.retrieved_at == later
    assert entry.frame["total_supply"].item() == 2.0
    assert len(list(cache_root.rglob("*.parquet"))) == 1


def test_write_leaves_no_temporary_files_behind(cache_root: Path, snapshots: pl.DataFrame) -> None:
    # Entries are written to a temp file and renamed into place so that an
    # interrupted write cannot leave a truncated parquet where a valid one was.
    cache = ParquetCache(cache_root)
    cache.put(KEY, snapshots, retrieved_at=NOW)

    assert [p.name for p in cache_root.rglob("*") if p.is_file() and p.suffix != ".parquet"] == []


def test_losing_a_concurrent_write_race_is_not_an_error(
    cache_root: Path, snapshots: pl.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On Windows os.replace raises PermissionError while any other process holds
    # the destination open, which a concurrent reader or writer of the same entry
    # routinely does -- two `rwa-liquidity` commands scanning one asset is enough.
    # Losing that race is harmless: entries are addressed by a digest of the
    # request, so the winner wrote the answer to the same query. Simulated here
    # rather than by spawning a process, so the test means the same thing on
    # every platform (on POSIX the failure cannot be provoked at all).
    cache = ParquetCache(cache_root)
    cache.put(KEY, snapshots, retrieved_at=NOW)  # the "winner" puts a file in place

    def refuse(*_args: object, **_kwargs: object) -> Path:
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(Path, "replace", refuse)
    # Must not raise: the destination exists, so the entry this call wanted is
    # already there.
    cache.put(KEY, snapshots.with_columns(total_supply=pl.lit(2.0)), retrieved_at=NOW)

    monkeypatch.undo()
    entry = cache.get(KEY)
    assert entry is not None
    # The winner's copy survives untouched, and no temp file is left behind.
    assert entry.frame["total_supply"].item() == snapshots["total_supply"].item()
    assert [p.name for p in cache_root.rglob("*") if p.suffix != ".parquet" and p.is_file()] == []


def test_losing_a_write_race_returns_the_winners_entry_not_the_losers(
    cache_root: Path, snapshots: pl.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    # put()'s docstring promises the entry now on disk, not just an echo of
    # what the caller passed in. On a lost race those are different values --
    # this pins the return value itself, which the test above never checks
    # (it only reads back via a separate cache.get() call afterward).
    cache = ParquetCache(cache_root)
    winner = cache.put(KEY, snapshots, retrieved_at=NOW)

    def refuse(*_args: object, **_kwargs: object) -> Path:
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(Path, "replace", refuse)
    loser_frame = snapshots.with_columns(total_supply=pl.lit(2.0))
    returned = cache.put(KEY, loser_frame, retrieved_at=NOW)

    assert returned.frame["total_supply"].item() == winner.frame["total_supply"].item()
    assert returned.frame["total_supply"].item() != loser_frame["total_supply"].item()


def test_a_refused_rename_with_no_file_in_place_still_raises(
    cache_root: Path, snapshots: pl.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The complement of the test above, and the reason the retry cannot simply
    # swallow PermissionError: with nothing at the destination, the failure is a
    # read-only directory or a scanner holding the tree, not a lost race. Hiding
    # it would leave the cache silently never writing anything.
    cache = ParquetCache(cache_root)

    def refuse(*_args: object, **_kwargs: object) -> Path:
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(PermissionError):
        cache.put(KEY, snapshots, retrieved_at=NOW)


def test_naive_retrieval_timestamp_is_rejected(cache_root: Path, snapshots: pl.DataFrame) -> None:
    # An unlabelled timestamp would make every TTL comparison wrong by the local
    # UTC offset, with no visible symptom.
    with pytest.raises(ValueError, match="timezone-aware"):
        ParquetCache(cache_root).put(
            KEY,
            snapshots,
            retrieved_at=datetime(2026, 7, 1, 12, 0),  # noqa: DTZ001
        )


def test_corrupt_file_raises_rather_than_being_treated_as_a_miss(
    cache_root: Path,
) -> None:
    # Treating an unreadable file as a miss would silently overwrite it. If the
    # cache holds the only copy of a response backing a published number, that
    # is data loss disguised as a cache refresh.
    cache = ParquetCache(cache_root)
    path = cache.path_for(KEY)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a parquet file")

    with pytest.raises(CorruptCacheEntryError):
        cache.get(KEY)


def test_entry_from_an_incompatible_format_version_is_refused(
    cache_root: Path, snapshots: pl.DataFrame
) -> None:
    cache = ParquetCache(cache_root)
    path = cache.path_for(KEY)
    cache.put(KEY, snapshots, retrieved_at=NOW)

    table = pq.read_table(path)
    pq.write_table(
        table.replace_schema_metadata(
            {
                **{k.decode(): v.decode() for k, v in (table.schema.metadata or {}).items()},
                "rwa_liquidity.format_version": "0",
            }
        ),
        path,
    )

    with pytest.raises(CorruptCacheEntryError, match="format version"):
        cache.get(KEY)


def test_clear_removes_everything(cache_root: Path, snapshots: pl.DataFrame) -> None:
    cache = ParquetCache(cache_root)
    cache.put(KEY, snapshots, retrieved_at=NOW)
    cache.put(CacheKey("dune", "transfers", {}), snapshots, retrieved_at=NOW)

    assert cache.clear() == 2
    assert cache.get(KEY) is None


def test_clear_can_target_one_source(cache_root: Path, snapshots: pl.DataFrame) -> None:
    cache = ParquetCache(cache_root)
    dune = CacheKey("dune", "transfers", {})
    cache.put(KEY, snapshots, retrieved_at=NOW)
    cache.put(dune, snapshots, retrieved_at=NOW)

    assert cache.clear(source="dune") == 1
    assert cache.get(KEY) is not None
    assert cache.get(dune) is None


def test_clear_on_an_empty_cache_is_not_an_error(cache_root: Path) -> None:
    assert ParquetCache(cache_root).clear() == 0


def test_cache_directory_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RWA_LIQUIDITY_CACHE_DIR", str(tmp_path / "elsewhere"))
    assert ParquetCache().root == tmp_path / "elsewhere"


def test_cache_defaults_to_a_dotfile_in_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("RWA_LIQUIDITY_CACHE_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    assert ParquetCache().root == tmp_path / ".rwa-cache"


def test_age_is_measured_from_retrieval(cache_root: Path, snapshots: pl.DataFrame) -> None:
    cache = ParquetCache(cache_root)
    entry = cache.put(KEY, snapshots, retrieved_at=NOW)
    assert entry.age(now=NOW + timedelta(hours=3)) == timedelta(hours=3)


def test_retrieval_timestamp_is_stored_in_utc(cache_root: Path, snapshots: pl.DataFrame) -> None:
    # Written from a non-UTC zone, read back as the same instant.
    istanbul = NOW.astimezone(tz=None).replace(tzinfo=UTC) + timedelta(hours=3)
    cache = ParquetCache(cache_root)
    cache.put(KEY, snapshots, retrieved_at=istanbul)

    entry = cache.get(KEY)
    assert entry is not None
    assert entry.retrieved_at == istanbul
