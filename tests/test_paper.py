"""The working paper's quantities, checked against its own definitions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import polars as pl
import pytest
from typer.testing import CliRunner

from rwa_liquidity import cli
from rwa_liquidity.metrics.base import Window
from rwa_liquidity.paper import (
    PANEL_SCHEMA,
    build_panel,
    categorize,
    months,
    months_table,
    paper_numbers,
    turnover_table,
)
from rwa_liquidity.schema.types import ZERO_ADDRESS

if TYPE_CHECKING:
    from pathlib import Path

UID = "ethereum:0x1b19c19393e2d034d8ff31ff34c81252fcbbee92"
WINDOW = Window(start=datetime(2026, 8, 1, tzinfo=UTC), end=datetime(2026, 9, 1, tzinfo=UTC))
INSIDE = WINDOW.start + timedelta(days=3)
DEAD = "0x000000000000000000000000000000000000dead"
ISSUER = "0x" + "1" * 40
POOL = "0x" + "2" * 40
ALICE = "0x" + "a" * 40
BOB = "0x" + "b" * 40
CAROL = "0x" + "c" * 40


def transfers(*rows: tuple[str, str, float], at: datetime = INSIDE) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "asset_uid": [UID] * len(rows),
            "block_time": [at] * len(rows),
            "from_address": [sender for sender, _, _ in rows],
            "to_address": [recipient for _, recipient, _ in rows],
            "amount": [amount for _, _, amount in rows],
        },
        schema={
            "asset_uid": pl.String(),
            "block_time": pl.Datetime("us", "UTC"),
            "from_address": pl.String(),
            "to_address": pl.String(),
            "amount": pl.Float64(),
        },
    )


def supply(value: float) -> pl.DataFrame:
    return pl.DataFrame(
        {"asset_uid": [UID], "as_of": [WINDOW.end], "total_supply": [value]},
        schema={
            "asset_uid": pl.String(),
            "as_of": pl.Datetime("us", "UTC"),
            "total_supply": pl.Float64(),
        },
    )


def holders(balances: dict[str, float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "asset_uid": [UID] * len(balances),
            "as_of": [WINDOW.end] * len(balances),
            "address": list(balances),
            "balance": list(balances.values()),
        },
        schema={
            "asset_uid": pl.String(),
            "as_of": pl.Datetime("us", "UTC"),
            "address": pl.String(),
            "balance": pl.Float64(),
        },
    )


def panel_row(
    moves: pl.DataFrame,
    total: float,
    balances: dict[str, float],
    **kwargs: object,
) -> dict[str, object]:
    panel = build_panel(
        supply(total),
        moves,
        holders(balances),
        assets=[(UID, "OUSG")],
        windows=[WINDOW],
        **kwargs,  # type: ignore[arg-type]
    )
    assert panel.height == 1
    return panel.row(0, named=True)


# --- event categories (Table 1) ---------------------------------------------


def test_creation_and_destruction_take_precedence_over_the_issuer_label() -> None:
    moves = transfers(
        (ZERO_ADDRESS, ISSUER, 1.0),
        (ISSUER, DEAD, 1.0),
        (ISSUER, ALICE, 1.0),
        (ALICE, ISSUER, 1.0),
        (ALICE, BOB, 1.0),
        (ZERO_ADDRESS, DEAD, 1.0),
    )
    assert categorize(moves, issuers=[ISSUER.upper()])["category"].to_list() == [
        "creation",
        "destruction",
        "issuer_linked",
        "issuer_linked",
        "residual",
        "unresolved",
    ]


# --- turnover decomposition (equations 1-5) ---------------------------------


def test_turnover_shares_one_supply_denominator() -> None:
    moves = transfers(
        (ZERO_ADDRESS, ALICE, 30.0),
        (ALICE, ISSUER, 10.0),
        (ALICE, BOB, 10.0),
    )
    row = panel_row(moves, 100.0, {ALICE: 10.0, BOB: 10.0, ISSUER: 80.0}, issuers={UID: [ISSUER]})
    assert row["v_all"] == pytest.approx(50.0)
    assert row["t_all"] == pytest.approx(0.5)
    assert row["t_res"] == pytest.approx(0.1)
    assert row["f"] == pytest.approx(5.0)
    assert row["x"] == pytest.approx(0.8)
    assert (row["n_creation"], row["n_issuer_linked"], row["n_residual"]) == (1, 1, 1)


def test_no_residual_volume_leaves_f_undefined_and_x_at_one() -> None:
    row = panel_row(transfers((ZERO_ADDRESS, ALICE, 5.0)), 100.0, {ALICE: 100.0})
    assert row["f"] is None
    assert row["x"] == pytest.approx(1.0)


def test_no_movement_at_all_leaves_both_f_and_x_undefined() -> None:
    # 0/0 is not a factor of one: there is nothing to decompose.
    row = panel_row(transfers(), 100.0, {ALICE: 100.0})
    assert row["t_all"] == 0.0
    assert row["t_res"] == 0.0
    assert row["f"] is None
    assert row["x"] is None


def test_a_transfer_at_the_window_end_belongs_to_the_next_window() -> None:
    row = panel_row(transfers((ALICE, BOB, 5.0), at=WINDOW.end), 100.0, {ALICE: 100.0})
    assert row["n_all"] == 0


# --- participation and dormancy (equations 6-8) -----------------------------


def test_participation_counts_only_holders_in_positive_value_non_self_residual_transfers() -> None:
    moves = transfers(
        (ALICE, CAROL, 10.0),  # Carol trades out before the end and is not a holder
        (BOB, BOB, 5.0),  # a self-transfer does not establish participation
        (POOL, BOB, 0.0),  # neither does a zero-value transfer
    )
    row = panel_row(moves, 100.0, {ALICE: 40.0, BOB: 30.0, POOL: 30.0})
    assert row["participation"] == pytest.approx(1 / 3)
    assert row["dormancy"] == pytest.approx(0.6)


# --- ownership coverage (equations 9-15) ------------------------------------


def test_the_papers_pooled_contract_example() -> None:
    # Section 5.2: a pool holds two-thirds of supply, one direct address the rest.
    row = panel_row(transfers(), 3.0, {POOL: 2.0, ALICE: 1.0}, exclude={UID: [POOL.upper()]})
    assert row["h_all"] == pytest.approx(5555.56, abs=0.01)
    assert row["coverage"] == pytest.approx(1 / 3)
    assert row["h_ret"] == pytest.approx(1111.11, abs=0.01)
    assert row["k_all"] == pytest.approx(1.0)
    assert row["k_ret"] == pytest.approx(1 / 3)
    # The paper's conditional 10,000 is below the reporting floor in a panel.
    assert row["h_cond"] is None


def test_retained_concentration_factors_into_coverage_and_conditional() -> None:
    row = panel_row(
        transfers(), 10.0, {POOL: 4.0, ALICE: 3.0, BOB: 2.0, CAROL: 1.0}, exclude={UID: [POOL]}
    )
    assert row["h_ret"] == pytest.approx(row["coverage"] ** 2 * row["h_cond"])  # type: ignore[operator]


def test_a_ledger_that_did_not_reconcile_keeps_turnover_but_not_ownership() -> None:
    row = panel_row(
        transfers((ALICE, BOB, 5.0)), 100.0, {ALICE: 100.0}, reconciliation={UID: False}
    )
    assert row["reconciled"] is False
    assert row["t_all"] == pytest.approx(0.05)
    assert row["h_all"] is None
    assert row["coverage"] is None
    assert row["participation"] is None


def test_an_asset_the_run_could_not_fetch_says_what_was_missing() -> None:
    row = panel_row(
        transfers((ALICE, BOB, 5.0)),
        100.0,
        {ALICE: 100.0},
        missing={UID: ("transfers", "holders")},
    )
    assert row["missing"] == "transfers, holders"
    assert row["t_all"] is None
    assert row["h_all"] is None


def test_blocks_and_dropped_transfers_are_carried_into_every_row() -> None:
    row = panel_row(
        transfers(),
        100.0,
        {ALICE: 100.0},
        blocks={WINDOW: (10, 20, 30)},
        dropped_transfers={UID: 2},
    )
    assert (row["start_block"], row["end_block"], row["head_block"]) == (10, 20, 30)
    assert row["dropped_transfers"] == 2


# --- windows and tables -----------------------------------------------------


def test_months_are_calendar_months_across_a_year_boundary() -> None:
    windows = months("2025-12", "2026-02")
    assert [(w.start.month, w.end.month) for w in windows] == [(12, 1), (1, 2), (2, 3)]
    assert windows[0].end.year == 2026


def test_months_refuses_a_reversed_range() -> None:
    with pytest.raises(ValueError, match="before"):
        months("2026-02", "2025-12")


def test_table_2_keeps_the_manuscripts_rows_columns_and_order() -> None:
    # Only the tabular: the caption and notes stay in the manuscript. An asset
    # the run could not measure keeps its row, with every figure undefined.
    panel = build_panel(
        supply(100.0),
        transfers(),
        holders({ALICE: 100.0}),
        assets=[(UID, "OUSG"), ("ethereum:0x" + "9" * 40, "BUIDL")],
        windows=[WINDOW],
        missing={"ethereum:0x" + "9" * 40: ("transfers", "holders")},
    )
    assert turnover_table(panel, WINDOW).splitlines() == [
        "% rwa-liquidity paper: window [2026-08-01, 2026-09-01) UTC.",
        r"\begin{tabular}{@{}lrrrr@{}}",
        r"\toprule",
        r"Asset & $T^{\mathrm{all}}$ & $T^{\mathrm{res}}$ & $F$ & $X$ (\%) \\",
        r"\midrule",
        r"BUIDL & -- & -- & -- & -- \\",
        r"USYC & -- & -- & -- & -- \\",
        r"OUSG & 0.0000 & 0.0000 & -- & -- \\",
        r"FDIT & -- & -- & -- & -- \\",
        r"\bottomrule",
        r"\end{tabular}",
    ]


JULY = Window(start=datetime(2026, 7, 1, tzinfo=UTC), end=WINDOW.start)
BUIDL_UID = "ethereum:0x7712c34205737192402172409a8f7ccef8aa2aec"


def two_month_panel() -> pl.DataFrame:
    """OUSG with a pool that grows from a half to 40% of supply; BUIDL with F of 10, then 2."""
    supplies = pl.concat(
        [
            supply(4.0).with_columns(pl.lit(JULY.end).alias("as_of")),
            supply(10.0),
        ]
    )
    balances = pl.concat(
        [
            holders({POOL: 2.0, ALICE: 1.0, BOB: 1.0}).with_columns(
                pl.lit(JULY.end).alias("as_of")
            ),
            holders({POOL: 4.0, ALICE: 3.0, BOB: 2.0, CAROL: 1.0}),
        ]
    )
    buidl = pl.concat(
        [
            transfers(
                (ZERO_ADDRESS, ALICE, 9.0), (ALICE, BOB, 1.0), at=JULY.start + timedelta(days=3)
            ),
            transfers((ZERO_ADDRESS, ALICE, 1.0), (ALICE, BOB, 1.0)),
        ]
    ).with_columns(pl.lit(BUIDL_UID).alias("asset_uid"))
    return build_panel(
        supplies,
        buidl,
        balances,
        assets=[(UID, "OUSG"), (BUIDL_UID, "BUIDL")],
        windows=[JULY, WINDOW],
        exclude={UID: [POOL]},
    )


def test_conditional_concentration_is_withheld_below_half_coverage() -> None:
    # ZTLN: once the Balancer vault is excluded, one address holds a third of
    # supply. Its conditional HHI of 10,000 describes almost nothing.
    row = panel_row(transfers(), 3.0, {POOL: 2.0, ALICE: 1.0}, exclude={UID: [POOL]})
    assert row["coverage"] == pytest.approx(1 / 3)
    assert row["assessable"] is False
    assert row["h_cond"] is None
    assert row["k_cond"] is None
    assert row["h_ret"] == pytest.approx(1111.11, abs=0.01)


def test_an_exclusion_applies_only_to_the_asset_it_is_listed_for() -> None:
    # The Midas vault pools USTB but is mTBILL's own redemption vault; leaving
    # it out of USTB's holders must not leave it out of mTBILL's.
    other = BUIDL_UID
    balances = pl.concat(
        [
            holders({POOL: 2.0, ALICE: 2.0}),
            holders({POOL: 1.0, BOB: 3.0}).with_columns(pl.lit(other).alias("asset_uid")),
        ]
    )
    supplies = pl.concat([supply(4.0), supply(4.0).with_columns(pl.lit(other).alias("asset_uid"))])
    panel = build_panel(
        supplies,
        transfers(),
        balances,
        assets=[(UID, "OUSG"), (other, "BUIDL")],
        windows=[WINDOW],
        exclude={UID: [POOL]},
    )
    coverage = dict(zip(panel["symbol"], panel["coverage"], strict=True))
    assert coverage == {"OUSG": pytest.approx(0.5), "BUIDL": pytest.approx(1.0)}


def test_half_coverage_is_still_assessable() -> None:
    row = panel_row(transfers(), 4.0, {POOL: 2.0, ALICE: 1.0, BOB: 1.0}, exclude={UID: [POOL]})
    assert row["assessable"] is True
    assert row["h_cond"] == pytest.approx(5000.0)


def test_the_figures_quoted_in_the_text_are_written_as_macros() -> None:
    assert paper_numbers(two_month_panel(), [JULY, WINDOW]).splitlines() == [
        "% rwa-liquidity paper: window [2026-08-01, 2026-09-01) UTC.",
        r"\newcommand{\PanelFirstMonth}{July 2026}",
        r"\newcommand{\PanelLastMonth}{August 2026}",
        r"\newcommand{\OUSGCoverage}{60.0}",
        r"\newcommand{\OUSGTopTenAll}{100.0}",
        r"\newcommand{\OUSGTopTenRet}{60.0}",
        r"\newcommand{\OUSGTopTenCond}{100.0}",
        r"\newcommand{\OUSGHHIAll}{3,000}",
        r"\newcommand{\OUSGHHIRet}{1,400}",
        r"\newcommand{\OUSGHHICond}{3,889}",
        r"\newcommand{\OUSGCoverageFirst}{50.0}",
        r"\newcommand{\OUSGTopTenAllFirst}{100.0}",
        r"\newcommand{\OUSGTopTenRetFirst}{50.0}",
        r"\newcommand{\OUSGTopTenCondFirst}{100.0}",
        r"\newcommand{\OUSGHHIAllFirst}{3,750}",
        r"\newcommand{\OUSGHHIRetFirst}{1,250}",
        r"\newcommand{\OUSGHHICondFirst}{5,000}",
        r"\newcommand{\BUIDLFMedian}{6.0}",
        r"\newcommand{\BUIDLFMin}{2.0}",
        r"\newcommand{\BUIDLFMax}{10.0}",
    ]


def test_the_months_table_summarises_x_and_f_across_months() -> None:
    assert months_table(two_month_panel()).splitlines() == [
        "% rwa-liquidity paper: monthly windows [2026-07-01, 2026-09-01) UTC.",
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Asset & Months & Median $X$ (\%) & Range $X$ (\%) & Median $F$ & Range $F$ \\",
        r"\midrule",
        r"OUSG & 0 & -- & -- & -- & -- \\",
        r"BUIDL & 2 & 70.0 & 50.0--90.0 & 6.0 & 2.0--10.0 \\",
        r"\bottomrule",
        r"\end{tabular}",
    ]


def test_paper_command_writes_the_panel_the_table_and_the_numbers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, object] = {}

    def fake_history(periods: list[Window], *, refresh: bool, head: int | None) -> cli._Collected:
        seen.update(periods=periods, refresh=refresh, head=head)
        return cli._Collected(supply(100.0), transfers(), holders({ALICE: 100.0}))

    monkeypatch.setattr(cli, "_collect_history", fake_history)
    result = CliRunner().invoke(
        cli.app,
        [
            "paper",
            "--first-month",
            "2026-08",
            "--last-month",
            "2026-08",
            "--head",
            "123",
            "--out",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen == {"periods": [WINDOW], "refresh": False, "head": 123}
    panel = pl.read_csv(tmp_path / "panel.csv")
    assert panel.columns == list(PANEL_SCHEMA)
    assert (tmp_path / "table_turnover.tex").read_text(encoding="utf-8").count(r"\toprule") == 1
    assert (tmp_path / "table_months.tex").exists()
    assert (tmp_path / "numbers.tex").read_text(encoding="utf-8").startswith("% rwa-liquidity")
    assert not (tmp_path / "table_coverage.tex").exists()
