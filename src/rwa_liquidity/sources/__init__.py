"""Ingestion adapters, one module per data provider.

Every adapter implements `Source` and returns frames conforming to the
normalized schemas in `rwa_liquidity.schema`. Provider-specific quirks -- field
names, pagination, rate limits, unit conventions, chain aliases -- are resolved
here and never leak past this boundary. Adding a fourth provider must not require
touching `rwa_liquidity.metrics`.

Sources declare what they can answer rather than implementing every method and
returning nothing for the parts they cannot serve. An empty transfer frame means
"this asset did not trade", which is a finding; a source that cannot see
transfers at all must not be able to produce that finding by accident.
"""

from rwa_liquidity.sources.base import (
    Capability,
    Source,
    SourceError,
    SourceFetchError,
    SourceTransportError,
    UnsupportedCapabilityError,
)
from rwa_liquidity.sources.classify import classify_transfers
from rwa_liquidity.sources.defillama import (
    DeFiLlamaPricesSource,
    DeFiLlamaProtocolTvlSource,
)
from rwa_liquidity.sources.dune import HOLDER_COLUMNS, TRANSFER_COLUMNS, DuneSource
from rwa_liquidity.sources.evm_rpc import (
    DEFAULT_RPC_URL,
    TRANSFER_TOPIC,
    EvmRpcSource,
    IssuanceProfile,
)
from rwa_liquidity.sources.http import CachedJSONClient, JSONResponse
from rwa_liquidity.sources.known_addresses import (
    KnownAddressesEntry,
    KnownAddressesError,
    excluded_contracts,
    issuer_addresses,
    load_known_addresses,
)
from rwa_liquidity.sources.registry import (
    RegistryEntry,
    RegistryError,
    load_defillama_registry,
)
from rwa_liquidity.sources.rwa_xyz import RwaXyzSource

__all__ = [
    "DEFAULT_RPC_URL",
    "HOLDER_COLUMNS",
    "TRANSFER_COLUMNS",
    "TRANSFER_TOPIC",
    "CachedJSONClient",
    "Capability",
    "DeFiLlamaPricesSource",
    "DeFiLlamaProtocolTvlSource",
    "DuneSource",
    "EvmRpcSource",
    "IssuanceProfile",
    "JSONResponse",
    "KnownAddressesEntry",
    "KnownAddressesError",
    "RegistryEntry",
    "RegistryError",
    "RwaXyzSource",
    "Source",
    "SourceError",
    "SourceFetchError",
    "SourceTransportError",
    "UnsupportedCapabilityError",
    "classify_transfers",
    "excluded_contracts",
    "issuer_addresses",
    "load_defillama_registry",
    "load_known_addresses",
]
