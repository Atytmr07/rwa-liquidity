"""Cross-source variance reporting.

When two providers report different numbers for the same asset, this module
reports the disagreement. It does not resolve it. Which source is right is a
research question about the providers, not something a library can decide, and a
library that quietly picked one would launder that judgement into every figure
downstream.

What "agreement" means here is deliberately narrow. Two sources agree on a field
when their values are within a stated relative tolerance **and** their
observations are close enough in time to be comparable. The second condition
matters more than it looks: rwa.xyz publishes no observation timestamp at all, so
its `as_of` is only an upper bound on the figure's age, and a disagreement
against a precisely-timestamped source may be nothing more than the two having
looked at different moments. That possibility is reported rather than assumed
away.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

import polars as pl

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "DEFAULT_STALENESS",
    "DEFAULT_TOLERANCE",
    "RECONCILABLE_FIELDS",
    "Disagreement",
    "ReconciliationReport",
    "reconcile_snapshots",
]

#: Fields two sources can meaningfully be compared on. Deliberately excludes
#: `symbol` and `name`, which differ in spelling without differing in substance.
RECONCILABLE_FIELDS: Final = ("total_supply", "market_value_usd", "price_usd", "holder_count")

#: Relative difference below which two figures are treated as the same number.
#: One percent is loose enough to absorb rounding and a few minutes of drift, and
#: tight enough that a genuinely different measurement stands out.
DEFAULT_TOLERANCE: Final = 0.01

#: How far apart two observations may be and still be worth comparing.
DEFAULT_STALENESS: Final = timedelta(days=1)

#: Above this magnitude, figures are shown with thousands separators and no
#: decimals rather than in scientific notation.
_THOUSAND: Final = 1000


@dataclass(frozen=True, slots=True)
class Disagreement:
    """Two sources reporting different values for one field of one asset.

    Attributes:
        asset_uid: The asset.
        field: Which column disagrees.
        source_a: Name of the first source, alphabetically.
        source_b: Name of the second source.
        value_a: What `source_a` reported.
        value_b: What `source_b` reported.
        relative_difference: `|a - b| / max(|a|, |b|)`. Symmetric, so neither
            source is implicitly treated as the reference.
        observation_gap: How far apart the two observations were taken.
        stale: Whether the gap exceeds the staleness threshold, meaning the two
            may simply have looked at different moments.
    """

    asset_uid: str
    field: str
    source_a: str
    source_b: str
    value_a: float
    value_b: float
    relative_difference: float
    observation_gap: timedelta
    stale: bool

    def describe(self) -> str:
        """Return a one-line summary suitable for a terminal or a log."""
        caveat = " (observations too far apart to compare)" if self.stale else ""
        return (
            f"{self.asset_uid} {self.field}: {self.source_a}={_readable(self.value_a)} vs "
            f"{self.source_b}={_readable(self.value_b)} "
            f"({self.relative_difference:.1%} apart){caveat}"
        )


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """The outcome of comparing every source against every other.

    Attributes:
        disagreements: Every field where two sources differ beyond tolerance,
            worst first.
        compared: How many source-pair-field comparisons were possible.
        single_source_fields: Fields only one source reported, which therefore
            could not be cross-checked. An unchecked figure is not a confirmed
            one, so these are listed rather than passed over in silence.
        tolerance: The relative tolerance applied.
    """

    disagreements: tuple[Disagreement, ...]
    compared: int
    single_source_fields: tuple[tuple[str, str], ...]
    tolerance: float

    @property
    def agrees(self) -> bool:
        """Return whether every comparison that was possible came out clean."""
        return not self.disagreements

    def to_frame(self) -> pl.DataFrame:
        """Return the disagreements as a frame, for export."""
        return pl.DataFrame(
            {
                "asset_uid": [d.asset_uid for d in self.disagreements],
                "field": [d.field for d in self.disagreements],
                "source_a": [d.source_a for d in self.disagreements],
                "source_b": [d.source_b for d in self.disagreements],
                "value_a": [d.value_a for d in self.disagreements],
                "value_b": [d.value_b for d in self.disagreements],
                "relative_difference": [d.relative_difference for d in self.disagreements],
                "observation_gap_hours": [
                    d.observation_gap.total_seconds() / 3600 for d in self.disagreements
                ],
                "stale": [d.stale for d in self.disagreements],
            },
            schema={
                "asset_uid": pl.String(),
                "field": pl.String(),
                "source_a": pl.String(),
                "source_b": pl.String(),
                "value_a": pl.Float64(),
                "value_b": pl.Float64(),
                "relative_difference": pl.Float64(),
                "observation_gap_hours": pl.Float64(),
                "stale": pl.Boolean(),
            },
        )


def _readable(value: float) -> str:
    """Format a figure for a human.

    A general format renders market values in scientific notation, which is
    exactly the wrong choice for a number a reader is meant to sanity-check
    against a fund's published size.
    """
    if abs(value) >= _THOUSAND:
        return f"{value:,.0f}"
    return f"{value:,.4g}"


def _relative_difference(a: float, b: float) -> float:
    """Return the symmetric relative difference between two figures.

    Dividing by the larger magnitude rather than by one of the two means neither
    source is implicitly the reference, so swapping the arguments cannot change
    whether a pair is reported as disagreeing.
    """
    scale = max(abs(a), abs(b))
    if scale == 0:
        # Both are zero, which is agreement, not a division by zero.
        return 0.0
    return abs(a - b) / scale


def _latest_per_source(snapshots: pl.DataFrame) -> pl.DataFrame:
    """Keep only each source's most recent snapshot of each asset."""
    return snapshots.sort("as_of").group_by(["asset_uid", "source"], maintain_order=True).last()


def reconcile_snapshots(
    snapshots: pl.DataFrame,
    *,
    fields: Sequence[str] = RECONCILABLE_FIELDS,
    tolerance: float = DEFAULT_TOLERANCE,
    staleness: timedelta = DEFAULT_STALENESS,
) -> ReconciliationReport:
    """Compare every source against every other across `fields`.

    Only each source's most recent snapshot of an asset is used; comparing a
    source's own history against another's would conflate disagreement with
    change over time.

    Args:
        snapshots: An `AssetSnapshot` frame, which may span several assets and
            sources.
        fields: Which columns to compare.
        tolerance: Relative difference below which two figures count as equal.
        staleness: How far apart two observations may be and still be compared.
            A pair beyond this is still reported, marked `stale`, because the
            difference may be nothing more than elapsed time.

    Returns:
        The report, with disagreements ordered worst first.
    """
    if snapshots.is_empty():
        return ReconciliationReport((), 0, (), tolerance)

    latest = _latest_per_source(snapshots)
    disagreements: list[Disagreement] = []
    single_source: list[tuple[str, str]] = []
    compared = 0

    for (asset_uid,), rows in latest.group_by(["asset_uid"], maintain_order=True):
        records = rows.sort("source").to_dicts()
        for field in fields:
            reported = [record for record in records if record.get(field) is not None]
            if len(reported) < 2:  # noqa: PLR2004 -- a comparison needs two sides
                if reported:
                    single_source.append((str(asset_uid), field))
                continue

            for index, first in enumerate(reported):
                for second in reported[index + 1 :]:
                    compared += 1
                    value_a = float(first[field])
                    value_b = float(second[field])
                    difference = _relative_difference(value_a, value_b)
                    if difference <= tolerance:
                        continue
                    gap = abs(first["as_of"] - second["as_of"])
                    disagreements.append(
                        Disagreement(
                            asset_uid=str(asset_uid),
                            field=field,
                            source_a=str(first["source"]),
                            source_b=str(second["source"]),
                            value_a=value_a,
                            value_b=value_b,
                            relative_difference=difference,
                            observation_gap=gap,
                            stale=gap > staleness,
                        )
                    )

    disagreements.sort(key=lambda d: d.relative_difference, reverse=True)
    return ReconciliationReport(
        disagreements=tuple(disagreements),
        compared=compared,
        single_source_fields=tuple(single_source),
        tolerance=tolerance,
    )
