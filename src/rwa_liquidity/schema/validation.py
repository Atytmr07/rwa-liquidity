"""The validation boundary between ingestion and analysis.

Every adapter passes its output through `validate` before returning it. Two
things matter here beyond calling pandera:

1. **Errors must name the provider.** A metric that fails three layers deep on a
   null it never expected is a bad debugging experience. Validating at the
   boundary means every schema violation is attributed to the source that
   produced it, in a message that says which column, which check, how many rows,
   and what the offending values looked like.

2. **Pandera's polars backend has two sharp edges that have to be blunted.**
   With `coerce=True`, a missing column surfaces as a raw
   `polars.exceptions.ColumnNotFoundError` from deep inside the coercion pass
   rather than as a schema error, and a timezone-naive timestamp column is
   silently relabelled UTC. The second is the dangerous one: every metric in
   this package is defined over an observation window, so a source that reports
   local time would produce quietly wrong windows rather than an error. Both are
   pre-checked here, before pandera runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import pandera.errors
import pandera.polars as pa
import polars as pl

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["SchemaValidationError", "polars_schema", "validate"]

# How many offending values to quote per problem. Enough to see a pattern,
# few enough that the message stays readable in a terminal.
_MAX_EXAMPLES: Final = 3


class SchemaValidationError(Exception):
    """A frame did not conform to its normalized schema.

    Attributes:
        frame_name: The schema the frame was checked against.
        origin: Who produced the frame, usually an adapter name.
        problems: One human-readable line per distinct violation.
    """

    def __init__(self, *, frame_name: str, origin: str, problems: list[str]) -> None:
        """Build the error and render its multi-line message."""
        self.frame_name = frame_name
        self.origin = origin
        self.problems = problems
        count = len(problems)
        header = (
            f"{origin} produced an invalid `{frame_name}` frame "
            f"({count} problem{'s' if count != 1 else ''}):"
        )
        super().__init__("\n".join([header, *(f"  - {problem}" for problem in problems)]))


def polars_schema(model: type[pa.DataFrameModel]) -> Mapping[str, pl.DataType]:
    """Return the polars dtype each column of `model` is declared as.

    Adapters use this to build their output frames, so an empty result and a
    populated one have identical dtypes and a schema change cannot leave an
    adapter constructing last week's columns.
    """
    schema = model.to_schema()
    dtypes: dict[str, pl.DataType] = {}
    for name, column in schema.columns.items():
        # pandera wraps the polars dtype in its own engine type; `.type` is the
        # underlying polars dtype. Fall back for any dtype that is already raw.
        dtypes[str(name)] = getattr(column.dtype, "type", column.dtype)
    return dtypes


def _check_columns_present(frame: pl.DataFrame, expected: Mapping[str, pl.DataType]) -> list[str]:
    """Report columns the schema requires that the frame does not have."""
    missing = [name for name in expected if name not in frame.columns]
    if not missing:
        return []
    return [
        f"required column {name!r} is missing (frame has: "
        f"{', '.join(repr(column) for column in frame.columns)})"
        for name in missing
    ]


def _check_timestamps_are_aware(
    frame: pl.DataFrame, expected: Mapping[str, pl.DataType]
) -> list[str]:
    """Report timestamp columns that arrived without a timezone.

    Pandera would coerce these to UTC without complaint. Every metric here is
    defined over an observation window, so accepting an unlabelled timestamp
    means accepting a window that may be wrong by hours with nothing to show for
    it. The adapter has to say what the timezone is.
    """
    problems: list[str] = []
    for name, dtype in expected.items():
        if not (isinstance(dtype, pl.Datetime) and dtype.time_zone is not None):
            continue
        actual = frame.schema.get(name)
        if isinstance(actual, pl.Datetime) and actual.time_zone is None:
            problems.append(
                f"column {name!r} is timezone-naive. Observation windows depend on "
                f"absolute time, so the adapter must attach a timezone rather than "
                f"leaving it to be assumed"
            )
    return problems


def _describe_failures(failure_cases: pl.DataFrame) -> list[str]:
    """Turn pandera's failure-case table into one readable line per violation."""
    grouped = (
        failure_cases.group_by(["schema_context", "column", "check"], maintain_order=True)
        .agg(
            pl.len().alias("row_count"),
            pl.col("failure_case").head(_MAX_EXAMPLES).alias("examples"),
        )
        .sort("column", "check")
    )

    problems: list[str] = []
    for row in grouped.iter_rows(named=True):
        column = row["column"]
        check = row["check"]
        rows = int(row["row_count"])
        examples = ", ".join(str(value) for value in row["examples"])

        if check == "column_in_schema":
            problems.append(
                f"unexpected column {examples!r} is not part of the schema; the "
                f"adapter must drop provider-specific columns at the boundary"
            )
        elif check.startswith("multiple_fields_uniqueness"):
            problems.append(
                f"{rows} rows violate the uniqueness constraint; the same record "
                f"appears more than once (e.g. {examples})"
            )
        elif check.startswith("coerce_dtype"):
            problems.append(
                f"column {column!r} holds values that cannot be converted to its "
                f"declared type (e.g. {examples})"
            )
        else:
            plural = "row" if rows == 1 else "rows"
            problems.append(
                f"column {column!r} failed {check} on {rows} {plural} (e.g. {examples})"
            )
    return problems


def validate(
    model: type[pa.DataFrameModel],
    frame: pl.DataFrame,
    *,
    origin: str,
) -> pl.DataFrame:
    """Validate `frame` against `model`, raising a message a human can act on.

    Args:
        model: The normalized schema to check against.
        frame: The candidate frame, typically fresh out of an adapter.
        origin: Who produced the frame. Appears in the error message, so it
            should be something like `"defillama"` rather than `"unknown"`.

    Returns:
        The validated frame, with dtypes coerced to the schema's declaration.

    Raises:
        SchemaValidationError: If the frame violates the schema in any way.
    """
    frame_name = model.__name__
    expected = polars_schema(model)

    # Run the pre-checks first and bail before pandera, whose failure modes for
    # these two cases are unhelpful (see the module docstring).
    problems = _check_columns_present(frame, expected)
    problems += _check_timestamps_are_aware(frame, expected)
    if problems:
        raise SchemaValidationError(frame_name=frame_name, origin=origin, problems=problems)

    try:
        # lazy=True collects every violation instead of stopping at the first,
        # so one run reports everything wrong with the adapter's output.
        validated = model.validate(frame, lazy=True)
    except pandera.errors.SchemaErrors as error:
        raise SchemaValidationError(
            frame_name=frame_name,
            origin=origin,
            problems=_describe_failures(error.failure_cases),
        ) from error
    except pl.exceptions.PolarsError as error:
        # A polars error escaping pandera means the frame is malformed in a way
        # the pre-checks did not anticipate. Surface it with attribution rather
        # than letting a bare engine error propagate.
        raise SchemaValidationError(
            frame_name=frame_name,
            origin=origin,
            problems=[f"polars rejected the frame: {error}"],
        ) from error

    return pl.DataFrame(validated)
