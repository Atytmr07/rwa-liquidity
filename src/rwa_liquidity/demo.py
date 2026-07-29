"""Loading the committed sample dataset.

The dataset is synthetic and is labelled as such wherever it is used. See
`data/sample/README.md` for what each asset is shaped to demonstrate and
`data/sample/build.py` for exactly how the numbers were constructed.

It is loaded through the same `validate` boundary as any adapter's output, so
the demo exercises the real ingestion path rather than a shortcut around it. If
a schema change broke the sample data, the demo would fail like a source would.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final

import polars as pl

from rwa_liquidity.metrics.base import Window
from rwa_liquidity.schema.frames import AssetSnapshot, HolderBalance, TransferEvent
from rwa_liquidity.schema.validation import polars_schema, validate

if TYPE_CHECKING:
    import pandera.polars as pa

__all__ = ["DEMO_LABEL", "SAMPLE_DIR", "DemoDataset", "load_demo_dataset"]

#: Shown wherever demo output is produced. The dataset is honest only as long as
#: nobody can mistake it for observed data.
DEMO_LABEL: Final = "SYNTHETIC SAMPLE DATA -- constructed, not observed"

#: The dataset lives in the repository rather than in the wheel: it is a
#: demonstration for people reading the source, not a runtime asset.
SAMPLE_DIR: Final = Path(__file__).resolve().parents[2] / "data" / "sample"

#: The window the sample data was built around.
DEMO_WINDOW: Final = Window(
    start=datetime(2026, 6, 1, tzinfo=UTC), end=datetime(2026, 7, 1, tzinfo=UTC)
)

#: What `datetime.isoformat()` produces for an aware UTC instant, with an
#: optional fractional part.
_ISO_WITH_OFFSET: Final = "%Y-%m-%dT%H:%M:%S%.f%:z"

_FILES: Final = {
    "snapshots": ("asset_snapshots.csv", AssetSnapshot),
    "transfers": ("transfer_events.csv", TransferEvent),
    "holders": ("holder_balances.csv", HolderBalance),
}


class DemoDataUnavailableError(Exception):
    """The sample dataset is not on disk."""


@dataclass(frozen=True, slots=True)
class DemoDataset:
    """The three sample frames plus the window they were built for."""

    snapshots: pl.DataFrame
    transfers: pl.DataFrame
    holders: pl.DataFrame
    window: Window

    @property
    def asset_uids(self) -> list[str]:
        """Return the assets present, in a stable order."""
        return sorted(self.snapshots["asset_uid"].unique().to_list())


def _read(path: Path, model: type[pa.DataFrameModel]) -> pl.DataFrame:
    """Read one sample CSV and validate it as if a source had produced it."""
    if not path.is_file():
        raise DemoDataUnavailableError(
            f"{path} is missing. The sample dataset ships with the repository; "
            f"rebuild it with `uv run python data/sample/build.py`."
        )

    schema = polars_schema(model)
    # CSV has no types, so the target dtypes are declared up front rather than
    # inferred. `schema_overrides` maps by column name; `schema` maps by
    # position, which would silently mis-assign types when the file's column
    # order differs from the model's. Timestamps are read as strings and
    # converted explicitly below: letting polars guess would risk a naive
    # column, which the validator then rejects.
    read_schema = {
        name: (pl.String() if isinstance(dtype, pl.Datetime) else dtype)
        for name, dtype in schema.items()
    }
    frame = pl.read_csv(path, schema_overrides=read_schema)
    timestamps = [name for name, dtype in schema.items() if isinstance(dtype, pl.Datetime)]
    if timestamps:
        # The format is stated rather than inferred. polars refuses to infer a
        # format for offset-bearing strings, and an inferred one could quietly
        # differ between polars versions -- not a property to build a
        # reproducible dataset on.
        frame = frame.with_columns(
            pl.col(name)
            .str.to_datetime(format=_ISO_WITH_OFFSET, time_unit="us")
            .dt.convert_time_zone("UTC")
            for name in timestamps
        )
    return validate(model, frame, origin="sample_data")


def load_demo_dataset(directory: Path | None = None) -> DemoDataset:
    """Load and validate the committed sample dataset.

    Args:
        directory: Where to read from. Defaults to `data/sample/`.

    Returns:
        The three validated frames and the window they describe.

    Raises:
        DemoDataUnavailableError: If a file is missing.
        SchemaValidationError: If the sample data no longer matches the schema,
            which means a schema change went in without the sample being updated.
    """
    root = directory if directory is not None else SAMPLE_DIR
    frames = {key: _read(root / name, model) for key, (name, model) in _FILES.items()}
    return DemoDataset(
        snapshots=frames["snapshots"],
        transfers=frames["transfers"],
        holders=frames["holders"],
        window=DEMO_WINDOW,
    )
