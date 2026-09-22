# Findings

Measurements on real tokenized real-world assets, produced by this package
against a public Ethereum node with **no API key**. Reproducible with:

```bash
uv run rwa-liquidity report --mode secondary_only
```

Window: 30 days ending 2026-08-28. Chain: Ethereum mainnet. Source: `evm_rpc`.
Holder distributions were reconstructed from each token's complete `Transfer`
history and checked against the contract's own `totalSupply()`; where the two
agreed the distribution is exact, and where they did not the affected metrics are
reported as undefined rather than estimated.

**§1 and §2 were regenerated 2026-08-28** over the widened sixteen-asset
registry, with `known_addresses.toml`'s exclusions in effect. Two things moved
at once relative to the previous version of those tables -- the exclusions, and
the window, which slides with the clock -- so a figure that differs from an
earlier draft is not attributable to either on its own. §5a isolates the
exclusion effect on a fixed window, and is the section to cite for that. The
narrative sections below (§3 through §7) discuss the 2026-07-30 measurement and
say so where a specific number is quoted.

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
| ZTLN | 150,000,000.00 | 2 | 0 | 0 | 0 | **0** |
| USTB | 56,167,083.01 | 80 | 2,342 | 209 | 739 | 1,394 |
| USYC | 50,578,022.33 | 26 | 100 | 41 | 37 | 22 |
| mTBILL | 66,954,773.22 | 279 | 291 | 54 | 108 | 129 |
| FDIT | 47,065,431.52 | 2 | 14 | 3 | 4 | 7 |
| STBT | 24,258,448.70 | 72 | 139 | 3 | 1 | 135 |
| TBILL | 21,952,320.40 | 32 | 72 | 10 | 24 | 38 |
| OUSG | 1,326,531.37 | 53 | 30 | 9 | 10 | 11 |
| USDM | 1,276,201.32 | 1,596 | 123 | 0 | 0 | 123 |
| RCOIN | 452,082.77 | 25 | 0 | 0 | 0 | **0** |
| CGT | 100,771.01 | 273 | 1 | 0 | 0 | 1 |
| CANA | 30,837.42 | 226 | 124 | 0 | 0 | 124 |
| ATT | 1,825.32 | 29 | 0 | 0 | 0 | **0** |
| HLSCOPE | 159.94 | 3 | 0 | 0 | 0 | **0** |
| BUIDL | 211,790,799.99 | *endpoint refused the scan* | | | | |
| PAXG | 429,666.38 | *over the scan ceiling* | | | | |

The two unmeasured rows fail for different reasons and must not be read the
same way. **PAXG** exceeds the 250,000-log ceiling and is structurally out of
reach of a keyless scan (§7; measured through a paid source in §7a).
**BUIDL** is measurable in principle -- it was measured on 2026-07-30 -- and
was refused on this run by a rate-limited free endpoint. Its supply figure is
a single `eth_call` and came back fine; only the log replay did not. Its
2026-07-30 figures (59 holders, 731 transfers, 696 mint / 3 burn / 32
secondary) are the ones §4 discusses.

## 2. The metrics

| Asset | turnover `all` | turnover `secondary_only` | overstatement | dormancy | top-10 | HHI |
|---|---|---|---|---|---|---|
| ZTLN | 0.0000 | **0.0000** | no secondary market | 100.0% | 100.0% | 5,556 |
| USTB | 1.3756 | **0.4094** | 3.4x | 36.9% | 84.2% | 1,067 |
| USYC | 7.9866 | **0.2048** | **39.0x** | 46.7% | 99.8% | 3,044 |
| mTBILL | 0.5841 | **0.1346** | 4.3x | 34.2% | 99.6% | 2,052 |
| FDIT | 0.7078 | **0.3539** | 2.0x | 0.0% | 100.0% | 9,569 |
| STBT | 0.0149 | **0.0071** | 2.1x | 0.0% | 97.3%* | 9,369* |
| TBILL | 1.6356 | **0.7828** | 2.1x | 53.8% | 97.6% | 2,542 |
| OUSG | 0.2983 | **0.1294** | 2.3x | 54.2% | 70.0% | 779 |
| USDM | 0.0089 | **0.0089** | 1.0x | n/a | n/a | 7,518 |
| RCOIN | 0.0000 | **0.0000** | no secondary market | 100.0% | 97.1% | 8,348 |
| CGT | 0.0000 | **0.0000** | 1.0x | 100.0% | 99.2% | 9,223 |
| CANA | 0.0129 | **0.0129** | 1.0x | 97.3% | 98.8% | 2,781 |
| ATT | 0.0000 | **0.0000** | no secondary market | 100.0% | 99.2% | 6,895 |
| HLSCOPE | 0.0000 | **0.0000** | no secondary market | 100.0% | 100.0% | 4,724 |
| BUIDL | *endpoint refused the scan* | | | | | |
| PAXG | *over the scan ceiling* | | | | | |

\* STBT's holder metrics carry a reconciliation warning and should not be
quoted without it: 141 addresses reconstruct to a negative balance and the
reconstructed total comes to 23,594,247 against a `totalSupply()` of
24,260,529, a 2.7% shortfall. Unlike USDM the discrepancy is small enough that
no share exceeds 1, so the impossibility guard does not fire and the figures
are computed -- but the warning says the distribution is unreliable, and it is
reported here rather than dropped for tidiness.

**USYC overstates by 39x**, which is not a typo and is now the largest
correction factor in the dataset by a wide margin -- BUIDL's much-quoted 10.8x
was measured on a different window and is smaller. USYC moved 7.99 times its
supply in 30 days under `all` mode; restricted to non-issuance transfers, 0.20.
Of its 100 transfers, 78 were mint or burn. A tokenized treasury product whose
raw on-chain volume reads as eight full turns of supply per month, and whose
actual secondary trading is a fifth of one turn, is the clearest single example
in this document of why the split matters.

**The three lowest-HHI assets are all new to the registry or newly corrected**:
OUSG at 779 (after excluding its lending vault, §5a), USTB at 1,067, and
mTBILL at 2,052. The 2026-07-30 sample's claim that eight of ten assets exceed
2,500 does not survive the widened registry unchanged: on this run it is
**eleven of fourteen** (mTBILL clears the stricter 1,800 threshold but not
this one -- only OUSG and USTB fall short of both). Concentration remains
high in most of the sample, but "almost everywhere" is now too strong, since
two of fourteen sit outside even the looser 1,800 standard.

---

## 3. Four of ten had no secondary market at all

ZTLN, RCOIN, ATT and CGT recorded **zero** non-issuance transfers in the
window. Their dormancy is 100%: every token outstanding sits with an address that
did not move it. For these four the distinction drawn in
`docs/methodology.md` §1.1 does not bite: a count of zero is zero whether or
not a non-issuance transfer would have been a genuine trade.

ZTLN is the starkest. It has **$150m of supply, two holders, and no transfers in
its entire history** beyond the twelve that created it. Read from a TVL dashboard
it is a substantial tokenized product. Measured, it is not the bilateral
arrangement an earlier version of this document called it: one of its two
holders is Etherscan-labeled `Balancer: Vault`, holding two-thirds of supply
on behalf of an unknown number of liquidity providers this method cannot see
(§5a). What can be said precisely is narrower and still stark -- one
confirmed investor holds a third of total supply and has never moved it --
and what cannot be said is whether anything backed by the pooled two-thirds
has traded, since a Balancer LP position can change hands without the
underlying ZTLN in the vault ever moving.

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
On the original ten-asset run, **eight exceeded 2,500 and six exceeded 5,000**,
and top-10 share was above 92% for nine of them.

**The widened registry weakens this less than an earlier draft of this
section claimed.** That draft undercounted the table above at "nine exceed
2,500"; the correct tally, recounted directly from §2, is **eleven exceed
2,500 rather than eight of ten**, and **twelve of fourteen clear the
stricter 1,800 threshold**. Only two assets fall below 1,800 -- OUSG at 779
and USTB at 1,067 -- and a third, mTBILL at 2,052, falls short of 2,500 but
still clears 1,800, so it belongs in neither "below the line" count. Two of
the three lowest-HHI assets are ones the second registry pass added, and
OUSG clears neither line unless its lending vault is excluded (§5a; the same
figure reads 1,385, still under 2,500, with the vault counted). The
direction of the finding holds -- most of these assets are concentrated by
any antitrust standard, and the weakening is smaller than it first looked --
but "almost everywhere," written when the sample was ten assets that
happened to share an instrument type, is still too strong for a sample where
two of fourteen sit outside even the looser standard.

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
pools many investors behind it. Every measurable asset in the registry has
now been checked against Etherscan's own contract labels for this (most on
2026-08-26, the remaining nine on 2026-08-31/2026-09-01), turning up seven
contracts across five assets: `Flux Finance: fOUSG Token` (OUSG, a lending
vault); Mountain Protocol's own `wUSDM` wrapper (USDM); a CANA-specific
Uniswap V2 pool and Uniswap V4's global pool-manager contract (CANA); Usual's
`DaoCollateral` treasury (USYC); Midas's `Instant Redemption Vault` (USTB);
and, found in this pass, `Balancer: Vault` (ZTLN) and Elixir's `deUSD Mint
and Redeem` contract (HLSCOPE). Full citations are in
`src/rwa_liquidity/sources/data/known_addresses.toml`.

To isolate what excluding them actually changes -- without also mixing in a
different observation window, which would confound the comparison -- the same
cached snapshots, transfers and holders (window held fixed per asset, dated
in each row group) were run through `build_report` twice: once with no
exclusions, once with the addresses above excluded. Nothing else differs
between the two columns.

| Asset | Metric | No exclusions | Excluded | |
|---|---|---|---|---|
| OUSG | Top-10 share | 94.2% | **70.0%** | -24.2 pts |
| OUSG | HHI | 1,422 | **779** | -45% |
| OUSG | Dormancy | 79.6% | **54.2%** | -25.4 pts |
| USDM | HHI | 7,929 | **7,518** | -5% |
| CANA | Top-10 share | 99.49% | **98.86%** | -0.6 pts |
| CANA | HHI | 2,781.6 | **2,781.2** | ~0 |
| USYC | Top-10 share | 99.997% | **68.254%** | -31.7 pts |
| USYC | HHI | 2,507.0 | **1,499.3** | -40% |
| USTB | Top-10 share | 84.643% | **75.612%** | -9.0 pts |
| USTB | HHI | 1,056.7 | **934.0** | -12% |
| ZTLN | Top-10 share | 100.0% | **33.3%** | -66.7 pts |
| ZTLN | HHI | 5,556 | **1,110.6** | -80% |
| ZTLN | Dormancy | 100.0% | **33.3%** | -66.7 pts |
| HLSCOPE | Top-10 share | 100.0% | **96.9%** | -3.1 pts |
| HLSCOPE | HHI | 4,724 | **4,714.0** | ~0 |
| HLSCOPE | Dormancy | 100.0% | **96.9%** | -3.1 pts |

**OUSG is the one that matters most for the six-window trend** (§7b): a
quarter of its supply sits in one lending vault, and excluding it changes
which side of the DOJ/FTC "highly concentrated" line (HHI 1,800 under the
2023 guidelines) OUSG falls on, in the direction of *less* concentrated.
**USYC is the largest single move in this table**: the Usual treasury held
essentially all of measured supply (99.997% in the top 10 before exclusion),
so removing it drops top-10 share by 31.7 points and very nearly halves HHI.
**CANA and HLSCOPE barely move**, for opposite reasons: CANA's single largest
holder already dominates supply independent of the pool it also happens to
hold, so excluding a contract that was never the concentration driver does
not change the headline number; HLSCOPE's excluded contract held a small
fraction (3.1%) of an already-thin token to begin with. Both were still the
right addresses to exclude on principle, and this table is the record that
checking does not always find something consequential -- which is itself
evidence the checks are not being applied selectively toward a preferred
result. **USDM's top-10 share and dormancy stay `n/a`** either way -- the
wrapper exclusion does not touch the separate rebasing-reconciliation failure
documented in §6, and its HHI figure, while numerically defined, inherits
that same unreliability and should not be read as precise regardless of
which column it is read from.

**ZTLN is the one that changes the narrative, not just the number.** Every
metric in this package divides by an asset's full reconstructed total
supply, never by a re-summed total of the remaining post-exclusion holders
(`docs/methodology.md` §2.4-2.6) -- so excluding the Balancer vault does
not turn ZTLN's one remaining confirmed investor into "100% concentrated by
default." It correctly reports that the confirmed investor holds **33.3% of
total supply**, and says nothing at all about the other 66.7%, which sits in
a DeFi pool this method cannot see inside. This also means the "ZTLN has
$150m supply, two holders, no trading in its entire history" framing used
elsewhere in this document (§3) and in the README is imprecise: one of those
two addresses is not an investor, and "no trading in its entire history" is
true of the ZTLN token specifically but is silent on whether claims on the
pooled ZTLN (Balancer LP shares) have themselves traded.

None of this has been propagated into §1, §2 or §7a's tables, which predate
these exclusions and were left as originally measured -- see the note at
the top of this document. §2's HHI-threshold counts (11 of 14 exceed 2,500,
12 of 14 exceed 1,800) are counted directly from that table and do **not**
yet reflect USYC, USTB, ZTLN or HLSCOPE's exclusions above; applying them
would move at least ZTLN below both thresholds (1,110.6), which this
document has not yet done because it requires regenerating §1/§2 in full,
not just this isolated-diff table, and that has not been run since these
five exclusions were added.

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

## 7b. Six months, not one snapshot

The cross-section above says how liquid these assets were. It cannot say whether
tokenized markets are deepening, which is the next question. Supply and holder
distributions are reconstructed from the ledger **at each window's end** rather
than taken from today, so a fund that has grown does not show a falsely
collapsing turnover because its denominator moved.

```bash
uv run rwa-liquidity trend --metric turnover_ratio
uv run rwa-liquidity trend --metric top_10_holder_share
```

**Regenerated 2026-08-31** over the widened sixteen-asset registry, with
`known_addresses.toml`'s exclusions in effect throughout -- both tables below
reflect the corrected mechanism from the start, not a before/after comparison.
Fetched asset by asset with per-asset retries after the full-registry `trend`
command lost partial runs to a flaky free RPC endpoint several times in a row;
see `DECISIONS.md` if that recurs. **BUIDL** could not be reached on this run
(the endpoint refused the scan after 3 attempts) and keeps its last-confirmed
reading, marked below; **PAXG** is out of reach of this adapter entirely (§7).

**Secondary turnover**, six consecutive 30-day windows, oldest first (04-03 to
08-31):

| Asset | 04-03 | 05-03 | 06-02 | 07-02 | 08-01 | 08-31 | |
|---|---|---|---|---|---|---|---|
| OUSG | 0.6130 | 0.7647 | 0.3623 | 0.8193 | 0.2197 | 0.1097 | falling |
| FDIT | 0.2433 | 0.3788 | 0.2628 | 1.1469 | 0.5972 | 0.3539 | rising |
| RCOIN | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | flat at zero |
| USDM | 0.0570 | 0.0757 | 0.0132 | 0.0232 | 0.0137 | 0.0280 | falling |
| ZTLN | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | flat at zero |
| USYC | 5.9147 | 2.1965 | 0.5710 | 3.6417 | 0.5675 | 0.1568 | falling |
| USTB | 0.3957 | 0.3615 | 0.3535 | 0.4669 | 0.4028 | 0.3765 | flat |
| mTBILL | 0.0995 | 0.0106 | 0.1560 | 0.2482 | 0.3533 | 0.1077 | flat, volatile |
| TBILL | 0.3642 | 1.0596 | 0.2051 | 0.6200 | 0.7672 | 0.8965 | rising |
| STBT | 1.1895 | 0.0014 | 0.3182 | 0.8407 | 0.0227 | 0.0038 | falling |
| HLSCOPE | 0.7181 | 0.2839 | 0.1201 | 0.0003 | 0.0728 | 0.0000 | falling |
| CGT | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | flat at zero |
| CANA | 0.0144 | 0.0176 | 0.1297 | 0.0533 | 0.0630 | 0.0918 | rising |
| ATT | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | flat at zero |
| BUIDL | 0.0384 | 0.0503 | 0.2128 | 0.1145 | 0.0133 | 0.0187 | *last confirmed 07-30, unconfirmed since* |
| PAXG | *not measurable by this adapter* | | | | | | |

**Four assets recorded no secondary trading in any of the six windows**
(RCOIN, ZTLN, CGT, ATT). A single month of silence could be a quiet month; six
is a property of the asset. Of the rest: three rose (FDIT, TBILL, CANA), five
fell (OUSG, USDM, USYC, STBT, HLSCOPE), and USTB/mTBILL moved without a clear
direction. Nothing here shows a market deepening in aggregate.

**Concentration**, same six windows:

| Asset | 04-03 | 05-03 | 06-02 | 07-02 | 08-01 | 08-31 | |
|---|---|---|---|---|---|---|---|
| OUSG | 81.6% | 80.6% | 78.6% | 73.5% | 70.7% | 70.1% | **falling** |
| FDIT | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | flat |
| RCOIN | 97.3% | 97.1% | 97.1% | 97.1% | 97.1% | 97.1% | flat |
| USDM | n/a | n/a | n/a | n/a | n/a | n/a | rebasing guard, all windows |
| ZTLN | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | flat |
| USYC | 99.5% | 99.7% | 99.1% | 97.3% | 99.4% | 99.8% | flat |
| USTB | 81.3% | 88.7% | 85.3% | 88.4% | 87.3% | 84.7% | flat |
| mTBILL | 99.8% | 99.9% | 99.8% | 99.8% | 99.7% | 99.6% | flat |
| TBILL | 99.4% | 99.4% | 98.8% | 98.6% | 96.7% | 97.7% | flat, drifting down |
| STBT | n/a | n/a | n/a | n/a | n/a | n/a | reconciliation warning, all windows |
| HLSCOPE | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | flat |
| CGT | 99.2% | 99.2% | 99.2% | 99.2% | 99.2% | 99.2% | flat |
| CANA | 94.7% | 94.6% | 94.6% | 94.8% | 99.2% | 98.4% | **rising** |
| ATT | 99.2% | 99.2% | 99.2% | 99.2% | 99.2% | 99.2% | flat |
| BUIDL | 84.1% | 83.6% | 82.8% | 83.7% | 83.6% | 81.8% | *last confirmed 07-30, unconfirmed since* |
| PAXG | *not measurable by this adapter* | | | | | | |

**OUSG is the only asset with a clear, sustained direction, and it falls.** A
previous version of this table -- computed before `known_addresses.toml`'s
exclusions existed -- reported OUSG *rising*, 82.4% to 92.9%, and called it
"the one clear mover, and it concentrated." With Flux Finance's fOUSG vault
excluded, the same series **falls**, and falls from the start: every point in
this regenerated run is lower than the corresponding point in the uncorrected
one. The sign of the only non-flat series in the original ten-asset dataset was
an artifact of counting a lending vault as a single large holder. §5a isolates
this precisely -- holding one window fixed and toggling only the exclusion
moves OUSG's top-10 share by 24 points, far more than a window shift alone
could produce -- so the exclusion, not measurement noise, is the cause. Read
correctly, OUSG was deconcentrating throughout while the vault's growing
position made it look like the opposite. That is the strongest single argument
in this document for why the address-versus-investor problem (§5a) is not a
footnote: it did not blur a number, it inverted a published finding.

**CANA rising is new** -- absent from the original ten-asset series, visible
now that the registry and the window both cover 2026 mid-year activity more
fully. Its known issuer address (§8) touches none of these six windows'
transfers, so the rise is not a mint/burn artifact.

BUIDL's series is carried forward from its last successful scan (07-30) rather
than re-measured; no exclusion in `known_addresses.toml` applies to it, so no
change is expected, but that is an expectation, not a confirmation.

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
