"""The interface every ingestion adapter implements.

Sources differ in what they can answer. DeFiLlama publishes prices and
protocol-level value but has no concept of an individual transfer; Dune has
transfer and holder data but does not know what an asset *is*. Rather than
pretend to a uniform interface and return empty frames for the parts a provider
cannot serve, each source declares its capabilities and raises a specific error
when asked for something outside them.

That distinction matters downstream: an empty transfer frame means "this asset
did not trade", which is a finding. A source that cannot see transfers at all
must not be able to produce that finding by accident.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    import polars as pl

    from rwa_liquidity.schema.asset import AssetRef

__all__ = [
    "Capability",
    "Source",
    "SourceError",
    "SourceFetchError",
    "UnsupportedCapabilityError",
]


class Capability(StrEnum):
    """A kind of fact a source is able to supply."""

    ASSET_SNAPSHOT = "asset_snapshot"
    TRANSFER_EVENT = "transfer_event"
    HOLDER_BALANCE = "holder_balance"


class SourceError(Exception):
    """Base class for every failure originating in an ingestion adapter."""


class UnsupportedCapabilityError(SourceError):
    """The source was asked for a kind of data it does not publish."""

    def __init__(self, source: str, capability: Capability) -> None:
        """Name both the source and what it was asked for."""
        self.source = source
        self.capability = capability
        super().__init__(
            f"{source} does not provide {capability.value} data. This is a property of "
            f"the provider, not a temporary failure; use a source that declares the "
            f"{capability.value} capability."
        )


class SourceFetchError(SourceError):
    """The provider was reachable but did not return usable data."""


class SourceTransportError(SourceFetchError):
    """The provider could not be reached, or failed in a way unrelated to the request.

    Separated from a plain `SourceFetchError` because callers legitimately react
    to a rejected request by reformulating it -- a log scan narrows its block
    range when a node refuses the query -- and that reaction is wrong when the
    request never arrived. A DNS failure says nothing about whether the range was
    acceptable, so treating it as a verdict on the request turns a network blip
    into an unbounded retry storm.
    """


class Source(ABC):
    """A provider adapter.

    Subclasses override only the fetch methods matching the capabilities they
    declare. The default implementations raise, so a mismatch between the
    declared capabilities and the implemented methods surfaces as a clear error
    rather than as silently missing data.
    """

    #: Short, stable identifier. Written into the `source` column of every frame
    #: this adapter produces, so changing it changes published provenance.
    #: Declared as a ClassVar so callers can read it off the class -- the CLI
    #: lists capabilities without constructing adapters, which would need keys.
    name: ClassVar[str]

    #: What this adapter can answer.
    capabilities: ClassVar[frozenset[Capability]]

    def supports(self, capability: Capability) -> bool:
        """Return whether this source can answer for `capability`."""
        return capability in self.capabilities

    def fetch_asset_snapshots(
        self,
        assets: Sequence[AssetRef],
        *,
        refresh: bool = False,
    ) -> pl.DataFrame:
        """Return an `AssetSnapshot` frame for `assets`.

        Args:
            assets: The assets to describe.
            refresh: Bypass the cache and refetch.

        Returns:
            A validated `AssetSnapshot` frame. Assets the provider does not know
            about are absent from the result rather than present with nulls.
        """
        raise UnsupportedCapabilityError(self.name, Capability.ASSET_SNAPSHOT)

    def fetch_transfers(
        self,
        asset: AssetRef,
        *,
        start: datetime,
        end: datetime,
        refresh: bool = False,
    ) -> pl.DataFrame:
        """Return a `TransferEvent` frame for `asset` over `[start, end)`.

        Args:
            asset: The asset to fetch transfers for.
            start: Inclusive start of the observation window.
            end: Exclusive end of the observation window.
            refresh: Bypass the cache and refetch.

        Returns:
            A validated `TransferEvent` frame, empty if the asset did not move.
        """
        raise UnsupportedCapabilityError(self.name, Capability.TRANSFER_EVENT)

    def fetch_holders(
        self,
        asset: AssetRef,
        *,
        as_of: datetime | None = None,
        refresh: bool = False,
    ) -> pl.DataFrame:
        """Return a `HolderBalance` frame for `asset`.

        Args:
            asset: The asset to fetch balances for.
            as_of: The moment to snapshot. Defaults to the latest available.
            refresh: Bypass the cache and refetch.

        Returns:
            A validated `HolderBalance` frame. May be truncated by the provider;
            metrics compare its height against the reported holder count.
        """
        raise UnsupportedCapabilityError(self.name, Capability.HOLDER_BALANCE)

    @abstractmethod
    def close(self) -> None:
        """Release network resources held by the adapter."""
