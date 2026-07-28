"""Pandera schemas for the three normalized frames.

The normalized model is deliberately three frames rather than one. The sources
supply three different shapes of fact -- what an asset was worth at a moment,
what moved between addresses, and who held what -- and flattening them into a
single table would mean a schema that is mostly null and a set of checks that
cannot say anything useful about any particular row.

All three carry the same envelope (`asset_uid`, `source`, `retrieved_at`), which
is what makes cross-source reconciliation and provenance possible.

Unit conventions, which every adapter is responsible for honouring:

* Token amounts are **human-scaled**, i.e. already divided by the token's
  `decimals`. They are stored as `Float64`, which is exact to about 15
  significant digits. That is far beyond the precision any liquidity ratio can
  meaningfully carry, but it means this package must not be used for wei-level
  accounting.
* All timestamps are timezone-aware UTC. See `validation.py` for why this is
  enforced rather than assumed.
"""

from __future__ import annotations

from typing import Annotated, ClassVar

import pandera.polars as pa
import polars as pl

from rwa_liquidity.schema.types import TransferKind

__all__ = ["AssetSnapshot", "HolderBalance", "TransferEvent"]

# Microsecond-precision UTC. Fixing the time unit as well as the zone means two
# adapters cannot produce frames that look identical but fail to concatenate.
Timestamp = Annotated[pl.Datetime, "us", "UTC"]

# `chain:address`, with neither component containing a colon or whitespace.
# Mirrors the invariants that `AssetRef` enforces in Python, so a frame that was
# not built through `AssetRef` still cannot carry a malformed key.
_ASSET_UID_PATTERN = r"^[^:\s]+:[^:\s]+$"

# An 18-decimal token is the common case; 36 leaves generous headroom while
# still rejecting a value that is obviously a different field misread.
_MAX_TOKEN_DECIMALS = 36


class _Envelope(pa.DataFrameModel):
    """Fields every normalized frame carries, whatever its shape.

    `retrieved_at` is when we asked the provider, which is not the same as the
    time the data describes. Keeping both is what allows a result to be
    reproduced later, after the upstream figures have moved on.
    """

    asset_uid: str = pa.Field(str_matches=_ASSET_UID_PATTERN)
    source: str = pa.Field(str_length={"min_value": 1})
    retrieved_at: Timestamp


class AssetSnapshot(_Envelope):
    """What one source said about one asset at one moment.

    Almost every field is nullable because the sources genuinely disagree about
    what they publish: DeFiLlama has no holder counts, and on-chain data has no
    concept of an issuer's stated market value. Making them non-nullable would
    force adapters to invent numbers, which is the opposite of what this package
    is for.
    """

    as_of: Timestamp
    symbol: str = pa.Field(nullable=True)
    name: str = pa.Field(nullable=True)
    decimals: int = pa.Field(nullable=True, ge=0, le=_MAX_TOKEN_DECIMALS)
    total_supply: float = pa.Field(nullable=True, ge=0)
    market_value_usd: float = pa.Field(nullable=True, ge=0)
    price_usd: float = pa.Field(nullable=True, ge=0)
    holder_count: int = pa.Field(nullable=True, ge=0)

    class Config:
        """Schema behaviour."""

        strict = True
        coerce = True
        # One source may not report the same asset twice for the same instant.
        # Two different sources may, and reconciling that is the point.
        unique: ClassVar[list[str]] = ["asset_uid", "source", "as_of"]


class TransferEvent(pa.DataFrameModel):
    """One token movement, classified against the primary market.

    `kind` is assigned by the adapter, which is the only layer that knows the
    issuer addresses for a given asset. Metrics filter on it and never re-derive
    it, so the classification rule lives in exactly one place per source.
    """

    asset_uid: str = pa.Field(str_matches=_ASSET_UID_PATTERN)
    source: str = pa.Field(str_length={"min_value": 1})
    retrieved_at: Timestamp
    block_time: Timestamp
    tx_hash: str = pa.Field(str_length={"min_value": 1})
    # Distinguishes several transfers of the same asset in one transaction,
    # which is routine: a single swap emits at least two Transfer events.
    log_index: int = pa.Field(ge=0)
    from_address: str = pa.Field(str_length={"min_value": 1})
    to_address: str = pa.Field(str_length={"min_value": 1})
    amount: float = pa.Field(ge=0)
    amount_usd: float = pa.Field(nullable=True, ge=0)
    kind: str = pa.Field(isin=[kind.value for kind in TransferKind])

    class Config:
        """Schema behaviour."""

        strict = True
        coerce = True
        unique: ClassVar[list[str]] = ["asset_uid", "source", "tx_hash", "log_index"]


class HolderBalance(_Envelope):
    """One address's balance of one asset at one moment.

    A holder snapshot is frequently truncated by the provider to the top N
    addresses. The frame itself cannot express that, so metrics that depend on
    the full distribution compare the row count against `AssetSnapshot.
    holder_count` and report the coverage in their provenance record.
    """

    as_of: Timestamp
    address: str = pa.Field(str_length={"min_value": 1})
    balance: float = pa.Field(ge=0)
    balance_usd: float = pa.Field(nullable=True, ge=0)

    class Config:
        """Schema behaviour."""

        strict = True
        coerce = True
        unique: ClassVar[list[str]] = ["asset_uid", "source", "as_of", "address"]
