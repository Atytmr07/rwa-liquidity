# rwa-liquidity

Measure liquidity in tokenized real-world asset (RWA) markets.

Tokenized asset data is scattered across providers that disagree on schemas and
definitions. Anyone asking "how liquid is this tokenized asset, actually?" ends
up rewriting the same ingestion and metric code. This package standardizes that:
it ingests from multiple sources, normalizes to one schema, and computes a
documented set of liquidity metrics whose outputs are reproducible and traceable
back to the raw records they came from.

## What it found

Measured against Ethereum mainnet with no API key, 30 days to 2026-07-30:

Eleven tokenized real-world assets, selected by a reproducible on-chain procedure
rather than by hand. **Four of the ten measurable ones recorded zero
holder-to-holder transfers in 30 days.** One of those, ZTLN, has $150m
outstanding, two holders, and no trading in its entire history.

| BlackRock BUIDL — $224.8M, **59 holders** | Counting all transfers | Counting only secondary trades |
|---|---|---|
| Turnover | 0.2015 | **0.0187** |
| Dormancy | 3.0% | **96.2%** |

731 transfers, of which **696 were issuance and 32 were actual trading**. Raw
transfer volume overstates this fund's secondary liquidity by **10.8x** — and the
factor is asset-specific, between 1x and 11x across the set, so it cannot be
corrected with a scalar.

Eight of the ten exceed an HHI of 2,500, the threshold the 2010 US Horizontal
Merger Guidelines call highly concentrated (1,800 under the 2023 revision --
the same eight clear that bar too). Six exceed 5,000.

Over **six consecutive 30-day windows**, four of the ten recorded no secondary
trading in any window, two rose, four fell, and top-10 concentration moved by
less than a percentage point for seven of nine. Tokenization did not broaden
ownership on this sample.

Full write-up, including the assets the method cannot measure and why, in
**[`docs/findings.md`](docs/findings.md)**.

## Try it in two commands

No API keys, no configuration.

```bash
uv sync
```

```bash
uv run rwa-liquidity report
```

That measures real assets on-chain by replaying each token's full transfer
history. The first run takes **on the order of an hour** for the whole registry
and is cached afterwards, so later runs are near-instant; a single asset is a
minute or two. For an instant run against the committed sample dataset:

```bash
uv run rwa-liquidity report --demo
```

```
SYNTHETIC SAMPLE DATA -- constructed, not observed

mode = secondary_only    window = [2026-06-01T00:00:00+00:00, 2026-07-01T00:00:00+00:00)
┌──────────────┬──────────┬──────────┬──────────┬──────────┬───────┬──────────┐
│ Asset        │ Turnover │  holders │     addr │    share │   HHI │ Dormancy │
├──────────────┼──────────┼──────────┼──────────┼──────────┼───────┼──────────┤
│ SYNTH-TBILL  │   0.0000 │     0.0% │      n/a │   100.0% │ 2,586 │   100.0% │
│ SYNTH-GOLD   │   0.2500 │    83.3% │   25,000 │    95.0% │ 1,086 │     5.0% │
│ SYNTH-CREDIT │   0.0080 │     7.5% │      267 │    98.0% │ 3,586 │    13.0% │
└──────────────┴──────────┴──────────┴──────────┴──────────┴───────┴──────────┘
```

Add `--out metrics.csv`, `--out table.tex`, or `--mode all` to see the same data
read a different way. Two more commands:

```bash
uv run rwa-liquidity trend --metric turnover_ratio
```

```bash
uv run rwa-liquidity issuance
```

`trend` measures consecutive windows with supply and holders reconstructed at
each window's end. `issuance` checks, per asset, whether the primary/secondary
split can actually see how that token is issued — the assumption the whole
method rests on.

## The thing this gets right

**Primary issuance is not liquidity.**

Every movement of an ERC-20 token emits the same `Transfer` event, but three
economically different things hide behind it: a fund minting tokens to an
investor, an investor redeeming them, and two investors trading with each other.
Only the third is a secondary market.

A tokenized fund that only mints and redeems has no secondary market however
large its raw transfer volume looks, because its investors cannot trade with
each other, only with the issuer. Most implementations add all three together.
Run the demo above with `--mode all` and watch the first row:

| `SYNTH-TBILL` | `--mode all` | `--mode secondary_only` |
|---|---|---|
| Turnover | 0.6600 | **0.0000** |
| Dormancy | 3.0% | **100.0%** |

Same data, same window, opposite conclusion. Every volume-based metric is
computable in three modes (`all`, `secondary_only`, `primary_only`) and
**`secondary_only` is the default**, because the error that produces runs in the
safe direction for published work.

## Why this exists

Theoretical work on tokenized supply chain finance treats market liquidity as an
exogenous parameter. Empirical work suggests real tokenized markets are thin.
Connecting those two literatures needs measurements, and the measurements need
to be auditable. That is why every metric returns a provenance record naming its
sources, window, record count, exclusions and caveats, and why the methodology is
written down rather than implied by the source code.

## Metrics

Over an observation period `P` (default 30 days), for an asset `a`:

| Metric | Definition |
|---|---|
| Turnover ratio | total transfer volume over `P` / total asset value at end of `P` |
| Active holder ratio | unique addresses with at least one transfer in `P` / total holder count at end of `P` |
| Volume per active address | total transfer volume over `P` / unique active addresses in `P` |
| Top-10 holder share | balance held by the 10 largest addresses / total supply |
| Holder HHI | sum of squared holder balance shares, on the 0-10,000 scale |
| Dormancy | share of total supply held by addresses with no transfer in `P` |

Formulas, unit conventions, exclusion rules and every caveat are in
[`docs/methodology.md`](docs/methodology.md). A worked example with the
arithmetic done by hand is in [`tests/test_metrics.py`](tests/test_metrics.py).

## Data sources

| Source | Provides | Key | Verified live |
|---|---|---|---|
| **Ethereum JSON-RPC** | transfers, holder balances, supply | **no** | **yes** |
| [DeFiLlama](https://defillama.com) prices | price, symbol, decimals | no | yes |
| [DeFiLlama](https://defillama.com) protocol TVL | protocol-level value | no | yes |
| [rwa.xyz](https://rwa.xyz) | market values, supply, holder counts | yes | no |
| [Dune Analytics](https://dune.com) | transfers, holder balances | yes | no |

The on-chain adapter is the one that matters, and it needs no credentials. It
reconstructs holder balances by replaying every `Transfer` event since a token was
deployed, then **checks the reconstruction against the contract's own
`totalSupply()`**. For BUIDL and OUSG the two match to the raw unit, so the holder
distribution is correct by construction rather than trusted: no provider index, no
truncated top-N list. A mismatch means balances change by some mechanism other
than transfers, most often rebasing, and the adapter says so instead of publishing
a distribution it cannot justify.

That is tractable only because tokenized funds are thin. BUIDL's entire history is
about 15,000 logs; a gold token's is a quarter of a million and the scan is
refused.

"Verified live" means the adapter has been run against the real API. rwa.xyz and
Dune were written against published documentation because no keys were available;
their tests prove they handle the documented shapes and nothing more. Every
unverified assumption is listed in
[`docs/data-sources.md`](docs/data-sources.md), which also carries the SQL a
saved Dune query must produce.

Where sources disagree on the same figure, the package reports the variance
rather than silently picking one.

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/atytmr07/rwa-liquidity.git
```

For live data, copy `.env.example` to `.env` and fill in the keys you have. No
key is needed for DeFiLlama. API responses are cached to local parquet as the
raw response, so a schema fix never costs another paid call, and `--refresh`
bypasses the cache.

## Python API

```python
from rwa_liquidity.demo import load_demo_dataset
from rwa_liquidity.metrics import turnover_ratio

data = load_demo_dataset()
result = turnover_ratio(data.transfers, data.snapshots, window=data.window)

result.value  # 0.0 -- no secondary market at all
result.provenance.mode  # VolumeMode.SECONDARY_ONLY
result.provenance.n_records  # transfers behind the number
result.provenance.warnings  # what is doubtful about it
```

Everything the CLI can do is reachable from Python; the CLI is presentation only.

## Development

```bash
uv sync --all-extras
```

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -m "not network"
```

`mypy --strict` and a clean `ruff` run are enforced in CI on every push. Tests
marked `network` hit live APIs and are deselected in CI; run them with
`uv run pytest -m network`. The ones needing keys skip themselves and name the
variable that is missing.

## Limitations

Stated at length in [`docs/methodology.md`](docs/methodology.md). The short
version:

- **On-chain data is not the whole market.** Off-chain settlement is invisible,
  so an actively traded asset can read as dormant.
- **Addresses are not people.** One custodian holding for a thousand clients is
  indistinguishable from a whale. Concentration figures are bounds, not
  measurements.
- **Issuer classification is configuration, not detection.** An issuer that
  distributes from an unconfigured treasury has its issuance counted as trading.
  The package warns when that pattern is possible; it cannot rule it out.
- **Holder lists are usually truncated**, which biases HHI downward. Disclosed,
  not corrected.
- **Ethereum only.** Multi-chain assets are measured on one chain, and
  cross-chain bridging appears as ordinary transfers.
- **Six months of history, ten assets.** Enough for a direction, not for a growth
  rate, and `trend` says so rather than fitting one.
- **Full-history reconstruction has a ceiling.** Tokens with more than ~250,000
  transfer logs are refused rather than scanned against a free endpoint.
- **Two of five adapters are unverified against their live APIs** (rwa.xyz, Dune).
- **The shipped sample dataset is synthetic.** It demonstrates the metrics; the
  real measurements come from the on-chain adapter.

## Roadmap

- [x] **1** Skeleton, tooling, CI
- [x] **2** Normalized schema and parquet cache
- [x] **3** DeFiLlama adapter
- [x] **4** Metrics layer, all three volume modes, provenance
- [x] **5** rwa.xyz and Dune adapters
- [x] **6** Cross-source reconciliation
- [x] **7** CLI, export, demo mode
- [x] **8** Methodology docs and worked example
- [x] **9** Keyless on-chain adapter, live pipeline, published findings
- [x] **10** Ledger-derived history, six-window trends, issuance verification

Not done: the two keyed adapters (rwa.xyz, Dune) need a first run against their
real APIs, and the registry covers eleven Ethereum assets rather than the full
multi-chain RWA universe.

## License

MIT, see [LICENSE](LICENSE).
