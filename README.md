# rwa-liquidity

Measure liquidity in tokenized real-world asset (RWA) markets.

Tokenized asset data is scattered across providers that disagree on schemas and
definitions. Anyone asking "how liquid is this tokenized asset, actually?" ends
up rewriting the same ingestion and metric code. This package standardizes that:
it ingests from multiple sources, normalizes to one schema, and computes a
documented set of liquidity metrics whose outputs are reproducible and traceable
back to the raw records they came from.

> **Status: under construction.** The skeleton and tooling are in place. Data
> adapters, metrics, and the CLI land over the phases listed in
> [Roadmap](#roadmap). Nothing below marked *planned* works yet.

## Why this exists

Theoretical work on tokenized supply chain finance treats market liquidity as an
exogenous parameter. Empirical work suggests real tokenized markets are thin.
Connecting those two literatures needs measurements, and the measurements need
to be auditable. That is why every metric here returns a provenance record
alongside its value, and why the methodology is documented rather than implied
by the source code.

## The thing this gets right

Primary issuance is not liquidity.

A tokenized fund that only ever mints and redeems has no secondary market, no
matter how large its raw transfer volume looks. Most naive implementations count
mints and burns as trading activity and overstate liquidity as a result. Here,
every volume-based metric is computable in three modes (`all`, `secondary_only`,
`primary_only`) and **`secondary_only` is the default**.

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

Full formulas, unit conventions, exclusion rules, and caveats live in
[`docs/methodology.md`](docs/methodology.md) *(planned, Phase 8)*.

## Data sources

| Source | Provides | Key required |
|---|---|---|
| [rwa.xyz](https://rwa.xyz) | asset metadata, issuers, networks, market values, holder counts | yes |
| [Dune Analytics](https://dune.com) | transfer-level and holder-level on-chain data | yes |
| [DeFiLlama](https://defillama.com) | TVL-style figures, used for cross-validation | no |

Where sources disagree on the same figure, the package reports the variance
rather than silently picking one. What each source actually supplies, and what is
wrong with it, is written up in [`docs/data-sources.md`](docs/data-sources.md).

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/atytmr07/rwa-liquidity.git
```

```bash
uv sync
```

## Quickstart

*Planned, Phase 7.* The package ships a committed sample dataset so it runs with
no API keys at all:

```bash
uv run rwa-liquidity report --demo
```

For live data, copy `.env.example` to `.env` and fill in the keys you have. No
key is needed for DeFiLlama. API responses are cached to local parquet; pass
`--refresh` to bypass the cache.

## Development

```bash
uv sync --all-extras
```

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest --cov
```

`mypy --strict` and a clean `ruff` run are enforced in CI on every push.

## Limitations

*To be written properly in Phase 8, once there is something to be honest about.*
Known constraints already visible: on-chain data cannot see off-chain transfers
of the same asset; holder concentration is measured over addresses, not
beneficial owners, so a single custodian and a thousand retail holders can be
indistinguishable.

## Roadmap

- [x] **1** Skeleton, tooling, CI
- [x] **2** Normalized schema and parquet cache
- [x] **3** DeFiLlama adapter
- [ ] **4** Metrics layer, all three volume modes, provenance
- [ ] **5** rwa.xyz and Dune adapters
- [ ] **6** Cross-source reconciliation
- [ ] **7** CLI, export, demo mode
- [ ] **8** Methodology docs and worked example

## License

MIT, see [LICENSE](LICENSE).
