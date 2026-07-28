"""Liquidity metric implementations, one module per family.

Metrics consume normalized frames and know nothing about where the data came
from. Each returns a `MetricResult`: the value together with a provenance record
naming the sources, the observation window, the number of underlying records,
what was excluded, and what is doubtful about the answer.

Two conventions hold throughout:

* **`None` means undefined, never zero.** A turnover ratio of `0.0` says an
  asset with supply did not trade. `None` says we could not tell. Collapsing
  them would put a fabricated number in a table.
* **`secondary_only` is the default mode** wherever transfers are counted,
  including the participation metrics. An address that received a mint and never
  traded is dormant.
"""

from rwa_liquidity.metrics.base import (
    DEFAULT_WINDOW_DAYS,
    MetricInputError,
    MetricResult,
    Provenance,
    Window,
)
from rwa_liquidity.metrics.concentration import (
    DEFAULT_TOP_N,
    HHI_SCALE,
    holder_hhi,
    top_holder_share,
)
from rwa_liquidity.metrics.participation import active_holder_ratio, dormancy
from rwa_liquidity.metrics.volume import (
    total_volume,
    turnover_ratio,
    volume_per_active_address,
)

__all__ = [
    "DEFAULT_TOP_N",
    "DEFAULT_WINDOW_DAYS",
    "HHI_SCALE",
    "MetricInputError",
    "MetricResult",
    "Provenance",
    "Window",
    "active_holder_ratio",
    "dormancy",
    "holder_hhi",
    "top_holder_share",
    "total_volume",
    "turnover_ratio",
    "volume_per_active_address",
]
