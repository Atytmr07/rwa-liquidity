"""Assembling frames from several sources, and what counts as measured."""

# The fake source implements the `Source` interface, whose parameters it must
# accept but has no use for.
# ruff: noqa: ARG002

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar

import polars as pl

from rwa_liquidity.metrics.base import Window
from rwa_liquidity.pipeline import collect
from rwa_liquidity.schema.asset import AssetRef
from rwa_liquidity.schema.frames import HolderBalance, TransferEvent
from rwa_liquidity.schema.validation import polars_schema
from rwa_liquidity.sources.base import Capability, Source, SourceFetchError

from .conftest import BUIDL, NOW, asset_snapshot_frame, holder_balance_frame, transfer_event_frame

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

ASSET = AssetRef.parse(BUIDL)
WINDOW = Window(start=NOW - timedelta(days=30), end=NOW)


class Fake(Source):
    """A source whose answers and failures are set per test."""

    name: ClassVar[str] = "fake"
    capabilities: ClassVar[frozenset[Capability]] = frozenset(
        {Capability.ASSET_SNAPSHOT, Capability.TRANSFER_EVENT, Capability.HOLDER_BALANCE}
    )

    def __init__(
        self,
        *,
        transfers: pl.DataFrame | None = None,
        holders: pl.DataFrame | None = None,
        reconciled: Mapping[str, bool | None] | None = None,
        dropped: Mapping[str, int] | None = None,
    ) -> None:
        # None means "raise"; an empty frame means "answered, nothing there".
        self._transfers = transfers
        self._holders = holders
        self._reconciled = dict(reconciled or {})
        self._dropped = dict(dropped or {})

    def fetch_asset_snapshots(
        self, assets: Sequence[AssetRef], *, refresh: bool = False
    ) -> pl.DataFrame:
        return asset_snapshot_frame()

    def fetch_transfers(
        self, asset: AssetRef, *, start: datetime, end: datetime, refresh: bool = False
    ) -> pl.DataFrame:
        if self._transfers is None:
            raise SourceFetchError("fake: transfers refused")
        return self._transfers

    def fetch_holders(
        self, asset: AssetRef, *, as_of: datetime | None = None, refresh: bool = False
    ) -> pl.DataFrame:
        if self._holders is None:
            raise SourceFetchError("fake: holders refused")
        return self._holders

    def reconciliation_status(self) -> Mapping[str, bool | None]:
        return self._reconciled

    def dropped_transfer_counts(self) -> Mapping[str, int]:
        return self._dropped

    def close(self) -> None:
        return None


def empty(model: type) -> pl.DataFrame:
    return pl.DataFrame(schema=dict(polars_schema(model)))


def test_an_asset_that_answered_with_no_transfers_is_measured() -> None:
    # A successful fetch that returns nothing means the asset did not move in
    # the window. That is a measurement, not missing data.
    result = collect(
        [Fake(transfers=empty(TransferEvent), holders=holder_balance_frame())],
        [ASSET],
        window=WINDOW,
    )
    assert result.missing == {}
    assert result.unmeasured == frozenset()


def test_holders_without_transfers_leave_the_asset_unmeasured_and_say_why() -> None:
    result = collect([Fake(transfers=None, holders=holder_balance_frame())], [ASSET], window=WINDOW)
    assert result.missing == {ASSET.uid: ("transfers",)}
    assert result.unmeasured == frozenset({ASSET.uid})


def test_transfers_without_holders_leave_the_asset_unmeasured_and_say_why() -> None:
    result = collect([Fake(transfers=transfer_event_frame(), holders=None)], [ASSET], window=WINDOW)
    assert result.missing == {ASSET.uid: ("holders",)}


def test_a_kind_one_source_failed_on_is_not_missing_if_another_supplied_it() -> None:
    result = collect(
        [
            Fake(transfers=None, holders=holder_balance_frame()),
            Fake(transfers=transfer_event_frame(), holders=None),
        ],
        [ASSET],
        window=WINDOW,
    )
    assert result.missing == {}


def test_a_kind_no_source_can_supply_is_never_counted_as_missing() -> None:
    class TransfersOnly(Fake):
        capabilities: ClassVar[frozenset[Capability]] = frozenset({Capability.TRANSFER_EVENT})

    result = collect([TransfersOnly(transfers=transfer_event_frame())], [ASSET], window=WINDOW)
    assert result.missing == {}


def test_reconciliation_and_dropped_counts_are_carried_into_the_result() -> None:
    result = collect(
        [
            Fake(
                transfers=transfer_event_frame(),
                holders=holder_balance_frame(),
                reconciled={ASSET.uid: False},
                dropped={ASSET.uid: 3},
            )
        ],
        [ASSET],
        window=WINDOW,
    )
    assert result.reconciliation == {ASSET.uid: False}
    assert result.dropped_transfers == {ASSET.uid: 3}


def test_the_holder_frame_keeps_its_schema_when_every_fetch_failed() -> None:
    result = collect([Fake()], [ASSET], window=WINDOW)
    assert result.holders.schema == pl.Schema(polars_schema(HolderBalance))
