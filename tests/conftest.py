"""Shared fixtures.

The frame builders here produce the minimal *valid* instance of each normalized
schema. Tests then break exactly one thing about a frame, which keeps it obvious
which invariant any given test is actually about.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import polars as pl
import pytest

from rwa_liquidity.schema.types import TransferKind

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

# A fixed instant, so nothing in the suite depends on the wall clock.
NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)

# BUIDL on Ethereum. A real contract address is used so that anyone reading the
# fixtures can check what the asset is; no network call is ever made with it.
BUIDL = "ethereum:0x7712c34205737192402172409a8f7ccef8aa2aec"

# Dtypes are written as instances rather than classes so the fixture builders
# state exactly what the adapters are expected to produce, including the time
# unit and zone that a bare `pl.Datetime` would leave open.
TIMESTAMP = pl.Datetime("us", "UTC")
TEXT = pl.String()
INTEGER = pl.Int64()
DECIMAL = pl.Float64()


def _frame(columns: Mapping[str, list[Any]], schema: Mapping[str, pl.DataType]) -> pl.DataFrame:
    return pl.DataFrame(dict(columns), schema=dict(schema))


def asset_snapshot_frame() -> pl.DataFrame:
    """Return a valid single-row `AssetSnapshot` frame."""
    return _frame(
        {
            "asset_uid": [BUIDL],
            "source": ["defillama"],
            "retrieved_at": [NOW],
            "as_of": [NOW],
            "symbol": ["BUIDL"],
            "name": ["BlackRock USD Institutional Digital Liquidity Fund"],
            "decimals": [6],
            "total_supply": [1_000_000.0],
            "market_value_usd": [1_000_000.0],
            "price_usd": [1.0],
            "holder_count": [75],
        },
        {
            "asset_uid": TEXT,
            "source": TEXT,
            "retrieved_at": TIMESTAMP,
            "as_of": TIMESTAMP,
            "symbol": TEXT,
            "name": TEXT,
            "decimals": INTEGER,
            "total_supply": DECIMAL,
            "market_value_usd": DECIMAL,
            "price_usd": DECIMAL,
            "holder_count": INTEGER,
        },
    )


def transfer_event_frame() -> pl.DataFrame:
    """Return a valid two-row `TransferEvent` frame: one mint, one secondary."""
    return _frame(
        {
            "asset_uid": [BUIDL, BUIDL],
            "source": ["dune", "dune"],
            "retrieved_at": [NOW, NOW],
            "block_time": [NOW, NOW],
            "tx_hash": ["0xaa", "0xbb"],
            "log_index": [0, 1],
            "from_address": ["0x" + "0" * 40, "0x" + "1" * 40],
            "to_address": ["0x" + "1" * 40, "0x" + "2" * 40],
            "amount": [500.0, 125.0],
            "amount_usd": [500.0, 125.0],
            "kind": [TransferKind.MINT.value, TransferKind.SECONDARY.value],
        },
        {
            "asset_uid": TEXT,
            "source": TEXT,
            "retrieved_at": TIMESTAMP,
            "block_time": TIMESTAMP,
            "tx_hash": TEXT,
            "log_index": INTEGER,
            "from_address": TEXT,
            "to_address": TEXT,
            "amount": DECIMAL,
            "amount_usd": DECIMAL,
            "kind": TEXT,
        },
    )


def holder_balance_frame() -> pl.DataFrame:
    """Return a valid two-row `HolderBalance` frame."""
    return _frame(
        {
            "asset_uid": [BUIDL, BUIDL],
            "source": ["dune", "dune"],
            "retrieved_at": [NOW, NOW],
            "as_of": [NOW, NOW],
            "address": ["0x" + "1" * 40, "0x" + "2" * 40],
            "balance": [750.0, 250.0],
            "balance_usd": [750.0, 250.0],
        },
        {
            "asset_uid": TEXT,
            "source": TEXT,
            "retrieved_at": TIMESTAMP,
            "as_of": TIMESTAMP,
            "address": TEXT,
            "balance": DECIMAL,
            "balance_usd": DECIMAL,
        },
    )


@pytest.fixture
def snapshots() -> pl.DataFrame:
    return asset_snapshot_frame()


@pytest.fixture
def transfers() -> pl.DataFrame:
    return transfer_event_frame()


@pytest.fixture
def holders() -> pl.DataFrame:
    return holder_balance_frame()


@pytest.fixture
def cache_root(tmp_path: Path) -> Path:
    return tmp_path / "cache"
