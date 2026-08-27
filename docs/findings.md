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

**Re-verified 2026-08-24 for nine of the ten measured assets**, after a rewrite
of the scanning method (`DECISIONS.md`, 2026-08-14/15 entries) changed how the
underlying logs are fetched without changing what they mean. ZTLN, RCOIN, CGT
and ATT reproduced every figure exactly; USDM's HHI matched exactly and its
rebasing guard fired correctly again; FDIT, CANA, HLSCOPE and OUSG showed
different turnover and dormancy (expected -- a different 30-day window has
different activity) while holding concentration nearly constant (expected --
ownership does not reshuffle in a month), matching the pattern already
documented in SS7a. **BUIDL itself could not be re-verified**: forty attempts
over 85 minutes, deliberately spaced to avoid the sustained load the endpoint's
own error message names as the trigger, failed identically every time. See
`DECISIONS.md`, 2026-08-24, for what that rules out and what it does not. The
BUIDL figures below are the original 2026-07-30 measurement, not re-confirmed
since.

**2026-08-26: `known_addresses.toml` added.** Checking each measured asset's
top holders against Etherscan's own contract labels found that three of them
had a DeFi contract -- a lending vault or an AMM pool -- sitting among their
largest holders, aggregating an unknown number of end-users behind one
balance. `report` and `trend` now exclude these by default; see §5a for what
changed, and `docs/methodology.md` §2.4 for the mechanism. The tables in §1,
§2 and §7a below are the original run and **predate this exclusion** -- they
were not regenerated in place, because doing so on the live window would also
shift every other figure in them (the observation window moves with "now"),
making it impossible to tell a window effect from an exclusion effect. §5a
isolates the exclusion effect instead, on the same cached data, holding the
window fixed.

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

The 2010 US Horizontal Merger Guidelines treat an HHI above 2,500 as highly
concentrated; the 2023 revision lowered that threshold to 1,800, and puts
1,000--1,800 at "moderately concentrated" (US DOJ & FTC, *Merger Guidelines*
SS2.1 (2023), as stated by the
[DOJ Antitrust Division](https://www.justice.gov/atr/herfindahl-hirschman-index)).
Of the ten measured assets, **eight exceed 2,500 and six exceed 5,000**; the
same eight also clear the stricter 1,800 threshold (the two that don't, BUIDL
at 1,618 and OUSG at 1,385, sit between "moderately" and "highly" concentrated
under either guideline). Top-10 share is above 92% for nine of them. OUSG's
1,385 is itself overstated by a DeFi vault this run did not yet exclude -- see
§5a, where the same figure comes out to 779 once it is.

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

## 5a. What changes once DeFi-aggregation contracts are excluded

The concentration figures above treat every address with a balance as one
holder, which cannot distinguish an investor's wallet from a contract that
pools many investors behind it. Checking OUSG, USDM and CANA's top holders
against Etherscan's own contract labels (2026-08-26) found three: `Flux
Finance: fOUSG Token`, a lending vault that accepts OUSG as collateral;
Mountain Protocol's own `wUSDM` wrapper; and, for CANA, both a CANA-specific
Uniswap V2 pool and Uniswap V4's global pool-manager contract. Full citations
are in `src/rwa_liquidity/sources/data/known_addresses.toml`.

To isolate what excluding them actually changes -- without also mixing in a
different observation window, which would confound the comparison -- the same
cached snapshots, transfers and holders (window ending 2026-08-26) were run
through `build_report` twice: once with no exclusions, once with the addresses
above excluded. Nothing else differs between the two columns.

| Asset | Metric | No exclusions | Excluded | |
|---|---|---|---|---|
| OUSG | Top-10 share | 94.2% | **70.0%** | -24.2 pts |
| OUSG | HHI | 1,422 | **779** | -45% |
| OUSG | Dormancy | 79.6% | **54.2%** | -25.4 pts |
| USDM | HHI | 7,929 | **7,518** | -5% |
| CANA | Top-10 share | 99.49% | **98.86%** | -0.6 pts |
| CANA | HHI | 2,781.6 | **2,781.2** | ~0 |

**OUSG is the one that matters.** A quarter of its supply sits in one lending
vault; excluding it does not just adjust the concentration figure, it changes
which side of the DOJ/FTC "highly concentrated" line (HHI 1,800 under the 2023
guidelines) OUSG falls on in the direction of *less* concentrated once the
vault is set aside. **CANA barely moves**, despite being the only asset in the
registry with a confirmed public AMM pool among its top holders: its single
largest holder already dominates supply independent of the pool, so excluding
a contract that never was the concentration driver does not change the
headline number, even though it was still the right thing to exclude on
principle. **USDM's top-10 share and dormancy stay `n/a`** either way -- the
wrapper exclusion does not touch the separate rebasing-reconciliation failure
documented in §6, and its HHI figure, while numerically defined, inherits that
same unreliability and should not be read as precise regardless of which
column it is read from.

None of this has been propagated into §1, §2 or §7a's tables, which predate
`known_addresses.toml` and were left as originally measured -- see the note at
the top of this document.

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

**PAXG** exceeds 250,000 transfer logs and is refused by the keyless adapter.
Tokenized gold trades like an ordinary crypto asset, and exhaustive
reconstruction against a free public endpoint is not reasonable at that volume.
It is reported as *not measurable*, and deliberately **not** as zero — a failed
scan and an inactive asset produce the same empty result, and conflating them
would manufacture a finding out of a failed request.

## 7a. Past that boundary: PAXG measured through a paid source

The §7 boundary invites a serious objection, and it is worth stating in its
strongest form: *if the method can only reach assets thin enough to scan
exhaustively, then "these assets barely trade" may be a property of the method's
reach rather than of the market.* On that reading the headline findings would be
close to circular.

Answering it requires measuring an asset from the other side of the boundary. On
2026-08-27, PAXG was measured over the identical 30-day window using Dune
Analytics, with the primary/secondary classification expressed in SQL rather than
in this package's classifier — same rules (zero address, burn address), different
engine. **The reconstruction was checked the same way**: balances summed to
441,940.72 PAXG against the contract's own `totalSupply()` of 441,941.91 recorded
in §1, a difference of 1.19 tokens or **0.00027%**. The invariant this package
insists on holds for these figures too, so they are not offered on a provider's
word alone.

| | PAXG | The ten permissioned assets |
|---|---|---|
| Holders | **84,962** | 2 – 1,587 |
| Secondary transfers | **135,145** | 0 – 255 |
| Turnover, `all` | 0.7421 | 0.0000 – 2.2576 |
| Turnover, `secondary_only` | **0.7172** | 0.0000 – 1.0767 |
| Overstatement factor | **1.03x** | 1.0x – 10.8x |
| Top-10 holder share | **34.0%** | above 92% for nine of ten |
| Holder HHI | **378** | 1,385 – 9,362 |
| Dormancy | **73.0%** | 0% – 100% |
| Active holder ratio | 26.4% | 0% – 200% |

**The objection does not survive this.** Applied to a genuinely traded tokenized
RWA, the same method reports a genuinely traded asset: an HHI of 378 is below
even the "unconcentrated" floor of 1,500, against a sample where eight of ten
exceed 2,500; a top-10 share of 34% against 92%-plus for nine of ten; 84,962
holders against a maximum of 1,587. The method is not built to find illiquidity
and does not find it here.

Two further points follow, and they cut in opposite directions:

* **The primary/secondary correction is near-irrelevant for PAXG** — 1.03x, the
  smallest factor anywhere in this document. Only 37 of its 135,182 transfers in
  the window were issuance. That is the *expected* result for an asset that
  trades on open venues, and it bounds the claim in §4 properly: raw volume
  overstates secondary liquidity **for permissioned funds that mint and redeem**,
  not for tokenized RWAs as a class.
* **Tokenization can produce broad ownership; these funds simply do not.** PAXG
  is a tokenized real-world asset with 84,962 holders and low concentration. The
  §5 concentration finding is therefore about the instrument class — regulated,
  whitelist-gated fund shares — and not, as a looser reading might have it, about
  tokenization itself. Stated that way it is a narrower claim and a defensible
  one.

**What this does not establish.** These figures come from a different code path
than every other number in this document: Dune's own indexed tables, queried in
SQL, not `evm_rpc`'s log replay. The supply cross-check above is real but it is
one check, not the full per-asset reconciliation the keyless adapter performs.
PAXG remains outside what a third party can reproduce with no API key, which is
the actual content of the §7 boundary — the constraint costs coverage of exactly
the assets that most need no defending.

The boundary is therefore informative rather than merely a limitation, but not
in the way §7 originally put it: the assets whose liquidity is worth questioning
are the ones thin enough to measure exhaustively for free, and the assets that
visibly trade are the ones that need a paid source to confirm what is already
visible.

## 7a. Six months, not one snapshot

The cross-section above says how liquid these assets were. It cannot say whether
tokenized markets are deepening, which is the next question. Supply and holder
distributions are reconstructed from the ledger **at each window's end** rather
than taken from today, so a fund that has grown does not show a falsely
collapsing turnover because its denominator moved. BUIDL's supply over the six
windows was 172m, 169m, 148m, 178m, 187m, 225m -- using the last figure
throughout would have distorted every earlier ratio.

```bash
uv run rwa-liquidity trend --metric turnover_ratio
```

**Secondary turnover**, six consecutive 30-day windows, oldest first:

| Asset | 03-02 | 04-01 | 05-01 | 05-31 | 06-30 | 07-30 | |
|---|---|---|---|---|---|---|---|
| ATT | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | flat at zero |
| BUIDL | 0.0384 | 0.0503 | 0.2128 | 0.1145 | 0.0133 | 0.0187 | falling |
| CANA | 0.0960 | 0.5313 | 0.0176 | 0.1251 | 0.0548 | 0.0669 | falling |
| CGT | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | flat at zero |
| FDIT | 0.1868 | 0.2121 | 0.4119 | 0.2019 | 0.6238 | 1.0767 | rising |
| HLSCOPE | 0.0147 | 0.7181 | 0.2839 | 0.1201 | 0.0003 | 0.0728 | rising |
| OUSG | 0.3141 | 0.6831 | 0.7677 | 0.3345 | 0.8556 | 0.1971 | falling |
| RCOIN | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | flat at zero |
| USDM | 0.1067 | 0.0577 | 0.0759 | 0.0131 | 0.0229 | 0.0058 | falling |
| ZTLN | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | flat at zero |

**Four assets recorded no secondary trading in any of the six windows.** A single
month of silence could be a quiet month; six is a property of the asset.

Nothing here shows a market deepening in aggregate. Two of ten rose, four fell,
four never moved. The single asset with a clear upward series, FDIT, has three
holders — its rising turnover is three parties trading with each other more often,
which is not the same as a market forming.

**Concentration is the flattest series in the dataset.** Top-10 share moved by
less than a percentage point over six months for seven of the nine measurable
assets. Regenerated 2026-08-27 with `known_addresses.toml`'s exclusions in
effect (§5a):

| Asset | 03-30 | 08-27 | |
|---|---|---|---|
| OUSG | 78.4% | 70.0% | **falling** |
| CANA | 94.7% | 98.8% | flat |
| RCOIN | 97.3% | 97.1% | flat |
| CGT | 99.2% | 99.2% | flat |
| ATT | 99.2% | 99.2% | flat |
| FDIT / HLSCOPE / ZTLN | 100.0% | 100.0% | flat |
| USDM | n/a | n/a | rebasing guard, all windows |
| BUIDL | — | — | endpoint refused the scan on this run |

### The direction of the one clear mover reversed

The previous version of this table, run before the DeFi-contract exclusions
existed, reported **OUSG rising from 82.4% to 92.9%** and called it "the one
clear mover, and it concentrated." With Flux Finance's fOUSG vault excluded,
OUSG **falls, 78.4% to 70.0%**. The sign of the only non-flat series in the
dataset was an artifact of counting a lending vault as a single large holder.

Two things changed between the runs — the exclusions, and the windows, which
slide with the present — so this is not a clean single-variable comparison on
its own. The isolated test in §5a is: holding the window fixed and toggling
only the exclusion moved OUSG's top-10 share from 94.2% to 70.0%, a 24-point
swing, which is far larger than anything the five-week window shift could
account for. The exclusion is the cause.

Read correctly, OUSG was **deconcentrating** over these six windows while the
vault's growing position made it look like the opposite. That is the strongest
single argument in this document for why the address-versus-investor problem
(§5a) is not a footnote: it did not merely blur a number here, it inverted a
published finding.

BUIDL could not be re-measured on this run — the free endpoint refused the scan
partway, the same failure documented at the top of this file — so its previous
reading (82.3% to 83.6%, flat) stands unconfirmed against the new exclusions.
BUIDL has no entry in `known_addresses.toml`, so no exclusion applies to it and
the figure is not expected to move; that is a reason to expect stability, not
evidence of it.

Nothing else moved. Over six months, on these assets, tokenization did not
broaden ownership — and the one asset that did broaden it, OUSG, was previously
reported as doing the reverse.

## 8. Caveats

In full in [`methodology.md`](methodology.md). Those bearing directly on the
figures above:

* **Ethereum only.** BUIDL also exists on Aptos, Solana, Avalanche, Optimism,
  Arbitrum, Polygon and BNB Chain; roughly a third of its value is on Ethereum.
  Cross-chain bridging appears here as ordinary transfers.
* **Issuer classification rests on the zero-address rule, and that rule is
  verified here.** This was previously a blanket caveat. It is now a checked fact:

  ```bash
  uv run rwa-liquidity issuance
  ```

  **All ten measurable assets mint through the zero address.** Their mint counts
  over full history run from 2 (ZTLN) to 11,622 (BUIDL), and every one has a first
  mint block. This rules out an asset that issues *exclusively* through an
  unconfigured treasury, which would show zero zero-address mints, ever. It does
  **not** rule out an asset minting its initial tranche through the zero address
  and later distributing further supply from a treasury address instead, which
  this method would count as ordinary secondary trading -- a single historical
  mint proves the asset *can* issue this way, not that everything counted as
  secondary here *did* trade rather than get distributed. This matters most for
  BUIDL, USDM, CANA and OUSG, the assets with non-trivial secondary-classified
  volume; it does not matter for the four with none.

  **This was searched for rather than left open.** On 2026-08-27 a query looked
  for the distributor signature -- an address that received a mint from the zero
  address and then sent onward to many distinct recipients -- and two candidates
  were confirmed by Etherscan's own labels: CANA's `0xccadea5c...` ("Maseer:
  Deployer", 113 distinct recipients across 133 sends) and CGT's `0x6522b05f...`
  ("CACHE Gold: Old Backed Treasury"). Both are now configured as
  `issuer_addresses` in `known_addresses.toml`. Their effect on the figures
  above is nil: CANA's appears in **zero** of the window's transfers (and in 11
  of the 1,885 across the six trend windows, 0.6%), and CGT's has been dormant
  since 2021-10-30. OUSG's strongest candidate, `0x3d85c41e...`, was
  **rejected** -- 220 sends to 12 distinct recipients, but no Etherscan label and
  no issuer documentation naming it, so configuring it would reclassify transfers
  on behaviour alone. That exposure is bounded rather than resolved: 3 of OUSG's
  50 window transfers involve it. Had any asset shown zero mints across its
  entire history, the rule would have been blind to it and the command would say
  so, naming the largest recipient of supply as a candidate issuer address for
  review.
* **Addresses are not investors.** 59 addresses could be 59 institutions or a few
  behind custodians. This is not hypothetical: §5a found three cases where a
  top holder is a DeFi contract standing in for an unknown number of end-users,
  now excluded by default from the concentration and dormancy figures the CLI
  reports. That correction covers only the three assets checked -- concentration
  still bounds the truth in both directions everywhere `known_addresses.toml` is
  silent.
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
