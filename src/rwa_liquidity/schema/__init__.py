"""The normalized data model and its pandera schemas.

This is the contract between ingestion and analysis. Data is validated on the
way out of every adapter, so any schema violation is attributed to the provider
that produced it rather than surfacing as a confusing failure inside a metric.

The model is three frames sharing one envelope:

* `AssetSnapshot` -- what a source said an asset was worth at a moment.
* `TransferEvent` -- one token movement, classified against the primary market.
* `HolderBalance` -- one address's balance at a moment.

Assets are identified by `AssetRef`, a `chain:address` pair, because a contract
address is the only identifier every on-chain source agrees on.
"""

from rwa_liquidity.schema.asset import AssetRef, InvalidAssetRefError, canonicalize_address
from rwa_liquidity.schema.frames import AssetSnapshot, HolderBalance, TransferEvent
from rwa_liquidity.schema.types import (
    BURN_ADDRESSES,
    ZERO_ADDRESS,
    Denomination,
    TransferKind,
    VolumeMode,
)
from rwa_liquidity.schema.validation import SchemaValidationError, validate

__all__ = [
    "BURN_ADDRESSES",
    "ZERO_ADDRESS",
    "AssetRef",
    "AssetSnapshot",
    "Denomination",
    "HolderBalance",
    "InvalidAssetRefError",
    "SchemaValidationError",
    "TransferEvent",
    "TransferKind",
    "VolumeMode",
    "canonicalize_address",
    "validate",
]
