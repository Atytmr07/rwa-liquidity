"""Shared machinery for every metric: windows, provenance, and input handling.

Two conventions hold across the whole metrics layer.

**A metric returns `None`, never a placeholder.** When a denominator is zero or
absent, the metric is undefined, and saying so is different from saying zero. A
turnover ratio of `0.0` means an asset with supply that did not trade; `None`
means we could not tell. Collapsing the two would put a fabricated number in a
table.

**A metric returns its provenance.** Value alone is not a result. Which sources
it came from, over what window, how many records were behind it, what was
excluded, and what was doubtful all travel with the number, because the number
may end up in a paper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, timedelta
from typing import TYPE_CHECKING, Final

import polars as pl

from rwa_liquidity.schema.types import BURN_ADDRESSES, Denomination, VolumeMode

if TYPE_CHECKING:
    from collections.abc import Collection
    from datetime import datetime

__all__ = [
    "COVERAGE_FLOOR",
    "DEFAULT_WINDOW_DAYS",
    "MetricInputError",
    "MetricResult",
    "Provenance",
    "Window",
    "active_addresses",
    "filter_by_mode",
    "latest_snapshot",
    "prepare_holders",
    "resolve_total_supply",
    "single_asset",
    "sources_of",
]

#: The observation period used when a caller does not specify one.
DEFAULT_WINDOW_DAYS: Final = 30

#: Below this fraction of the reported holder count, a holder distribution is
#: too incomplete for a concentration figure to be quoted without a caveat.
COVERAGE_FLOOR: Final = 0.99

#: How far after a window's end a snapshot may still be used to describe the
#: state at that end. A live source reads the chain as it is now, and a
#: full-history scan takes minutes, so the reading always post-dates the window
#: it was requested for. An hour against a 30-day window is immaterial; a day is
#: not, and is refused.
SNAPSHOT_GRACE: Final = timedelta(hours=1)


class MetricInputError(Exception):
    """A metric was given frames it cannot compute over."""


@dataclass(frozen=True, slots=True)
class Window:
    """A half-open observation period, `[start, end)`.

    Half-open so that consecutive windows tile without double-counting a
    transfer that lands exactly on a boundary.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        """Reject windows that cannot define an observation period."""
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise MetricInputError("window bounds must be timezone-aware")
        if self.end <= self.start:
            raise MetricInputError(f"window end {self.end} is not after start {self.start}")

    @classmethod
    def ending(cls, end: datetime, *, days: int = DEFAULT_WINDOW_DAYS) -> Window:
        """Return the `days`-long window ending at `end`."""
        return cls(start=end - timedelta(days=days), end=end)

    @property
    def days(self) -> float:
        """Return the window length in days."""
        return (self.end - self.start).total_seconds() / 86_400

    def clip(self, frame: pl.DataFrame, *, column: str) -> pl.DataFrame:
        """Return the rows of `frame` whose `column` falls inside the window."""
        return frame.filter(
            (pl.col(column) >= self.start.astimezone(UTC))
            & (pl.col(column) < self.end.astimezone(UTC))
        )

    def __str__(self) -> str:
        """Render the window compactly for provenance display."""
        return f"[{self.start.isoformat()}, {self.end.isoformat()})"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Everything needed to defend a metric value.

    Attributes:
        metric: The function that produced the value.
        asset_uid: The asset measured.
        sources: Every `source` label that contributed, sorted.
        window: The observation period.
        mode: The volume mode applied, where the metric has one.
        denomination: The unit, where the metric has one.
        n_records: How many underlying rows survived filtering.
        exclusions: What was deliberately left out, and why.
        warnings: What is doubtful about the value. A non-empty list does not
            mean the value is wrong, but it does mean it should not be quoted
            without the caveat.
    """

    metric: str
    asset_uid: str
    sources: tuple[str, ...]
    window: Window
    n_records: int
    mode: VolumeMode | None = None
    denomination: Denomination | None = None
    exclusions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def with_warning(self, message: str) -> Provenance:
        """Return a copy carrying one more warning."""
        return Provenance(
            metric=self.metric,
            asset_uid=self.asset_uid,
            sources=self.sources,
            window=self.window,
            n_records=self.n_records,
            mode=self.mode,
            denomination=self.denomination,
            exclusions=self.exclusions,
            warnings=(*self.warnings, message),
        )


@dataclass(frozen=True, slots=True)
class MetricResult:
    """A metric value together with the record of how it was obtained.

    Attributes:
        value: The metric, or `None` where it is undefined.
        provenance: How the value was arrived at.
    """

    value: float | None
    provenance: Provenance = field(compare=False)

    @property
    def is_defined(self) -> bool:
        """Return whether the metric could be computed at all."""
        return self.value is not None


def single_asset(frame: pl.DataFrame, *, what: str) -> str:
    """Return the one asset uid in `frame`, or raise.

    Metrics are defined for one asset. Silently aggregating across several
    would produce a plausible-looking number that describes nothing.

    Args:
        frame: A normalized frame.
        what: Name of the frame, for the error message.

    Returns:
        The single asset uid present.

    Raises:
        MetricInputError: If the frame is empty or covers more than one asset.
    """
    if frame.is_empty():
        raise MetricInputError(f"{what} frame is empty, so there is no asset to measure")
    uids = frame["asset_uid"].unique().to_list()
    if len(uids) != 1:
        raise MetricInputError(
            f"{what} frame covers {len(uids)} assets ({', '.join(sorted(uids))}); "
            f"metrics are defined for one asset at a time"
        )
    return str(uids[0])


def filter_by_mode(transfers: pl.DataFrame, mode: VolumeMode) -> pl.DataFrame:
    """Return the transfers counted under `mode`.

    See `VolumeMode.kinds`. Unclassified transfers are counted only under `ALL`.
    """
    return transfers.filter(pl.col("kind").is_in([kind.value for kind in mode.kinds]))


def active_addresses(transfers: pl.DataFrame) -> set[str]:
    """Return the addresses that participated in `transfers`.

    An address counts as active whether it sent or received: a holder who took
    delivery participated in the market, and counting senders only would treat
    every buyer as dormant.

    Burn addresses are excluded. The zero address is a bookkeeping artifact of
    issuance and redemption, not a market participant, and leaving it in would
    add one phantom active address to every asset that has ever minted.
    """
    if transfers.is_empty():
        return set()
    parties = pl.concat(
        [
            transfers.select(pl.col("from_address").alias("address")),
            transfers.select(pl.col("to_address").alias("address")),
        ]
    )
    return {
        str(address)
        for address in parties["address"].unique().to_list()
        if str(address).lower() not in BURN_ADDRESSES
    }


def latest_snapshot(snapshots: pl.DataFrame, window: Window) -> dict[str, object]:
    """Return the state of the asset at the end of `window`.

    Metrics are defined against the state at the end of the observation period,
    so a snapshot taken after the window closed would describe a different world
    than the transfers being measured.

    Where several sources describe the asset, each field takes the most recent
    non-null value rather than every field coming from one winning row. Sources
    publish different subsets -- DeFiLlama has no holder counts, an on-chain
    source has no stated market value -- so picking a single row would discard
    fields that another source did report, and which row won would depend on an
    unstable sort. Ties are broken by source name so the result is deterministic.

    This is *not* the package deciding which source is right. Where two sources
    report the same field differently, `rwa_liquidity.reconcile` reports the
    disagreement; this function only ensures a metric has something to divide by.

    Args:
        snapshots: An `AssetSnapshot` frame for one asset.
        window: The observation period.

    Returns:
        The merged state as a mapping.

    Raises:
        MetricInputError: If no snapshot falls at or before the window's end.
    """
    # The cutoff carries a grace period rather than landing exactly on the
    # window's end. A live source reads the chain as it is now, and a
    # full-history scan takes minutes, so a reading requested for the window end
    # necessarily arrives after it. Applying the grace only when *nothing* else
    # qualifies is not enough: one source whose timestamp happens to fall inside
    # the window would then win outright and the fields only a slightly-late
    # source reported would vanish, which is how a supply figure that was
    # fetched correctly still shows up as missing.
    cutoff = window.end.astimezone(UTC) + SNAPSHOT_GRACE
    eligible = snapshots.filter(pl.col("as_of") <= cutoff)
    if eligible.is_empty():
        raise MetricInputError(
            f"no snapshot within {SNAPSHOT_GRACE} of {window.end.isoformat()}; the "
            f"earliest available is {snapshots['as_of'].min()!r}"
        )

    ordered = eligible.sort(["as_of", "source"]).to_dicts()
    merged: dict[str, object] = dict(ordered[-1])
    for row in reversed(ordered[:-1]):
        for key, value in row.items():
            if merged.get(key) is None and value is not None:
                merged[key] = value
    return merged


def sources_of(*frames: pl.DataFrame) -> tuple[str, ...]:
    """Return every distinct `source` label across `frames`, sorted."""
    labels: set[str] = set()
    for frame in frames:
        if not frame.is_empty():
            labels.update(str(value) for value in frame["source"].unique().to_list())
    return tuple(sorted(labels))


def prepare_holders(
    holders: pl.DataFrame,
    exclude: Collection[str],
) -> tuple[pl.DataFrame, list[str]]:
    """Drop burn and caller-excluded addresses, returning the frame and notes.

    Issuer treasury, bridge, and custody addresses are **not** excluded by
    default. Excluding them would bury an editorial judgement inside a published
    number; including them is wrong in a way the reader can see and correct with
    `exclude`, which is then recorded in the provenance.

    Address matching is case-insensitive: a source may report EIP-55 checksummed
    addresses where another reports lowercase, and a case mismatch would silently
    exclude nothing.
    """
    excluded = {address.lower() for address in exclude}
    notes: list[str] = []
    lowered = pl.col("address").str.to_lowercase()

    burned = holders.filter(lowered.is_in(list(BURN_ADDRESSES)))
    if not burned.is_empty():
        notes.append(
            f"{burned.height} burn address(es) excluded; tokens sent there are "
            f"destroyed and their holder is not a market participant"
        )
    if excluded:
        matched = holders.filter(lowered.is_in(list(excluded)))
        notes.append(
            f"{matched.height} address(es) excluded by request: {', '.join(sorted(excluded))}"
        )

    kept = holders.filter(~lowered.is_in(list(BURN_ADDRESSES | excluded)))
    return kept, notes


def resolve_total_supply(
    kept: pl.DataFrame,
    snapshots: pl.DataFrame,
    window: Window,
) -> tuple[float, list[str]]:
    """Return the share denominator, with warnings about how complete it is.

    Raises:
        MetricInputError: If the reported supply is non-positive, which makes
            every share undefined rather than merely doubtful.
    """
    snapshot = latest_snapshot(snapshots, window)
    warnings: list[str] = []
    observed = float(kept["balance"].sum()) if not kept.is_empty() else 0.0
    supply = snapshot.get("total_supply")

    if supply is None:
        # Falling back to the sum of observed balances forces shares to sum to
        # one, which hides truncation instead of revealing it. Say so.
        warnings.append(
            "the snapshot reports no total_supply, so shares are taken against the "
            "sum of observed balances; holders the provider omitted are invisible and "
            "the figure is an upper bound on concentration"
        )
        return observed, warnings

    total = float(supply)  # type: ignore[arg-type]
    if total <= 0:
        raise MetricInputError(f"total_supply is {total}, so holder shares are undefined")

    reported_holders = snapshot.get("holder_count")
    if reported_holders is not None:
        reported = int(reported_holders)  # type: ignore[call-overload]
        if reported > 0 and kept.height < reported * COVERAGE_FLOOR:
            warnings.append(
                f"the holder list covers {kept.height} of {reported} reported holders "
                f"({kept.height / reported:.1%}); a truncated distribution biases "
                f"concentration downward, so the true value is higher than reported"
            )

    if observed > total:
        warnings.append(
            f"observed balances sum to {observed:,.4g}, which exceeds the reported "
            f"total_supply of {total:,.4g}; the two figures are inconsistent"
        )
    return total, warnings
