# Sample dataset

**This data is synthetic. It was constructed, not observed.**

No keyless source publishes transfer-level or holder-level data, so no real
dataset can demonstrate this package's metrics until someone supplies a Dune API
key. Constructing one is the only way a stranger can clone the repository and
see real output in two commands.

Synthetic data is honest as long as nobody can mistake it for observed data, so
it is labelled here, in the project README, in `build.py`, and in the CLI's own
output every time it runs.

The files are CSV rather than parquet on purpose: you can open them on GitHub
and check every number without installing anything.

## What each asset is shaped to demonstrate

| Asset | Supply | Reported holders | Point |
|---|---|---|---|
| `SYNTH-TBILL` | 500,000,000 | 8 | A fund that only mints and redeems |
| `SYNTH-GOLD` | 1,000,000 | 12 | A genuinely traded token |
| `SYNTH-CREDIT` | 100,000 | 40 | Thin, concentrated, and only partly observed |

### SYNTH-TBILL — the case the package exists for

Four issuances totalling 280m and two redemptions totalling 50m. **Nothing at
all traded between holders.**

| | `--mode all` | `--mode secondary_only` |
|---|---|---|
| Turnover | 0.6600 | **0.0000** |
| Dormancy | 3.0% | **100.0%** |

A naive implementation counts the issuance as trading and reports a fund with
two-thirds of its supply turning over in a month. The honest reading is that it
has no secondary market at all and every holder is dormant. Same data, same
window, opposite conclusion.

### SYNTH-GOLD — a working market

Ten trades between holders totalling 250,000, alongside 80,000 of issuance and
10,000 of redemption. Turnover reads 0.34 raw against 0.25 secondary: the two
differ, but neither is absurd, which is what an asset with a real secondary
market looks like.

### SYNTH-CREDIT — thin, and only partly visible

Two small trades on a 100,000 supply, so secondary turnover is 0.008. It also
exercises two of the package's caveats:

* One of its four transfers is `unclassified`, so any narrow mode reports the
  volume as a lower bound rather than a measurement.
* Its holder list contains 6 addresses against a reported holder count of 40.
  Concentration computed from 15% coverage is biased downward, and the metrics
  say so instead of presenting the figure as final.

### A deliberate cross-source disagreement

`SYNTH-TBILL` is described by two sources: `sample_registry` reports a supply of
500m, `sample_protocol_feed` reports 560m. They disagree by 10.7%.

This mirrors the real BUIDL case, where DeFiLlama's protocol figure covers two
share classes while rwa.xyz reports on a single contract. Neither source is
wrong. The reconcile layer surfaces the gap rather than picking a winner, and
`report --demo` prints it under the table.

## Rebuilding

```bash
uv run python data/sample/build.py
```

`build.py` is the specification for this data. Every number above is derived
from it, and the tests in `tests/test_demo.py` assert the properties this file
claims.
