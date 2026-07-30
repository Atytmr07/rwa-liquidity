"""Assembling live measurements from several sources.

This is the layer that turns a list of assets into the three normalized frames,
by asking each source for what it can answer and concatenating the results. The
metrics layer then works on those frames exactly as it does on the sample data,
which is the point: nothing downstream can tell whether a number came from a
node, a paid API, or a CSV.

Ordering is deliberate. `EvmRpcSource` is asked first because its figures are
derived from chain state and verifiable, and the API-backed sources fill in only
what a node cannot know -- prices, and a provider's own view of market value.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import polars as pl

from rwa_liquidity.schema.frames import AssetSnapshot, HolderBalance, TransferEvent
from rwa_liquidity.schema.validation import polars_schema
from rwa_liquidity.sources.base import Capability, SourceError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rwa_liquidity.metrics.base import Window
    from rwa_liquidity.schema.asset import AssetRef
    from rwa_liquidity.sources.base import Source

__all__ = ["IngestionResult", "collect"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """The three frames, plus a record of what went wrong along the way.

    Attributes:
        snapshots: Concatenated `AssetSnapshot` rows from every source.
        transfers: Concatenated `TransferEvent` rows.
        holders: Concatenated `HolderBalance` rows.
        failures: One entry per source that raised, as `(source, message)`. A
            failure is recorded rather than propagated: one provider being down
            should not discard the data the others returned, but it must not be
            invisible either.
    """

    snapshots: pl.DataFrame
    transfers: pl.DataFrame
    holders: pl.DataFrame
    failures: tuple[tuple[str, str], ...] = field(default=())

    @property
    def sources_used(self) -> tuple[str, ...]:
        """Return every source label that contributed a row."""
        labels: set[str] = set()
        for frame in (self.snapshots, self.transfers, self.holders):
            if not frame.is_empty():
                labels.update(str(value) for value in frame["source"].unique().to_list())
        return tuple(sorted(labels))


def _empty(model: type[AssetSnapshot] | type[TransferEvent] | type[HolderBalance]) -> pl.DataFrame:
    return pl.DataFrame(schema=dict(polars_schema(model)))


def _concat(frames: Sequence[pl.DataFrame], model: type) -> pl.DataFrame:
    populated = [frame for frame in frames if not frame.is_empty()]
    if not populated:
        return _empty(model)
    return pl.concat(populated, how="vertical")


def collect(
    sources: Sequence[Source],
    assets: Sequence[AssetRef],
    *,
    window: Window,
    refresh: bool = False,
) -> IngestionResult:
    """Ask every source for everything it can answer about `assets`.

    Args:
        sources: Adapters to query, in priority order.
        assets: Assets to measure.
        window: The observation period, used to bound transfer queries.
        refresh: Bypass the cache on every fetch.

    Returns:
        The concatenated frames and any per-source failures.
    """
    snapshots: list[pl.DataFrame] = []
    transfers: list[pl.DataFrame] = []
    holders: list[pl.DataFrame] = []
    failures: list[tuple[str, str]] = []

    for source in sources:
        if source.supports(Capability.ASSET_SNAPSHOT):
            try:
                snapshots.append(source.fetch_asset_snapshots(assets, refresh=refresh))
            except SourceError as error:
                failures.append((source.name, f"asset snapshots: {error}"))
                logger.warning("%s could not supply asset snapshots: %s", source.name, error)

        # Transfers and holders are per-asset, so one asset failing must not
        # discard the others -- a single unusual token is exactly the case where
        # partial results are still worth having.
        for asset in assets:
            if source.supports(Capability.TRANSFER_EVENT):
                try:
                    transfers.append(
                        source.fetch_transfers(
                            asset, start=window.start, end=window.end, refresh=refresh
                        )
                    )
                except SourceError as error:
                    failures.append((source.name, f"transfers for {asset.uid}: {error}"))
                    logger.warning(
                        "%s could not supply transfers for %s: %s", source.name, asset.uid, error
                    )
            if source.supports(Capability.HOLDER_BALANCE):
                try:
                    holders.append(source.fetch_holders(asset, as_of=window.end, refresh=refresh))
                except SourceError as error:
                    failures.append((source.name, f"holders for {asset.uid}: {error}"))
                    logger.warning(
                        "%s could not supply holders for %s: %s", source.name, asset.uid, error
                    )

    return IngestionResult(
        snapshots=_concat(snapshots, AssetSnapshot),
        transfers=_concat(transfers, TransferEvent),
        holders=_concat(holders, HolderBalance),
        failures=tuple(failures),
    )
