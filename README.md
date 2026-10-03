# rwa-liquidity

Measurement of transfer activity and ownership concentration in tokenized
real-world asset (RWA) markets.

The package ingests data from several sources, normalizes it to one schema,
classifies every token transfer, and computes documented liquidity and
concentration measures that can be traced back to the records they came from.
It accompanies a working paper in preparation. Definitions and classification
rules are in [`docs/methodology.md`](docs/methodology.md); source-specific
details are in [`docs/data-sources.md`](docs/data-sources.md).

## Replication

All figures in the paper come from one run, read at Ethereum block 26,086,416
(29 September 2026, UTC) over the calendar months December 2025 to August 2026:

```bash
uv run rwa-liquidity paper --first-month 2025-12 --last-month 2026-08 --head 26086416
```

The command writes four files to [`paper/`](paper/):

| File | Contents |
|---|---|
| `panel.csv` | One row per asset and month: window blocks, closing supply and holders, transfer counts and volumes by event category, the turnover decomposition, participation, dormancy, and the ownership coverage decomposition |
| `table_turnover.tex` | Table 2 of the paper, August 2026 |
| `table_months.tex` | Median and range of `X` and `F` over the nine months, per asset |
| `numbers.tex` | LaTeX macros for the figures quoted in the text |

Each transfer is classified as creation (from the zero address), destruction
(to the zero or dead address), issuer-linked (to or from an address that the
asset's own issuer documents or labels, such as a redemption contract),
residual, or unresolved. Total and residual turnover share the same supply
denominator, so their ratio isolates the effect of classification.

| Asset | Total turnover | Residual turnover | Factor `F` | Outside residual `X` |
|---|---|---|---|---|
| BUIDL | 0.1940 | 0.1044 | 1.9 | 46.2% |
| OUSG | 0.5286 | 0.0563 | 9.4 | 89.4% |
| FDIT | 1.0478 | 0.6939 | 1.5 | 33.8% |
| USYC | 10.9039 | 0.4927 | 22.1 | 95.5% |
| USTB | 1.3191 | 0.2529 | 5.2 | 80.8% |
| mTBILL | 0.4958 | 0.1074 | 4.6 | 78.3% |
| TBILL | 2.0561 | 0.4385 | 4.7 | 78.7% |

August 2026. The other assets are in `paper/panel.csv`. RCOIN, ZTLN, HLSCOPE
and ATT had no transfers in August, so their factor is undefined. USDM and STBT
do not reconcile with `totalSupply()`, so their holder measures are withheld.
PAXG exceeds the 250,000-log ceiling of a full replay and is not measured; the
Dune queries used for it in a single-window comparison are in
[`sql/dune/`](sql/dune/).

Residual transfers are not verified trades: they can include custody
movements, collateral transfers and wallet reorganisation. Creation can include
distributions as well as subscriptions; BUIDL pays its dividends as newly
minted tokens.

**Ownership coverage.** At the end of August 2026 a lending vault, Flux
Finance's fOUSG contract, holds 27.9% of OUSG's supply. Excluding it lowers the
top-10 share from 96.8% to 69.6% and the HHI from 1,680 to 901 with total
supply as the denominator, but the remaining holders cover only 72.1% of
supply; among themselves their top-10 share is 96.6% and their HHI 1,734.
Between December 2025 and August 2026 coverage fell from 94.6% to 72.1%, and
the top-10 share among the retained holders rose from 76.1% to 96.6%.

## Installation

Requires Python 3.11 or later and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/atytmr07/rwa-liquidity.git
```

```bash
uv sync
```

No key is needed for the on-chain adapter or DeFiLlama. For the keyed sources,
copy `.env.example` to `.env` and fill in the keys. Responses are cached
locally, and `--refresh` bypasses the cache.

## Usage

A run against the committed synthetic sample dataset:

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

A live run replays each registered token's full transfer history from a public
Ethereum endpoint:

```bash
uv run rwa-liquidity report
```

The first run issues one log request per 10,000 blocks of each token's history
and caches every response; later runs read from the cache. A free endpoint
throttles sustained scanning, so a first run may need to be repeated to fill
the cache. `EVM_RPC_URL` selects another endpoint and `EVM_RPC_BLOCK_STEP` fixes
the block span per request.

Other commands:

| Command | Purpose |
|---|---|
| `report` | Measures for one window, ending now or from the sample data |
| `trend` | One measure across consecutive windows, with supply and holders reconstructed at each window end |
| `paper` | The paper's panel and tables, from one pinned block |
| `issuance` | Whether the classification can see how each token is issued |
| `sources` | The ingestion adapters and their capabilities |

`report` and `trend` take `--out` to write CSV, Parquet or LaTeX, and `--mode`
to choose which transfers count as activity.

### Why classification matters

Every movement of an ERC-20 token emits the same `Transfer` event, whether it
records issuance, redemption or a transfer between holders. A fund that only
issues and redeems can show large transfer volume with no circulation among its
holders. In the sample data:

| `SYNTH-TBILL` | `--mode all` | `--mode secondary_only` |
|---|---|---|
| Turnover | 0.6600 | 0.0000 |
| Dormancy | 3.0% | 100.0% |

Volume measures can be computed in three modes, `all`, `secondary_only` and
`primary_only`; `secondary_only` is the default.

### Python API

```python
from rwa_liquidity.demo import load_demo_dataset
from rwa_liquidity.metrics import turnover_ratio

data = load_demo_dataset()
result = turnover_ratio(data.transfers, data.snapshots, window=data.window)

result.value  # 0.0
result.provenance.mode  # VolumeMode.SECONDARY_ONLY
result.provenance.n_records  # transfers behind the value
result.provenance.warnings  # caveats attached to the value
```

Every measure returns a value with a provenance record naming its sources,
window, record count, exclusions and caveats. The CLI is a thin layer over the
same functions.

## Metrics

Over an observation window `P`, for an asset `a`:

| Metric | Definition |
|---|---|
| Turnover ratio | transfer volume over `P` / supply at the end of `P` |
| Active holder ratio | addresses with a counted transfer in `P` / holders at the end of `P` |
| Volume per active address | transfer volume over `P` / active addresses in `P` |
| Top-10 holder share | balance of the 10 largest addresses / supply |
| Holder HHI | sum of squared balance shares, on the 0 to 10,000 scale |
| Dormancy | share of supply held by addresses with no counted transfer in `P` |

Retained coverage and concentration conditional on retained holdings are
reported beside the full-supply measures whenever an intermediary is excluded.
The paper's quantities, including the classification factor `F`, the excluded
share `X` and bounded participation, are defined in
[`docs/methodology.md`](docs/methodology.md), section 6. A worked example is in
[`tests/test_metrics.py`](tests/test_metrics.py).

## Data sources

| Source | Provides | Key | Run against the live API |
|---|---|---|---|
| Ethereum JSON-RPC | transfers, holder balances, supply | no | yes |
| [DeFiLlama](https://defillama.com) prices | price, symbol, decimals | no | yes |
| [DeFiLlama](https://defillama.com) protocol TVL | protocol value | no | yes |
| [rwa.xyz](https://rwa.xyz) | market values, supply, holder counts | yes | no |
| [Dune Analytics](https://dune.com) | transfers, holder balances | yes | yes |

The on-chain adapter reconstructs holder balances by replaying every `Transfer`
event since deployment and checks the result against the contract's
`totalSupply()` at the pinned block. The outcome is exported as `reconciled`;
when the check fails, every measure derived from the holder distribution is
withheld. Where sources disagree on the same figure, the package reports the
difference rather than choosing one.

Per-asset issuer addresses and excluded intermediaries, with the evidence for
each, are recorded in
[`known_addresses.toml`](src/rwa_liquidity/sources/data/known_addresses.toml).

## Development

```bash
uv sync --all-extras
```

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -m "not network"
```

CI runs the same checks on every push, with `mypy --strict`. Tests marked
`network` call live APIs and are deselected in CI; run them with
`uv run pytest -m network`.

## Limitations

- On-chain data does not show off-chain settlement, so an asset traded off
  chain can appear dormant.
- Residual transfers are not verified trades.
- Concentration is measured over addresses, not beneficial owners. Known pools,
  vaults, wrappers and bridges are excluded; other intermediaries are not.
- Issuer-linked classification covers only addresses that the issuer documents
  or labels. Undocumented operational addresses remain residual.
- Measurement covers Ethereum only. Cross-chain bridging appears as ordinary
  transfers or as creation and destruction.
- Tokens with more than 250,000 transfer logs are not replayed.
- The rwa.xyz adapter has not been run against its live API.
- The sample dataset is synthetic.

Details are in [`docs/methodology.md`](docs/methodology.md).

## License

MIT, see [LICENSE](LICENSE).
