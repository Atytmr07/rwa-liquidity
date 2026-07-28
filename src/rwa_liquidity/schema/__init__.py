"""The normalized data model and its pandera schemas.

This is the contract between ingestion and analysis. Data is validated on the
way out of every adapter, so any schema violation is attributed to the provider
that produced it rather than surfacing as a confusing failure inside a metric.
"""
