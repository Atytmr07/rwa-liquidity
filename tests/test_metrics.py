"""Metrics, against a worked example computed by hand.

Every expected value below was calculated on paper from the fixture and is
written into the test as a literal with its arithmetic shown. None of them were
produced by running the code and pasting the output, which would only prove the
code agrees with itself.

The worked example
==================

Window: 2026-06-01T00:00Z to 2026-07-01T00:00Z (30 days, half-open).
Snapshot at the window's end: total_supply = 1000, holder_count = 5,
price_usd = 2.0, market_value_usd = 2000.

Holders at the end of the window::

    A  500      B  250      C  150      D   60      E   40      sum = 1000

Transfers inside the window::

    #  kind          from -> to    amount
    1  mint          0x0  -> A       400
    2  mint          0x0  -> B       200
    3  secondary     A    -> C       100
    4  secondary     C    -> D        60
    5  burn          E    -> 0x0      25
    6  unclassified  D    -> E        15

One further secondary transfer of 999 sits a month before the window and must
never appear in any figure.

Hand-computed volumes::

    secondary_only  = 100 + 60                    = 160
    primary_only    = 400 + 200 + 25              = 625
    all             = 400+200+100+60+25+15        = 800

The gap between 160 and 800 is the entire point of the package: an
implementation that counts issuance as trading reports five times the liquidity
this asset actually has.
"""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from rwa_liquidity.metrics import (
    MetricInputError,
    Window,
    active_holder_ratio,
    dormancy,
    holder_hhi,
    top_holder_share,
    total_volume,
    turnover_ratio,
    volume_per_active_address,
)
from rwa_liquidity.metrics.base import latest_holders
from rwa_liquidity.metrics.trend import (
    AssetTrend,
    TrendPoint,
    build_trend,
    windows_ending,
)
from rwa_liquidity.schema import AssetSnapshot, HolderBalance, TransferEvent, validate
from rwa_liquidity.schema.types import ZERO_ADDRESS, Denomination, TransferKind, VolumeMode

ASSET = "ethereum:0x7712c34205737192402172409a8f7ccef8aa2aec"

A, B, C, D, E = ("0x" + letter * 40 for letter in "abcde")

WINDOW = Window(
    start=datetime(2026, 6, 1, tzinfo=UTC),
    end=datetime(2026, 7, 1, tzinfo=UTC),
)
IN_WINDOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
BEFORE_WINDOW = datetime(2026, 5, 1, tzinfo=UTC)

# (kind, from, to, amount, block_time)
TRANSFERS = [
    (TransferKind.MINT, ZERO_ADDRESS, A, 400.0, IN_WINDOW),
    (TransferKind.MINT, ZERO_ADDRESS, B, 200.0, IN_WINDOW),
    (TransferKind.SECONDARY, A, C, 100.0, IN_WINDOW),
    (TransferKind.SECONDARY, C, D, 60.0, IN_WINDOW),
    (TransferKind.BURN, E, ZERO_ADDRESS, 25.0, IN_WINDOW),
    (TransferKind.UNCLASSIFIED, D, E, 15.0, IN_WINDOW),
    (TransferKind.SECONDARY, A, B, 999.0, BEFORE_WINDOW),
]

BALANCES = [(A, 500.0), (B, 250.0), (C, 150.0), (D, 60.0), (E, 40.0)]


def transfers_frame(*, usd: bool = True) -> pl.DataFrame:
    """Build the worked example's transfers. `amount_usd` is amount x 2."""
    return validate(
        TransferEvent,
        pl.DataFrame(
            {
                "asset_uid": [ASSET] * len(TRANSFERS),
                "source": ["dune"] * len(TRANSFERS),
                "retrieved_at": [WINDOW.end] * len(TRANSFERS),
                "block_time": [row[4] for row in TRANSFERS],
                "tx_hash": [f"0x{index:02x}" for index in range(len(TRANSFERS))],
                "log_index": list(range(len(TRANSFERS))),
                "from_address": [row[1] for row in TRANSFERS],
                "to_address": [row[2] for row in TRANSFERS],
                "amount": [row[3] for row in TRANSFERS],
                "amount_usd": [row[3] * 2 if usd else None for row in TRANSFERS],
                "kind": [row[0].value for row in TRANSFERS],
            },
            schema={
                "asset_uid": pl.String(),
                "source": pl.String(),
                "retrieved_at": pl.Datetime("us", "UTC"),
                "block_time": pl.Datetime("us", "UTC"),
                "tx_hash": pl.String(),
                "log_index": pl.Int64(),
                "from_address": pl.String(),
                "to_address": pl.String(),
                "amount": pl.Float64(),
                "amount_usd": pl.Float64(),
                "kind": pl.String(),
            },
        ),
        origin="test",
    )


def holders_frame(balances: list[tuple[str, float]] | None = None) -> pl.DataFrame:
    rows = BALANCES if balances is None else balances
    return validate(
        HolderBalance,
        pl.DataFrame(
            {
                "asset_uid": [ASSET] * len(rows),
                "source": ["dune"] * len(rows),
                "retrieved_at": [WINDOW.end] * len(rows),
                "as_of": [WINDOW.end] * len(rows),
                "address": [row[0] for row in rows],
                "balance": [row[1] for row in rows],
                "balance_usd": [row[1] * 2 for row in rows],
            },
            schema={
                "asset_uid": pl.String(),
                "source": pl.String(),
                "retrieved_at": pl.Datetime("us", "UTC"),
                "as_of": pl.Datetime("us", "UTC"),
                "address": pl.String(),
                "balance": pl.Float64(),
                "balance_usd": pl.Float64(),
            },
        ),
        origin="test",
    )


def snapshot_frame(
    *,
    total_supply: float | None = 1000.0,
    holder_count: int | None = 5,
    market_value_usd: float | None = 2000.0,
) -> pl.DataFrame:
    return validate(
        AssetSnapshot,
        pl.DataFrame(
            {
                "asset_uid": [ASSET],
                "source": ["rwa_xyz"],
                "retrieved_at": [WINDOW.end],
                "as_of": [WINDOW.end],
                "symbol": ["X"],
                "name": ["Worked Example"],
                "decimals": [18],
                "total_supply": [total_supply],
                "market_value_usd": [market_value_usd],
                "price_usd": [2.0],
                "holder_count": [holder_count],
            },
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


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        # 100 + 60
        (VolumeMode.SECONDARY_ONLY, 160.0),
        # 400 + 200 + 25
        (VolumeMode.PRIMARY_ONLY, 625.0),
        # 400 + 200 + 100 + 60 + 25 + 15
        (VolumeMode.ALL, 800.0),
    ],
)
def test_total_volume_by_mode(mode: VolumeMode, expected: float) -> None:
    assert total_volume(transfers_frame(), window=WINDOW, mode=mode).value == expected


def test_transfers_outside_the_window_are_excluded() -> None:
    # The 999 transfer sits a month early. If windowing were broken every figure
    # in this file would be wrong by roughly an order of magnitude.
    result = total_volume(transfers_frame(), window=WINDOW, mode=VolumeMode.ALL)
    assert result.value == 800.0
    assert result.value != 800.0 + 999.0


def test_default_mode_is_secondary_only() -> None:
    # The headline claim, asserted directly: the default must be the
    # conservative measure, not raw transfer volume.
    assert total_volume(transfers_frame(), window=WINDOW).value == 160.0


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (VolumeMode.SECONDARY_ONLY, 0.16),  # 160 / 1000
        (VolumeMode.PRIMARY_ONLY, 0.625),  # 625 / 1000
        (VolumeMode.ALL, 0.8),  # 800 / 1000
    ],
)
def test_turnover_ratio_by_mode(mode: VolumeMode, expected: float) -> None:
    result = turnover_ratio(transfers_frame(), snapshot_frame(), window=WINDOW, mode=mode)
    assert result.value == pytest.approx(expected)


def test_naive_turnover_overstates_liquidity_fivefold() -> None:
    # Stated as its own test because it is the finding the package exists to
    # produce: 0.80 against 0.16 for the same asset over the same window.
    honest = turnover_ratio(transfers_frame(), snapshot_frame(), window=WINDOW)
    naive = turnover_ratio(transfers_frame(), snapshot_frame(), window=WINDOW, mode=VolumeMode.ALL)
    assert naive.value == pytest.approx(5.0 * (honest.value or 0.0))


def test_usd_and_native_turnover_agree_when_prices_are_consistent() -> None:
    # amount_usd is 2x amount and market_value_usd is 2x total_supply, so the
    # two readings must coincide: 320 / 2000 = 160 / 1000 = 0.16.
    native = turnover_ratio(transfers_frame(), snapshot_frame(), window=WINDOW)
    usd = turnover_ratio(
        transfers_frame(), snapshot_frame(), window=WINDOW, denomination=Denomination.USD
    )
    assert usd.value == pytest.approx(0.16)
    assert usd.value == pytest.approx(native.value)


def test_turnover_is_undefined_when_the_denominator_is_missing() -> None:
    # Not zero. Zero would say the asset is infinitely illiquid; undefined says
    # we do not know how big it is.
    result = turnover_ratio(transfers_frame(), snapshot_frame(total_supply=None), window=WINDOW)
    assert result.value is None
    assert not result.is_defined
    assert any("total_supply" in warning for warning in result.provenance.warnings)


def test_usd_turnover_is_undefined_when_no_usd_amounts_exist() -> None:
    result = turnover_ratio(
        transfers_frame(usd=False),
        snapshot_frame(),
        window=WINDOW,
        denomination=Denomination.USD,
    )
    assert result.value is None


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        # secondary transfers touch A, C, D -> 3 active; 160 / 3
        (VolumeMode.SECONDARY_ONLY, 160.0 / 3.0),
        # every transfer touches A..E, the zero address excluded -> 5; 800 / 5
        (VolumeMode.ALL, 160.0),
    ],
)
def test_volume_per_active_address(mode: VolumeMode, expected: float) -> None:
    result = volume_per_active_address(transfers_frame(), window=WINDOW, mode=mode)
    assert result.value == pytest.approx(expected)


def test_zero_address_is_not_an_active_participant() -> None:
    # Under primary_only the transfers are 0x0->A, 0x0->B and E->0x0. If the
    # zero address counted, the denominator would be 4 rather than 3 and every
    # asset that has ever minted would gain one phantom participant.
    result = volume_per_active_address(
        transfers_frame(), window=WINDOW, mode=VolumeMode.PRIMARY_ONLY
    )
    assert result.value == pytest.approx(625.0 / 3.0)


# ---------------------------------------------------------------------------
# Participation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (VolumeMode.SECONDARY_ONLY, 0.6),  # {A,C,D} / 5
        (VolumeMode.PRIMARY_ONLY, 0.6),  # {A,B,E} / 5
        (VolumeMode.ALL, 1.0),  # {A,B,C,D,E} / 5
    ],
)
def test_active_holder_ratio_by_mode(mode: VolumeMode, expected: float) -> None:
    result = active_holder_ratio(transfers_frame(), snapshot_frame(), window=WINDOW, mode=mode)
    assert result.value == pytest.approx(expected)


def test_active_holder_ratio_above_one_is_reported_not_clamped() -> None:
    # Two holders reported, five addresses active: churn, not an error.
    result = active_holder_ratio(
        transfers_frame(), snapshot_frame(holder_count=2), window=WINDOW, mode=VolumeMode.ALL
    )
    assert result.value == pytest.approx(2.5)
    assert any("traded out" in warning for warning in result.provenance.warnings)


def test_active_holder_ratio_is_undefined_without_a_holder_count() -> None:
    result = active_holder_ratio(
        transfers_frame(), snapshot_frame(holder_count=None), window=WINDOW
    )
    assert result.value is None


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        # active {A,C,D}; dormant B(250) + E(40) = 290 -> 0.29
        (VolumeMode.SECONDARY_ONLY, 0.29),
        # active {A,B,E}; dormant C(150) + D(60) = 210 -> 0.21
        (VolumeMode.PRIMARY_ONLY, 0.21),
        # every holder touched something
        (VolumeMode.ALL, 0.0),
    ],
)
def test_dormancy_by_mode(mode: VolumeMode, expected: float) -> None:
    result = dormancy(
        holders_frame(), transfers_frame(), snapshot_frame(), window=WINDOW, mode=mode
    )
    assert result.value == pytest.approx(expected)


def test_an_address_that_only_received_a_mint_is_dormant() -> None:
    # B's only in-window activity is receiving a 200-token mint. Under the
    # default mode B holds 250 of 1000 and is dormant, which is precisely the
    # reading the package argues for.
    result = dormancy(holders_frame(), transfers_frame(), snapshot_frame(), window=WINDOW)
    assert result.value == pytest.approx(0.29)


# ---------------------------------------------------------------------------
# Concentration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (1, 0.5),  # 500 / 1000
        (2, 0.75),  # (500 + 250) / 1000
        (3, 0.9),  # (500 + 250 + 150) / 1000
        (5, 1.0),  # everything
    ],
)
def test_top_holder_share(n: int, expected: float) -> None:
    result = top_holder_share(holders_frame(), snapshot_frame(), window=WINDOW, n=n)
    assert result.value == pytest.approx(expected)


def test_top_ten_share_warns_when_fewer_than_ten_holders_are_known() -> None:
    result = top_holder_share(holders_frame(), snapshot_frame(), window=WINDOW)
    assert result.value == pytest.approx(1.0)
    assert any("fewer than the 10" in warning for warning in result.provenance.warnings)


def test_holder_hhi() -> None:
    # shares 0.5, 0.25, 0.15, 0.06, 0.04
    # squares 0.25 + 0.0625 + 0.0225 + 0.0036 + 0.0016 = 0.3402
    # x 10000 = 3402
    result = holder_hhi(holders_frame(), snapshot_frame(), window=WINDOW)
    assert result.value == pytest.approx(3402.0)


def test_hhi_of_a_single_holder_is_the_maximum() -> None:
    result = holder_hhi(holders_frame([(A, 1000.0)]), snapshot_frame(), window=WINDOW)
    assert result.value == pytest.approx(10_000.0)


def test_hhi_of_ten_equal_holders_is_one_thousand() -> None:
    # Numbered from 1: index 0 would render as the zero address, which is
    # excluded as a burn address and would leave nine holders scoring 900.
    equal = [(f"0x{index:040x}", 100.0) for index in range(1, 11)]
    result = holder_hhi(holders_frame(equal), snapshot_frame(), window=WINDOW)
    assert result.value == pytest.approx(1000.0)


def test_excluded_addresses_are_removed_and_recorded() -> None:
    # A holds 500 of 1000. Excluding it leaves B..E with 500 between them, so
    # the top-2 share becomes (250 + 150) / 1000 = 0.4 against total supply.
    result = top_holder_share(holders_frame(), snapshot_frame(), window=WINDOW, n=2, exclude=[A])
    assert result.value == pytest.approx(0.4)
    assert any("excluded by request" in note for note in result.provenance.exclusions)


def test_burn_address_holdings_are_excluded() -> None:
    with_burn = [*BALANCES, (ZERO_ADDRESS, 300.0)]
    result = top_holder_share(holders_frame(with_burn), snapshot_frame(), window=WINDOW, n=1)
    # Still A at 500/1000, not the burn address at 300.
    assert result.value == pytest.approx(0.5)
    assert any("burn address" in note for note in result.provenance.exclusions)


def test_float_summation_noise_does_not_flag_the_supply_as_inconsistent() -> None:
    # Measured on a real on-chain reconstruction: a ledger replay's balances
    # summed to 30837.417783566347 against a totalSupply() of
    # 30837.417783566332, a difference of 1.46e-11 -- float64 summation order,
    # not a wrong reconstruction. A strict `observed > total` flagged it anyway.
    noisy = [(A, 500.0 + 4e-11), (B, 250.0), (C, 150.0), (D, 60.0), (E, 40.0)]
    result = holder_hhi(holders_frame(noisy), snapshot_frame(), window=WINDOW)
    assert not any("inconsistent" in warning for warning in result.provenance.warnings)


def test_a_real_supply_mismatch_is_still_flagged() -> None:
    # The tolerance above must not swallow a genuine mismatch, which is what
    # caught USDM's rebasing balances in the published findings.
    overshoot = [(A, 900.0), (B, 250.0), (C, 150.0), (D, 60.0), (E, 40.0)]
    result = holder_hhi(holders_frame(overshoot), snapshot_frame(), window=WINDOW)
    assert any("inconsistent" in warning for warning in result.provenance.warnings)


def test_truncated_holder_list_is_flagged_as_biased_downward() -> None:
    # Two of a reported 5000 holders. HHI computed from that is meaningless
    # without the caveat, so the caveat has to be attached to the value.
    result = holder_hhi(
        holders_frame([(A, 500.0), (B, 250.0)]),
        snapshot_frame(holder_count=5000),
        window=WINDOW,
    )
    assert result.value == pytest.approx(0.25 * 10_000 + 0.0625 * 10_000)
    assert any("biases concentration downward" in w for w in result.provenance.warnings)


# ---------------------------------------------------------------------------
# Provenance and input handling
# ---------------------------------------------------------------------------


def test_provenance_records_the_window_mode_and_record_count() -> None:
    result = total_volume(transfers_frame(), window=WINDOW, mode=VolumeMode.SECONDARY_ONLY)
    provenance = result.provenance

    assert provenance.metric == "total_volume"
    assert provenance.asset_uid == ASSET
    assert provenance.mode is VolumeMode.SECONDARY_ONLY
    assert provenance.window == WINDOW
    assert provenance.n_records == 2  # the two secondary transfers
    assert provenance.sources == ("dune",)


def test_provenance_names_every_contributing_source() -> None:
    result = turnover_ratio(transfers_frame(), snapshot_frame(), window=WINDOW)
    assert result.provenance.sources == ("dune", "rwa_xyz")


def test_unclassified_transfers_are_reported_as_a_lower_bound() -> None:
    # One of six in-window transfers cannot be classified. Under any narrow mode
    # it is dropped, and the reader has to be told how much was set aside.
    result = total_volume(transfers_frame(), window=WINDOW)
    assert any("could not be classified" in w for w in result.provenance.warnings)


def test_exclusions_record_what_the_mode_filtered_out() -> None:
    result = total_volume(transfers_frame(), window=WINDOW)
    assert any("excluded by mode" in note for note in result.provenance.exclusions)


def test_an_asset_that_never_traded_scores_zero_not_undefined() -> None:
    # A fund that only mints and redeems. Its secondary turnover is a real 0.0,
    # and reporting None instead would lose the finding.
    primary_only = transfers_frame().filter(
        pl.col("kind").is_in([TransferKind.MINT.value, TransferKind.BURN.value])
    )
    result = turnover_ratio(primary_only, snapshot_frame(), window=WINDOW)
    assert result.value == 0.0
    assert result.is_defined


def test_metrics_refuse_to_aggregate_across_assets() -> None:
    two = pl.concat([transfers_frame(), transfers_frame().with_columns(asset_uid=pl.lit("x:y"))])
    with pytest.raises(MetricInputError, match="2 assets"):
        total_volume(two, window=WINDOW)


def test_window_must_be_ordered_and_aware() -> None:
    with pytest.raises(MetricInputError, match="not after"):
        Window(start=WINDOW.end, end=WINDOW.start)
    with pytest.raises(MetricInputError, match="timezone-aware"):
        Window(start=datetime(2026, 6, 1), end=datetime(2026, 7, 1))  # noqa: DTZ001


def test_default_window_is_thirty_days() -> None:
    assert Window.ending(WINDOW.end).days == 30


def test_a_snapshot_taken_just_after_the_window_is_still_used() -> None:
    # A live source reads the chain as it is now, and a full-history scan takes
    # minutes, so the reading always post-dates the window it was asked for.
    # Refusing it would mean no metric at all for any live measurement.
    late = snapshot_frame().with_columns(as_of=pl.lit(WINDOW.end).dt.offset_by("5m"))
    result = turnover_ratio(transfers_frame(), late, window=WINDOW)
    assert result.value == pytest.approx(0.16)


def test_a_snapshot_a_day_after_the_window_is_still_refused() -> None:
    # An hour against a 30-day window is immaterial. A day is not.
    late = snapshot_frame().with_columns(as_of=pl.lit(WINDOW.end).dt.offset_by("1d"))
    with pytest.raises(MetricInputError, match="no snapshot within"):
        turnover_ratio(transfers_frame(), late, window=WINDOW)


def test_a_late_source_still_contributes_the_fields_only_it_reported() -> None:
    # The trap this guards: a source whose timestamp falls inside the window but
    # which reports no supply would otherwise win outright, and the supply a
    # slightly-later source did fetch would read as missing.
    price_only = snapshot_frame(total_supply=None, holder_count=None).with_columns(
        source=pl.lit("price_feed"), as_of=pl.lit(WINDOW.end).dt.offset_by("-1h")
    )
    supply_only = snapshot_frame(market_value_usd=None).with_columns(
        source=pl.lit("on_chain"), as_of=pl.lit(WINDOW.end).dt.offset_by("2m")
    )
    result = turnover_ratio(transfers_frame(), pl.concat([price_only, supply_only]), window=WINDOW)
    assert result.value == pytest.approx(0.16)


def test_active_holder_ratio_prefers_an_observed_distribution() -> None:
    # An observed distribution checked against on-chain supply is exact; a
    # reported count is a figure taken on faith. Here the two disagree: five
    # holder rows against a reported count of 50. Under secondary_only three
    # addresses were active, so 3/5 = 0.6 rather than 3/50 = 0.06.
    result = active_holder_ratio(
        transfers_frame(),
        snapshot_frame(holder_count=50),
        window=WINDOW,
        holders=holders_frame(),
    )
    assert result.value == pytest.approx(0.6)
    assert any("actually observed" in w for w in result.provenance.warnings)
    assert any("reported count was 50" in w for w in result.provenance.warnings)


def test_active_holder_ratio_falls_back_to_the_reported_count() -> None:
    result = active_holder_ratio(transfers_frame(), snapshot_frame(), window=WINDOW)
    assert result.value == pytest.approx(0.6)  # 3 of 5 reported holders


def test_an_asset_with_no_transfers_reports_zero_not_undefined() -> None:
    # The asset identity comes from the caller, because there is no transfer row
    # to read it from. Without that the quietest assets -- the ones this package
    # is looking for -- would be reported as unmeasured.
    empty = transfers_frame().clear()
    result = turnover_ratio(empty, snapshot_frame(), window=WINDOW, asset_uid=ASSET)
    assert result.value == 0.0
    assert result.provenance.asset_uid == ASSET


def test_a_mismatched_asset_uid_is_refused() -> None:
    with pytest.raises(MetricInputError, match="was being measured"):
        turnover_ratio(
            transfers_frame(), snapshot_frame(), window=WINDOW, asset_uid="ethereum:0xdead"
        )


def test_a_share_above_one_is_refused_rather_than_published() -> None:
    # A rebasing token's balances grow without transfers, so a ledger replayed
    # from transfers disagrees with supply and yields shares above 1. USDM
    # produced a top-10 share of 2.21 this way. A warning on an impossible
    # number is not enough; it invites the reader to treat it as a percentage.
    inflated = holders_frame([(A, 1500.0), (B, 900.0)])
    top = top_holder_share(inflated, snapshot_frame(), window=WINDOW, n=2)
    hhi = holder_hhi(inflated, snapshot_frame(), window=WINDOW)

    assert top.value is None
    assert hhi.value is None
    assert any("not a possible share" in w for w in top.provenance.warnings)
    assert any("rebases" in w for w in hhi.provenance.warnings)


def test_dormancy_above_one_is_refused_too() -> None:
    inflated = holders_frame([(B, 1500.0)])
    result = dormancy(inflated, transfers_frame(), snapshot_frame(), window=WINDOW)
    assert result.value is None
    assert any("not a possible share" in w for w in result.provenance.warnings)


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------


def test_windows_tile_without_overlap() -> None:
    periods = windows_ending(WINDOW.end, days=30, periods=3)
    assert len(periods) == 3
    # Oldest first, and each window's end is the next one's start, so a transfer
    # on a boundary is counted exactly once across the series.
    assert periods[-1].end == WINDOW.end
    assert periods[0].end == periods[1].start
    assert periods[1].end == periods[2].start


def test_a_trend_tracks_one_metric_across_windows() -> None:
    periods = windows_ending(WINDOW.end, days=30, periods=2)
    # The worked example's transfers all sit in the latest window; the earlier one
    # holds only the out-of-window transfer, which is not secondary volume.
    snapshots = pl.concat(
        [snapshot_frame().with_columns(as_of=pl.lit(period.end)) for period in periods]
    )
    holders = pl.concat(
        [holders_frame().with_columns(as_of=pl.lit(period.end)) for period in periods]
    )
    trends = build_trend(
        snapshots, transfers_frame(), holders, windows=periods, metric="turnover_ratio"
    )

    assert len(trends) == 1
    assert trends[0].values[-1] == pytest.approx(0.16)
    assert trends[0].symbol == "X"


def test_holder_distributions_are_selected_per_window() -> None:
    # A holder frame carrying several instants must not have its balances summed
    # across them; that multiplies supply and makes every share exceed 1.

    periods = windows_ending(WINDOW.end, days=30, periods=2)
    stacked = pl.concat(
        [holders_frame().with_columns(as_of=pl.lit(period.end)) for period in periods]
    )
    assert stacked.height == 10
    assert latest_holders(stacked, periods[-1]).height == 5
    assert latest_holders(stacked, periods[0]).height == 5


def test_a_window_with_no_holder_distribution_yields_nothing() -> None:
    # Empty is the honest answer: a distribution from a later instant would
    # describe a different set of holders.

    periods = windows_ending(WINDOW.end, days=30, periods=2)
    only_recent = holders_frame().with_columns(as_of=pl.lit(periods[-1].end))
    assert latest_holders(only_recent, periods[0]).is_empty()


def test_direction_is_coarse_on_purpose() -> None:
    def trend_of(*values: float | None) -> AssetTrend:
        periods = [WINDOW] * len(values)
        return AssetTrend(
            asset_uid=ASSET,
            symbol="X",
            metric="turnover_ratio",
            mode=VolumeMode.SECONDARY_ONLY,
            points=tuple(
                TrendPoint(window=w, value=v) for w, v in zip(periods, values, strict=True)
            ),
        )

    assert trend_of(0.10, 0.30).direction == "rising"
    assert trend_of(0.30, 0.10).direction == "falling"
    # Within a tenth is noise at these counts, not a trend.
    assert trend_of(0.100, 0.105).direction == "flat"
    assert trend_of(0.0, 0.0).direction == "flat at zero"
    assert trend_of(0.0, 0.5).direction == "rising from zero"
    assert trend_of(0.1).direction == "insufficient data"
    assert trend_of(None, None).direction == "insufficient data"
