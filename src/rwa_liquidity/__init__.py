"""Liquidity measurement for tokenized real-world asset (RWA) markets.

The package ingests market data from several providers, normalizes it to one
schema, and computes a documented set of liquidity metrics. Every metric carries
a provenance record so that any published number can be traced back to the raw
records it was computed from.

See `docs/methodology.md` for metric definitions and their caveats.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    # Read the version from installed package metadata rather than duplicating
    # the literal here, so pyproject.toml stays the single source of truth.
    __version__ = version("rwa-liquidity")
except PackageNotFoundError:  # pragma: no cover
    # Only reachable when imported from a source tree that was never installed.
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
