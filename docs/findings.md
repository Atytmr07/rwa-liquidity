# Findings

Real measurements on real tokenized funds, produced by this package against a
public Ethereum node with no API key. Every figure here is reproducible:

```bash
uv run rwa-liquidity report --mode secondary_only
```

Window: 30 days ending 2026-07-30. Chain: Ethereum mainnet. Source: `evm_rpc`,
whose holder distributions were verified against each contract's own
`totalSupply()` and matched to the raw unit.

---

## 1. The headline: raw transfer volume overstates liquidity by up to 11x

**BlackRock USD Institutional Digital Liquidity Fund (BUIDL)**, the largest
tokenized treasury fund on Ethereum, held 224,830,404.13 tokens across **59
addresses** over the window.

Of its 731 transfers:

| Kind | Count | Share |
|---|---|---|
| Mint (issuance) | 696 | 95.2% |
| Burn (redemption) | 3 | 0.4% |
| **Secondary (actual trading)** | **32** | **4.4%** |

The consequence:

| BUIDL | `--mode all` | `--mode secondary_only` | Ratio |
|---|---|---|---|
| Turnover | 0.2015 | **0.0187** | **10.8x** |
| Dormancy | 3.0% | **96.2%** | |
| Active holder ratio | 69.5% | **18.6%** | |

Read the first column and BUIDL looks like a fund with a fifth of its supply
changing hands monthly and almost no idle holders. Read the second and the same
30 days show 1.9% of supply traded between investors, with 96% of the fund
sitting in addresses that never traded at all.

Both columns come from identical data. The difference is entirely whether
issuance is counted as trading.

## 2. The effect is not uniform

**Ondo Short-Term US Government Treasuries (OUSG)** held 1,445,114.65 tokens
across **53 addresses**. Its 51 transfers split 15 mint, 15 burn, 21 secondary,
so 41% of its activity is genuine trading against BUIDL's 4.4%.

| | BUIDL | OUSG |
|---|---|---|
| Secondary share of transfers | 4.4% | 41.2% |
| Turnover, `all` | 0.2015 | 0.4233 |
| Turnover, `secondary_only` | 0.0187 | 0.1985 |
| Overstatement factor | **10.8x** | **2.1x** |
| Dormancy, `secondary_only` | 96.2% | 51.3% |

OUSG has a materially more active secondary market than BUIDL despite being
roughly 1% of its size in token count. A ranking by raw transfer volume would
put BUIDL far ahead; a ranking by secondary turnover reverses it.

**This is the finding that matters for the literature.** If theoretical work
treats liquidity as an exogenous parameter and calibrates it from published
transfer volume, it is calibrating from a figure that is wrong by an
asset-specific factor between roughly 2 and 11. The correction is not a constant.

## 3. Concentration

| | BUIDL | OUSG |
|---|---|---|
| Holders | 59 | 53 |
| Top-10 share | 83.6% | 93.5% |
| Holder HHI (0-10,000) | 1,618 | 1,405 |

For scale: a market where ten firms hold equal shares scores 1,000, and US
antitrust guidelines treat above 1,500 as moderately concentrated. A
multi-hundred-million-dollar fund with 59 holders and 84% of supply in ten
addresses is not a market in the sense the word usually carries.

These are **exact** rather than estimated. The distributions were reconstructed
by replaying every `Transfer` event since deployment and then checked against the
contract's own `totalSupply()`; both matched to the raw unit, so neither figure
depends on a provider's holder index or a truncated top-N list.

## 4. Where the method stops working

Two of the four registry assets could not be measured this way:

| Asset | Transfer logs since deployment | Outcome |
|---|---|---|
| PAXG (Paxos Gold) | ~254,600 | refused |
| XAUt (Tether Gold) | ~254,300 | refused |

Full-history reconstruction is tractable precisely because tokenized funds are
thin: BUIDL's entire history is ~15,000 logs and OUSG's ~2,200, each fetched in
seconds. Tokenized *commodities* trade like ordinary crypto assets, and at a
quarter of a million logs the scan exceeds what a free endpoint should be asked
for. The adapter refuses with an explanation rather than hammering the node.

That boundary is itself informative: **the assets whose liquidity is worth
questioning are exactly the ones cheap enough to measure exhaustively.** Gold
tokens do not need this analysis; they visibly trade.

## 5. Caveats that apply to every number above

Stated in full in [`methodology.md`](methodology.md). The ones that bear directly
on these figures:

* **Ethereum only.** BUIDL also exists on Aptos, Solana, Avalanche, Optimism,
  Arbitrum, Polygon and BNB Chain. Roughly a third of its multi-chain value sits
  on Ethereum, and cross-chain bridging appears here as ordinary transfers.
* **Issuer classification rests on the zero-address rule.** BUIDL mints from the
  zero address, so its issuance is visible and the classification is sound. An
  issuer distributing from a treasury address would have that activity counted as
  secondary unless the address were configured, which would push the measured
  turnover up. The figures above are therefore **upper bounds on secondary
  activity**, not lower ones.
* **Addresses are not investors.** 59 addresses could be 59 institutions or a
  handful behind custodians. Concentration figures bound the truth in both
  directions.
* **Off-chain transfers are invisible.** Securitize maintains a transfer agent
  register; a transfer settled there without an on-chain movement does not appear.
* **One 30-day window.** These are a snapshot, not a trend. Nothing here
  establishes whether either fund's secondary market is growing.

## Reproducing

```bash
uv run rwa-liquidity report --mode all --out all.csv
```

```bash
uv run rwa-liquidity report --mode secondary_only --out secondary.csv
```

The first run replays each token's full history and takes a minute or two;
responses are cached afterwards, so re-running is instant and the numbers behind
a published figure stay on disk. Figures move as new blocks arrive, so a rerun
today will differ slightly from the table above.
