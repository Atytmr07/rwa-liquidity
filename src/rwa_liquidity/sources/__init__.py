"""Ingestion adapters, one module per data provider.

Every adapter implements the same protocol and returns frames conforming to the
normalized schemas in `rwa_liquidity.schema`. Provider-specific quirks -- field
names, pagination, rate limits, unit conventions -- are resolved here and never
leak past this boundary. Adding a fourth provider must not require touching
`rwa_liquidity.metrics`.
"""
