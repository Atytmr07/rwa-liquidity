"""Cross-source variance reporting.

When two providers report different figures for the same asset, the package
reports the disagreement rather than silently choosing a winner. Which source is
correct is a research question, not something a library should decide.

A disagreement is not automatically a bug in either source. The clearest case in
this package is BUIDL: DeFiLlama's protocol TVL covers two share classes, so it
legitimately exceeds the value of the single contract rwa.xyz reports on. The
report exists so that gap is visible and explainable, not so it can be closed.
"""

from rwa_liquidity.reconcile.variance import (
    DEFAULT_STALENESS,
    DEFAULT_TOLERANCE,
    RECONCILABLE_FIELDS,
    Disagreement,
    ReconciliationReport,
    reconcile_snapshots,
)

__all__ = [
    "DEFAULT_STALENESS",
    "DEFAULT_TOLERANCE",
    "RECONCILABLE_FIELDS",
    "Disagreement",
    "ReconciliationReport",
    "reconcile_snapshots",
]
