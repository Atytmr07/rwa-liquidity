"""The validation boundary.

The acceptance criterion for this layer is not "invalid frames are rejected" but
"invalid frames are rejected with a message someone can act on". Every test here
asserts on the content of the message, not just that an exception was raised.
"""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from rwa_liquidity.schema import (
    AssetSnapshot,
    HolderBalance,
    SchemaValidationError,
    TransferEvent,
    validate,
)

from .conftest import NOW, asset_snapshot_frame, holder_balance_frame, transfer_event_frame


def test_valid_frames_pass(
    snapshots: pl.DataFrame, transfers: pl.DataFrame, holders: pl.DataFrame
) -> None:
    assert validate(AssetSnapshot, snapshots, origin="defillama").height == 1
    assert validate(TransferEvent, transfers, origin="dune").height == 2
    assert validate(HolderBalance, holders, origin="dune").height == 2


def test_empty_frame_with_the_right_columns_is_valid(snapshots: pl.DataFrame) -> None:
    # An asset with no activity in the window is a legitimate answer, and the
    # thin markets this package studies produce it often.
    assert validate(AssetSnapshot, snapshots.clear(), origin="defillama").is_empty()


def test_error_names_the_origin_and_the_frame(snapshots: pl.DataFrame) -> None:
    broken = snapshots.with_columns(total_supply=pl.lit(-1.0))
    with pytest.raises(SchemaValidationError) as caught:
        validate(AssetSnapshot, broken, origin="defillama")

    message = str(caught.value)
    assert "defillama" in message
    assert "AssetSnapshot" in message


def test_failing_check_reports_column_rule_and_offending_value(
    snapshots: pl.DataFrame,
) -> None:
    broken = snapshots.with_columns(total_supply=pl.lit(-42.0))
    with pytest.raises(SchemaValidationError) as caught:
        validate(AssetSnapshot, broken, origin="defillama")

    message = str(caught.value)
    assert "'total_supply'" in message
    assert "greater_than_or_equal_to(0)" in message
    assert "-42.0" in message


def test_missing_column_is_reported_by_name(snapshots: pl.DataFrame) -> None:
    # Without the pre-check this surfaces as a bare polars ColumnNotFoundError
    # raised from inside pandera's coercion pass, which names neither the schema
    # nor the adapter at fault.
    with pytest.raises(SchemaValidationError) as caught:
        validate(AssetSnapshot, snapshots.drop("total_supply"), origin="defillama")

    assert "'total_supply' is missing" in str(caught.value)


def test_timezone_naive_timestamp_is_rejected_rather_than_assumed_utc(
    snapshots: pl.DataFrame,
) -> None:
    # This is the important one. Pandera would relabel a naive column as UTC
    # without complaint, so a source reporting local time would silently shift
    # every observation window instead of failing.
    naive = snapshots.with_columns(pl.col("as_of").dt.replace_time_zone(None))
    with pytest.raises(SchemaValidationError) as caught:
        validate(AssetSnapshot, naive, origin="defillama")

    message = str(caught.value)
    assert "'as_of'" in message
    assert "timezone-naive" in message


def test_extra_column_is_rejected(snapshots: pl.DataFrame) -> None:
    # Provider-specific columns are the adapter's job to drop. Letting them
    # through would make the frames source-dependent, which defeats the point.
    extra = snapshots.with_columns(llama_protocol_slug=pl.lit("blackrock-buidl"))
    with pytest.raises(SchemaValidationError) as caught:
        validate(AssetSnapshot, extra, origin="defillama")

    assert "llama_protocol_slug" in str(caught.value)


def test_null_in_a_non_nullable_column_is_rejected(transfers: pl.DataFrame) -> None:
    broken = transfers.with_columns(amount=pl.lit(None, dtype=pl.Float64))
    with pytest.raises(SchemaValidationError) as caught:
        validate(TransferEvent, broken, origin="dune")

    assert "not_nullable" in str(caught.value)


def test_nulls_are_allowed_where_sources_genuinely_have_no_answer(
    snapshots: pl.DataFrame,
) -> None:
    # DeFiLlama publishes no holder counts. Forcing a number here would mean
    # inventing one.
    sparse = snapshots.with_columns(
        holder_count=pl.lit(None, dtype=pl.Int64),
        decimals=pl.lit(None, dtype=pl.Int64),
    )
    assert validate(AssetSnapshot, sparse, origin="defillama").height == 1


def test_unknown_transfer_kind_is_rejected(transfers: pl.DataFrame) -> None:
    # `kind` is a closed vocabulary. An adapter inventing "transfer" would have
    # its rows silently dropped by every mode filter downstream.
    broken = transfers.with_columns(kind=pl.lit("transfer"))
    with pytest.raises(SchemaValidationError) as caught:
        validate(TransferEvent, broken, origin="dune")

    message = str(caught.value)
    assert "'kind'" in message
    assert "isin" in message


def test_duplicate_transfer_is_rejected(transfers: pl.DataFrame) -> None:
    # The same (tx_hash, log_index) twice means paginated fetching overlapped.
    # Undetected, it would inflate every volume metric.
    with pytest.raises(SchemaValidationError) as caught:
        validate(TransferEvent, pl.concat([transfers, transfers]), origin="dune")

    assert "uniqueness" in str(caught.value)


def test_two_sources_may_report_the_same_asset_at_the_same_instant() -> None:
    # Uniqueness is per source. Reconciliation depends on being able to hold
    # both answers at once.
    both = pl.concat(
        [
            asset_snapshot_frame(),
            asset_snapshot_frame().with_columns(source=pl.lit("rwa_xyz")),
        ]
    )
    assert validate(AssetSnapshot, both, origin="test").height == 2


def test_malformed_asset_uid_is_rejected(holders: pl.DataFrame) -> None:
    broken = holders.with_columns(asset_uid=pl.lit("0xdeadbeef"))
    with pytest.raises(SchemaValidationError) as caught:
        validate(HolderBalance, broken, origin="dune")

    assert "'asset_uid'" in str(caught.value)


def test_uncoercible_value_is_reported_not_crashed(transfers: pl.DataFrame) -> None:
    broken = transfers.with_columns(amount=pl.lit("a lot"))
    with pytest.raises(SchemaValidationError) as caught:
        validate(TransferEvent, broken, origin="dune")

    assert "'amount'" in str(caught.value)


def test_several_problems_are_reported_in_one_pass(transfers: pl.DataFrame) -> None:
    # Fixing an adapter one error per run is miserable; lazy validation collects
    # everything wrong with the frame at once.
    broken = transfers.with_columns(amount=pl.lit(-1.0), kind=pl.lit("transfer"))
    with pytest.raises(SchemaValidationError) as caught:
        validate(TransferEvent, broken, origin="dune")

    assert len(caught.value.problems) >= 2


def test_declared_dtypes_are_enforced_on_the_returned_frame() -> None:
    # Coercion is allowed, but the frame handed to metrics must have the
    # declared types regardless of what the adapter produced.
    loose = transfer_event_frame().with_columns(pl.col("log_index").cast(pl.Int32))
    validated = validate(TransferEvent, loose, origin="dune")
    assert validated.schema["log_index"] == pl.Int64


def test_microsecond_precision_is_normalized() -> None:
    # Sources differ on time unit; concatenating a millisecond frame with a
    # microsecond one would otherwise fail far from the adapter that caused it.
    millis = holder_balance_frame().with_columns(
        pl.col("as_of").cast(pl.Datetime("ms", "UTC")),
    )
    validated = validate(HolderBalance, millis, origin="dune")
    assert validated.schema["as_of"] == pl.Datetime("us", "UTC")


def test_non_utc_timezone_is_converted_not_rejected() -> None:
    # An aware timestamp in another zone is unambiguous, so it is safe to
    # convert. Only the *unlabelled* case is an error.
    istanbul = asset_snapshot_frame().with_columns(
        pl.col("as_of").dt.convert_time_zone("Europe/Istanbul"),
    )
    validated = validate(AssetSnapshot, istanbul, origin="rwa_xyz")
    assert validated.schema["as_of"] == pl.Datetime("us", "UTC")
    assert validated["as_of"].item() == datetime(NOW.year, 7, 1, 12, 0, tzinfo=UTC)
