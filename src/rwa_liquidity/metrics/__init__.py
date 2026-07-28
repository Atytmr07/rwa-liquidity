"""Liquidity metric implementations, one module per family.

Metrics consume normalized frames and know nothing about where the data came
from. Each metric returns its value together with a provenance record: source,
observation window, number of underlying records, and any exclusions applied.

Volume-based metrics are computable in three modes -- `all`, `secondary_only`,
and `primary_only` -- because primary issuance (mint and redeem) is not
liquidity. `secondary_only` is the default; see `docs/methodology.md`.
"""
