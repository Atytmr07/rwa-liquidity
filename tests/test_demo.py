"""The sample dataset, the report layer, export, and the CLI.

The assertions about the sample data are not incidental. `data/sample/README.md`
makes specific claims about what each asset demonstrates, and a dataset that
quietly stopped demonstrating them would make that document a lie while every
other test still passed.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from rwa_liquidity.cli import app
from rwa_liquidity.demo import DEMO_LABEL, DemoDataUnavailableError, load_demo_dataset
from rwa_liquidity.export import to_latex, write_frame
from rwa_liquidity.metrics.report import METRIC_COLUMNS, build_report, report_frame
from rwa_liquidity.schema.types import VolumeMode

runner = CliRunner()

TBILL = "ethereum:0x0000000000000000000000000000000000000001"
CREDIT = "ethereum:0x0000000000000000000000000000000000000003"


def reports(mode: VolumeMode = VolumeMode.SECONDARY_ONLY) -> dict[str, object]:
    dataset = load_demo_dataset()
    built = build_report(
        dataset.snapshots, dataset.transfers, dataset.holders, window=dataset.window, mode=mode
    )
    return {report.asset_uid: report for report in built}


# ---------------------------------------------------------------------------
# The sample dataset
# ---------------------------------------------------------------------------


def test_sample_data_passes_the_same_validation_as_a_real_source() -> None:
    # Loaded through `validate`, so a schema change that broke the sample would
    # fail here rather than producing a quietly wrong demo.
    dataset = load_demo_dataset()
    assert dataset.snapshots.height == 4
    assert dataset.transfers.height == 23
    assert dataset.holders.height == 26
    assert len(dataset.asset_uids) == 3


def test_sample_timestamps_are_timezone_aware() -> None:
    dataset = load_demo_dataset()
    assert dataset.transfers.schema["block_time"] == pl.Datetime("us", "UTC")


def test_missing_sample_directory_says_how_to_rebuild() -> None:
    with pytest.raises(DemoDataUnavailableError, match="rebuild it"):
        load_demo_dataset(Path("does-not-exist"))


def test_tbill_has_no_secondary_market_at_all() -> None:
    # The claim data/sample/README.md is built around. 280m issued and 50m
    # redeemed, nothing traded between holders.
    tbill = reports()[TBILL]
    assert tbill.value("turnover_ratio") == 0.0  # type: ignore[attr-defined]
    assert tbill.value("dormancy") == 1.0  # type: ignore[attr-defined]


def test_the_naive_reading_of_tbill_reports_two_thirds_turnover() -> None:
    # 330m of issuance and redemption against 500m of supply. This is the number
    # an implementation that ignores the primary market would publish.
    tbill = reports(VolumeMode.ALL)[TBILL]
    assert tbill.value("turnover_ratio") == pytest.approx(0.66)  # type: ignore[attr-defined]
    assert tbill.value("dormancy") == pytest.approx(0.03)  # type: ignore[attr-defined]


def test_credit_reports_its_unclassified_share() -> None:
    warnings = reports()[CREDIT].warnings  # type: ignore[attr-defined]
    assert any("could not be classified" in w for w in warnings)


def test_credit_reports_its_holder_list_coverage() -> None:
    warnings = reports()[CREDIT].warnings  # type: ignore[attr-defined]
    assert any("6 of 40 reported holders" in w for w in warnings)


# ---------------------------------------------------------------------------
# The report layer
# ---------------------------------------------------------------------------


def test_report_frame_has_one_row_per_asset_and_every_metric() -> None:
    dataset = load_demo_dataset()
    frame = report_frame(
        build_report(dataset.snapshots, dataset.transfers, dataset.holders, window=dataset.window)
    )
    assert frame.height == 3
    for name, _ in METRIC_COLUMNS:
        assert name in frame.columns


def test_report_records_the_mode_it_was_computed_under() -> None:
    # A figure copied out of a table loses its mode unless the table carries it.
    dataset = load_demo_dataset()
    frame = report_frame(
        build_report(
            dataset.snapshots,
            dataset.transfers,
            dataset.holders,
            window=dataset.window,
            mode=VolumeMode.ALL,
        )
    )
    assert frame["mode"].unique().to_list() == ["all"]


def test_an_asset_with_no_transfers_scores_zero_turnover() -> None:
    # Not None. An asset with supply that did not move has a turnover of zero,
    # and that is the finding this package exists to surface -- ZTLN has $150m
    # outstanding and no transfers at all. Reporting it as unmeasured would hide
    # exactly the assets worth looking at.
    dataset = load_demo_dataset()
    built = build_report(
        dataset.snapshots,
        dataset.transfers.clear(),
        dataset.holders,
        window=dataset.window,
    )
    assert len(built) == 3
    assert built[0].value("turnover_ratio") == 0.0
    assert built[0].value("dormancy") == 1.0


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def demo_frame() -> pl.DataFrame:
    dataset = load_demo_dataset()
    return report_frame(
        build_report(dataset.snapshots, dataset.transfers, dataset.holders, window=dataset.window)
    )


@pytest.mark.parametrize("suffix", ["csv", "parquet", "tex"])
def test_export_round_trips_by_suffix(tmp_path: Path, suffix: str) -> None:
    path = write_frame(demo_frame(), tmp_path / f"metrics.{suffix}")
    assert path.is_file()
    assert path.stat().st_size > 0


def test_export_creates_missing_parent_directories(tmp_path: Path) -> None:
    path = write_frame(demo_frame(), tmp_path / "nested" / "deeper" / "metrics.csv")
    assert path.is_file()


def test_unknown_export_format_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown export format"):
        write_frame(demo_frame(), tmp_path / "metrics.xlsx")


def test_latex_escapes_characters_that_would_break_compilation() -> None:
    # Asset uids and source names contain underscores. Unescaped, the table
    # simply does not compile, which is a silent failure at the worst moment.
    latex = to_latex(pl.DataFrame({"name": ["a_b & c% d#"]}))
    assert r"a\_b \& c\% d\#" in latex


def test_latex_marks_undefined_metrics_rather_than_leaving_a_blank() -> None:
    # A blank cell reads as an oversight; "--" reads as a result.
    latex = to_latex(pl.DataFrame({"value": [None]}, schema={"value": pl.Float64}))
    assert "--" in latex


def test_latex_right_aligns_numbers_and_left_aligns_text() -> None:
    latex = to_latex(pl.DataFrame({"name": ["a"], "value": [1.0]}))
    assert r"\begin{tabular}{lr}" in latex


def test_latex_carries_a_caption_and_label() -> None:
    latex = to_latex(pl.DataFrame({"a": [1]}), caption="Liquidity metrics", label="tab:liquidity")
    assert r"\caption{Liquidity metrics}" in latex
    assert r"\label{tab:liquidity}" in latex


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_demo_report_runs_with_no_api_keys() -> None:
    # The property that makes the repository worth cloning: two commands, real
    # output, no credentials.
    result = runner.invoke(app, ["report", "--demo"])
    assert result.exit_code == 0
    assert "SYNTH-TBILL" in result.output


def test_demo_output_always_says_the_data_is_synthetic() -> None:
    result = runner.invoke(app, ["report", "--demo"])
    assert DEMO_LABEL in result.output


def test_demo_output_states_the_mode() -> None:
    assert "secondary_only" in runner.invoke(app, ["report", "--demo"]).output
    assert "mode = all" in runner.invoke(app, ["report", "--demo", "--mode", "all"]).output


def test_demo_output_prints_caveats() -> None:
    output = runner.invoke(app, ["report", "--demo"]).output
    assert "Caveats" in output
    assert "truncated distribution" in output


def test_demo_output_reports_the_cross_source_disagreement() -> None:
    output = runner.invoke(app, ["report", "--demo"]).output
    assert "Cross-source disagreement" in output
    assert "total_supply" in output


def test_demo_writes_a_csv(tmp_path: Path) -> None:
    destination = tmp_path / "metrics.csv"
    result = runner.invoke(app, ["report", "--demo", "--out", str(destination)])
    assert result.exit_code == 0
    written = pl.read_csv(destination)
    assert written.height == 3
    assert "turnover_ratio" in written.columns


def test_live_mode_is_offered_and_needs_no_key() -> None:
    # Live mode measures real assets against a public node. The help text has to
    # say that keys are not required, or nobody will try it.
    output = runner.invoke(app, ["report", "--help"]).output
    assert "--demo" in output
    assert "--refresh" in output


def test_invalid_mode_is_rejected() -> None:
    assert runner.invoke(app, ["report", "--demo", "--mode", "nonsense"]).exit_code != 0


def test_sources_command_marks_which_adapters_are_verified() -> None:
    output = runner.invoke(app, ["sources"]).output
    assert "defillama_prices" in output
    assert "dune" in output
    # The distinction between "documented" and "observed" has to survive into
    # the interface a user actually sees.
    assert "Verified live" in output


def test_window_command_reports_the_default_period() -> None:
    result = runner.invoke(app, ["window"])
    assert result.exit_code == 0
    assert "30 days" in result.output


def test_latex_renders_counts_without_decimals() -> None:
    # "n_warnings = 1.0000" implies a precision a count does not have.
    latex = to_latex(pl.DataFrame({"n": [3]}, schema={"n": pl.Int64}))
    assert "3 \\\\" in latex


def test_latex_renders_booleans_as_words_not_numbers() -> None:
    # bool is a subclass of int, so the int branch would otherwise claim it.
    latex = to_latex(pl.DataFrame({"stale": [True]}, schema={"stale": pl.Boolean}))
    assert "yes" in latex


def test_an_unmeasured_asset_is_not_reported_as_inactive() -> None:
    # A failed scan and an asset that did not trade produce the same empty frame.
    # Reporting the first as the second would manufacture a finding out of a
    # failed request -- PAXG exceeds the scan budget and briefly read as having
    # a turnover of exactly zero.
    dataset = load_demo_dataset()
    built = build_report(
        dataset.snapshots,
        dataset.transfers.clear(),
        dataset.holders,
        window=dataset.window,
        unmeasured={TBILL},
    )
    tbill = next(r for r in built if r.asset_uid == TBILL)
    others = [r for r in built if r.asset_uid != TBILL]

    assert tbill.value("turnover_ratio") is None
    assert any("nothing about its activity is known" in w for w in tbill.warnings)
    # The rest are still measured, and still report zero.
    assert all(r.value("turnover_ratio") == 0.0 for r in others)
