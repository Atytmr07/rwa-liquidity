# Findings

Measurements on real tokenized real-world assets, produced by this package
against a public Ethereum node with **no API key**. Reproducible with:

```bash
uv run rwa-liquidity report --mode secondary_only
```

Window: 30 days ending 2026-07-30. Chain: Ethereum mainnet. Source: `evm_rpc`.
Holder distributions were reconstructed from each token's complete `Transfer`
history and checked against the contract's own `totalSupply()`; where the two
agreed the distribution is exact, and where they did not the affected metrics are
reported as undefined rather than estimated.

## How these eleven assets were chosen

Not by hand-picking. Every protocol DeFiLlama files under category `RWA` was
taken, its Ethereum addresses extracted, and each address resolved on-chain. The
contract's own `symbol()` and `name()` decided what it is. Roughly three quarters
of the addresses turned out to be a protocol's **governance token** rather than a
tokenized asset — ONDO, CFG, ENA, SKY, CPOOL, SYRUP and others — and were
discarded. The procedure and the discards are recorded in
`src/rwa_liquidity/sources/data/defillama.toml`.

The result spans treasury funds, private credit, gold, carbon allowances and a
green bond, which is deliberate: nothing here assumes the instrument classes
behave alike.

---

## 1. What was observed

| Asset | Supply | Holders | Transfers | mint | burn | secondary |
|---|---|---|---|---|---|---|
| BUIDL | 224,830,404.13 | 59 | 731 | 696 | 3 | **32** |
| ZTLN | 150,000,000.00 | 2 | 0 | 0 | 0 | **0** |
| FDIT | 63,287,229.17 | 3 | 28 | 9 | 6 | 13 |
| OUSG | 1,455,454.62 | 53 | 51 | 15 | 15 | 21 |
| USDM | 1,276,201.32 | 1,587 | 256 | 0 | 1 | 255 |
| RCOIN | 452,082.77 | 25 | 0 | 0 | 0 | **0** |
| PAXG | 441,941.91 | *not measurable* | | | | |
| CGT | 100,771.01 | 272 | 3 | 0 | 0 | 3 |
| CANA | 30,837.42 | 222 | 102 | 0 | 0 | 102 |
| ATT | 1,825.32 | 29 | 0 | 0 | 0 | **0** |
| HLSCOPE | 159.94 | 3 | 2 | 0 | 0 | 2 |

## 2. The metrics

| Asset | turnover `all` | turnover `secondary_only` | overstatement | dormancy | top-10 | HHI |
|---|---|---|---|---|---|---|
| BUIDL | 0.2015 | **0.0187** | **10.8x** | 96.2% | 83.6% | 1,618 |
| ZTLN | 0.0000 | **0.0000** | no secondary market | 100.0% | 100.0% | 5,556 |
| FDIT | 2.2576 | **1.0767** | 2.1x | 0.0% | 100.0% | 9,362 |
| OUSG | 0.4203 | **0.1971** | 2.1x | 50.9% | 92.9% | 1,385 |
| USDM | 0.0022 | **0.0022** | 1.0x | n/a | n/a | 7,929 |
| RCOIN | 0.0000 | **0.0000** | no secondary market | 100.0% | 97.1% | 8,348 |
| PAXG | *not measurable* | | | | | |
| CGT | 0.0000 | **0.0000** | no secondary market | 100.0% | 99.2% | 9,223 |
| CANA | 0.0677 | **0.0677** | 1.0x | 82.3% | 99.5% | 2,783 |
| ATT | 0.0000 | **0.0000** | no secondary market | 100.0% | 99.2% | 6,895 |
| HLSCOPE | 0.0728 | **0.0728** | 1.0x | 54.9% | 100.0% | 4,724 |

---

## 3. Four of ten had no secondary market at all

ZTLN, RCOIN, ATT and CGT recorded **zero** holder-to-holder transfers in the
window. Their dormancy is 100%: every token outstanding sits with an address that
did not move it.

ZTLN is the starkest. It has **$150m of supply, two holders, and no transfers in
its entire history** beyond the twelve that created it. Read from a TVL dashboard
it is a substantial tokenized product. Measured, it is a bilateral arrangement
recorded on a public chain.

This is not a distinction that raw transfer volume can express. `turnover_ratio`
under `--mode all` also reads 0.0000 for these four, so nothing is gained here by
the primary/secondary split — the point is that a **non-zero** figure would have
been reported for BUIDL and OUSG regardless, and no reader could tell from the
number alone which situation they were in.

## 4. Where the split does change the answer

**BUIDL**, the largest tokenized treasury fund on Ethereum, moved 731 times in
the window. 696 of those were issuance and 32 were trading between holders.

| BUIDL | `--mode all` | `--mode secondary_only` |
|---|---|---|
| Turnover | 0.2015 | **0.0187** |
| Dormancy | 3.0% | **96.2%** |
| Active holder ratio | 69.5% | **18.6%** |

Read the first column and BUIDL is a fund with a fifth of its supply changing
hands monthly and few idle holders. Read the second and 1.9% of supply traded
between investors while 96% of the fund sat still. Identical data; the difference
is entirely whether issuance counts as trading.

**The correction is not a constant.** BUIDL 10.8x, OUSG 2.1x, FDIT 2.1x, and 1.0x
for the assets whose activity is already all secondary. Any model calibrating
liquidity from published transfer volume is calibrating from a figure wrong by an
asset-specific factor between 1 and 11, which cannot be corrected with a scalar.

## 5. Concentration is extreme almost everywhere

US antitrust guidelines treat an HHI above 2,500 as highly concentrated. Of the
ten measured assets, **eight exceed 2,500 and six exceed 5,000**. Top-10 share is
above 92% for nine of them.

Two cases deserve separate mention because they invert the usual reading:

* **FDIT** (Fidelity Digital Interest Token) shows the highest secondary turnover
  in the set at 1.08 and a dormancy of 0%. It has **three holders**. Every token
  is active because there is nobody inactive; HHI 9,362. High turnover among three
  parties is not a liquid market, and no volume-based metric can say so on its
  own. This is the clearest argument in the dataset for reporting flow and stock
  measures together.
* **HLSCOPE**, a Hamilton Lane private-credit feeder, has three holders and 50
  transfers in its entire history. Private credit is illiquid by design, so this
  is the expected result and serves as a control: the method reports a genuinely
  illiquid instrument as illiquid.

## 6. The verification check earning its place

**USDM** rebases: holder balances grow without a `Transfer` event. The
reconstruction therefore disagreed with `totalSupply()` — by a wide margin, with
439 addresses ending on a negative balance — and the concentration and dormancy
metrics are reported as **n/a** rather than as numbers.

Before that guard existed this asset produced a top-10 share of **2.21** and a
dormancy of **1.53**. A share cannot exceed 1. Publishing those with a warning
attached would have invited any reader to treat 2.21 as a percentage. They are now
refused outright, and the reason is recorded.

That is the argument for deriving holder data rather than fetching it: a provider
would have returned a plausible-looking distribution for USDM and nothing would
have signalled that it could not be reconciled with the token's own supply.

## 7. Where the method stops

**PAXG** exceeds 250,000 transfer logs and is refused. Tokenized gold trades like
an ordinary crypto asset, and exhaustive reconstruction against a free public
endpoint is not reasonable at that volume. It is reported as *not measurable*, and
deliberately **not** as zero — a failed scan and an inactive asset produce the
same empty result, and conflating them would manufacture a finding out of a
failed request.

The boundary is informative rather than merely a limitation: the assets whose
liquidity is worth questioning are precisely the ones thin enough to measure
exhaustively. Gold tokens do not need this analysis; they visibly trade.

## 8. Caveats

In full in [`methodology.md`](methodology.md). Those bearing directly on the
figures above:

* **Ethereum only.** BUIDL also exists on Aptos, Solana, Avalanche, Optimism,
  Arbitrum, Polygon and BNB Chain; roughly a third of its value is on Ethereum.
  Cross-chain bridging appears here as ordinary transfers.
* **Issuer classification rests on the zero-address rule.** BUIDL, OUSG and FDIT
  mint from the zero address, so their issuance is visible. CANA, USDM, CGT,
  HLSCOPE and ATT show **no mints at all**, which means either that issuance
  predates the window or that they distribute from a treasury this registry has
  not been told about. In the second case some of what is counted as secondary is
  really issuance, so those secondary figures are **upper bounds**. The adapter
  warns whenever this pattern is possible.
* **Addresses are not investors.** 59 addresses could be 59 institutions or a few
  behind custodians. Concentration bounds the truth in both directions.
* **Off-chain settlement is invisible.** Securitize and similar transfer agents
  maintain registers; a transfer settled there without an on-chain movement does
  not appear.
* **One window, one snapshot.** Nothing here establishes a trend.

## Reproducing

```bash
uv run rwa-liquidity report --mode all --out all.csv
```

```bash
uv run rwa-liquidity report --mode secondary_only --out secondary.csv
```

The first run replays each token's full history and takes a few minutes;
responses are cached afterwards, so the bytes behind every figure above stay on
disk and a rerun is instant. Numbers move as new blocks arrive.
