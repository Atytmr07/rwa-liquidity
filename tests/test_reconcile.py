"""Cross-source reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from rwa_liquidity.reconcile import reconcile_snapshots
from rwa_liquidity.schema import AssetSnapshot, validate

ASSET = "ethereum:0x7712c34205737192402172409a8f7ccef8aa2aec"
OTHER = "ethereum:0x" + "1" * 40
NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def snapshots(*rows: dict[str, object]) -> pl.DataFrame:
    """Build an AssetSnapshot frame from partial rows, filling the rest."""
    defaults: dict[str, object] = {
        "asset_uid": ASSET,
        "source": "rwa_xyz",
        "retrieved_at": NOW,
        "as_of": NOW,
        "symbol": None,
        "name": None,
        "decimals": None,
        "total_supply": None,
        "market_value_usd": None,
        "price_usd": None,
        "holder_count": None,
    }
    filled = [{**defaults, **row} for row in rows]
    return validate(
        AssetSnapshot,
        pl.DataFrame(
            {key: [row[key] for row in filled] for key in defaults},
            schema={
                "asset_uid": pl.String(),
                "source": pl.String(),
                "retrieved_at": pl.Datetime("us", "UTC"),
                "as_of": pl.Datetime("us", "UTC"),
                "symbol": pl.String(),
                "name": pl.String(),
                "decimals": pl.Int64(),
                "total_supply": pl.Float64(),
                "market_value_usd": pl.Float64(),
                "price_usd": pl.Float64(),
                "holder_count": pl.Int64(),
            },
        ),
        origin="test",
    )


def test_agreeing_sources_produce_no_disagreements() -> None:
    report = reconcile_snapshots(
        snapshots(
            {"source": "rwa_xyz", "market_value_usd": 1_000_000.0},
            {"source": "defillama_protocol_tvl", "market_value_usd": 1_000_000.0},
        )
    )
    assert report.agrees
    assert report.compared == 1


def test_small_differences_fall_inside_tolerance() -> None:
    # 0.5% apart. Rounding and a few minutes of drift must not read as a finding.
    report = reconcile_snapshots(
        snapshots(
            {"source": "a", "market_value_usd": 1_000_000.0},
            {"source": "b", "market_value_usd": 1_005_000.0},
        )
    )
    assert report.agrees


def test_a_real_disagreement_is_reported_with_both_values() -> None:
    # The BUIDL case: a protocol figure covering two share classes against the
    # value of one contract. Not a bug in either source, and not something the
    # package should resolve by picking one.
    report = reconcile_snapshots(
        snapshots(
            {"source": "rwa_xyz", "market_value_usd": 1_158_286_022.0},
            {"source": "defillama_protocol_tvl", "market_value_usd": 3_443_574_869.0},
        )
    )
    assert not report.agrees
    found = report.disagreements[0]
    assert found.field == "market_value_usd"
    # Sources are ordered alphabetically, not by the order they were passed, so
    # the same pair always reads the same way in a report.
    assert (found.source_a, found.value_a) == ("defillama_protocol_tvl", 3_443_574_869.0)
    assert (found.source_b, found.value_b) == ("rwa_xyz", 1_158_286_022.0)
    # |a-b| / max(|a|,|b|) = 2285288847 / 3443574869 = 0.6636...
    assert found.relative_difference == pytest.approx(0.6636, abs=1e-4)


def test_the_difference_is_symmetric() -> None:
    # Dividing by one side would make the answer depend on argument order, and
    # on which source happened to sort first.
    forward = reconcile_snapshots(
        snapshots({"source": "a", "price_usd": 100.0}, {"source": "b", "price_usd": 50.0})
    ).disagreements[0]
    reverse = reconcile_snapshots(
        snapshots({"source": "b", "price_usd": 100.0}, {"source": "a", "price_usd": 50.0})
    ).disagreements[0]
    assert forward.relative_difference == reverse.relative_difference == pytest.approx(0.5)


def test_two_zeroes_agree_rather_than_dividing_by_zero() -> None:
    report = reconcile_snapshots(
        snapshots({"source": "a", "total_supply": 0.0}, {"source": "b", "total_supply": 0.0})
    )
    assert report.agrees


def test_a_field_only_one_source_reports_is_listed_not_ignored() -> None:
    # An unchecked figure is not a confirmed one. DeFiLlama publishes no holder
    # counts, so a report that stayed silent here would imply agreement.
    report = reconcile_snapshots(
        snapshots(
            {"source": "rwa_xyz", "holder_count": 75, "market_value_usd": 1.0},
            {"source": "defillama_prices", "market_value_usd": 1.0},
        )
    )
    assert report.agrees
    assert (ASSET, "holder_count") in report.single_source_fields


def test_observations_far_apart_are_flagged_as_incomparable() -> None:
    # rwa.xyz publishes no observation timestamp, so its as_of is only an upper
    # bound. A difference against a precisely-timestamped source may be nothing
    # but elapsed time, and saying so is more honest than a bare percentage.
    report = reconcile_snapshots(
        snapshots(
            {"source": "a", "price_usd": 100.0, "as_of": NOW},
            {"source": "b", "price_usd": 50.0, "as_of": NOW - timedelta(days=5)},
        )
    )
    found = report.disagreements[0]
    assert found.stale
    assert found.observation_gap == timedelta(days=5)
    assert "too far apart" in found.describe()


def test_recent_observations_are_not_flagged_stale() -> None:
    report = reconcile_snapshots(
        snapshots(
            {"source": "a", "price_usd": 100.0, "as_of": NOW},
            {"source": "b", "price_usd": 50.0, "as_of": NOW - timedelta(hours=2)},
        )
    )
    assert not report.disagreements[0].stale


def test_only_each_sources_latest_snapshot_is_used() -> None:
    # Comparing a source's own history against another's would report change
    # over time as if it were disagreement between providers.
    report = reconcile_snapshots(
        snapshots(
            {"source": "a", "price_usd": 999.0, "as_of": NOW - timedelta(days=30)},
            {"source": "a", "price_usd": 100.0, "as_of": NOW},
            {"source": "b", "price_usd": 100.0, "as_of": NOW},
        )
    )
    assert report.agrees


def test_three_sources_produce_every_pairing() -> None:
    report = reconcile_snapshots(
        snapshots(
            {"source": "a", "price_usd": 100.0},
            {"source": "b", "price_usd": 100.0},
            {"source": "c", "price_usd": 100.0},
        )
    )
    assert report.compared == 3


def test_assets_are_reconciled_independently() -> None:
    report = reconcile_snapshots(
        snapshots(
            {"asset_uid": ASSET, "source": "a", "price_usd": 100.0},
            {"asset_uid": ASSET, "source": "b", "price_usd": 100.0},
            {"asset_uid": OTHER, "source": "a", "price_usd": 100.0},
            {"asset_uid": OTHER, "source": "b", "price_usd": 1.0},
        )
    )
    assert len(report.disagreements) == 1
    assert report.disagreements[0].asset_uid == OTHER


def test_disagreements_come_back_worst_first() -> None:
    report = reconcile_snapshots(
        snapshots(
            {"source": "a", "price_usd": 100.0, "total_supply": 100.0},
            {"source": "b", "price_usd": 90.0, "total_supply": 10.0},
        )
    )
    differences = [d.relative_difference for d in report.disagreements]
    assert differences == sorted(differences, reverse=True)


def test_empty_input_is_an_empty_report() -> None:
    report = reconcile_snapshots(snapshots().clear())
    assert report.agrees
    assert report.compared == 0


def test_report_converts_to_a_frame_for_export() -> None:
    report = reconcile_snapshots(
        snapshots({"source": "a", "price_usd": 100.0}, {"source": "b", "price_usd": 50.0})
    )
    frame = report.to_frame()
    assert frame.height == 1
    assert frame["relative_difference"].item() == pytest.approx(0.5)


def test_empty_report_still_produces_a_typed_frame() -> None:
    frame = reconcile_snapshots(snapshots().clear()).to_frame()
    assert frame.is_empty()
    assert frame.schema["relative_difference"] == pl.Float64
