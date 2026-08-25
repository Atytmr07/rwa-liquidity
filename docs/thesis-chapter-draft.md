# Measuring Liquidity in Tokenized Real-World Asset Markets: A Verifiable, Keyless Approach

*Draft thesis chapter. Written in English to match the rest of the project's
documentation; translate or adapt headings to your institution's required
format (e.g. Giriş / Literatür Taraması / Yöntem / Bulgular) before
submission. Numbers, tables, and citations below are drawn directly from
`docs/findings.md`, `docs/methodology.md`, and `docs/literature-review.md` in
this repository — if any of those files change, this chapter needs to be
re-synced with them rather than edited independently.*

---

## Abstract

Tokenization is often presented as a mechanism for improving the liquidity of
otherwise illiquid assets — real estate, private credit, Treasury bills — by
placing ownership on a continuously tradable public ledger. This chapter
presents an empirical measurement of that claim against eleven real,
Ethereum-based tokenized real-world assets (RWAs), using an open-source
measurement pipeline (`rwa-liquidity`) built for this purpose. The central
methodological contribution is a strict separation of primary issuance
(minting and redemption) from secondary trading, verified at the level of
individual on-chain transfer events and cross-checked against each asset's
own reported total supply, rather than relying on a third-party data
aggregator. Against ten measurable assets, raw transfer volume is found to
overstate secondary-market liquidity by a factor of 1.0x to 10.8x depending
on the asset, four of ten assets record no peer-to-peer trading at all across
six consecutive monthly windows, and holder concentration is extreme (eight
of ten assets exceed an HHI of 2,500) and largely unchanged over six months.
These findings are consistent with, and extend, contemporaneous academic work
(Mafrur, 2026) that identifies the same primary/secondary conflation as an
open measurement problem; this chapter's contribution is a method that
resolves it for the addressable subset of tokens using the standard ERC-20
issuance convention.

---

## 1. Introduction

### 1.1 Motivation

Real-world asset (RWA) tokenization — representing claims on Treasury bills,
private credit, commodities, and other traditional instruments as tokens on a
public blockchain — has grown from a marginal experiment to a market
institutions now analyze directly (Li, 2025; Bank for International
Settlements, 2026). The stated case for tokenization rests substantially on a
liquidity argument: that moving an asset onto a continuously operating,
programmable settlement layer makes it easier to buy, sell, and price. That
argument is testable, and it has rarely been tested directly against
transaction-level, on-chain data rather than against reported market values
or aggregator-supplied summary statistics.

### 1.2 The measurement problem

Every transfer of an ERC-20 token — the standard almost all tokenized RWA
products use — emits an identical `Transfer` event regardless of its economic
meaning. Three distinct events are indistinguishable at the event level
without further processing:

1. An investor **subscribing** to a fund (the fund mints tokens to them);
2. An investor **redeeming** (tokens are burned or returned to the issuer);
3. Two investors **trading** with each other on a secondary venue or
   peer-to-peer.

Only the third is evidence of a secondary market. A fund that only mints and
redeems can show a large raw transfer volume — every subscription and
redemption is a `Transfer` — while having no functioning secondary market at
all: its investors can only ever transact with the issuer, and if the issuer
stops honoring redemptions, there is no exit. Treating all three as
equivalent, which is the default behavior of most on-chain analytics
platforms and dashboards, systematically overstates liquidity, and does so by
an amount that varies by asset rather than by a constant that could be
corrected after the fact.

### 1.3 Research questions

This chapter addresses three questions empirically:

- **RQ1.** For real, currently-trading tokenized RWA products, how large is
  the gap between raw transfer-based liquidity measures and liquidity
  measures that isolate secondary trading?
- **RQ2.** Is holder concentration in tokenized RWA markets consistent with
  the "broadened ownership" narrative commonly attached to tokenization, and
  does that concentration change over time?
- **RQ3.** Can the primary/secondary distinction, and the holder
  distributions it depends on, be established without relying on a licensed
  or trust-requiring third-party data provider — i.e., can this measurement
  be made independently reproducible and auditable?

### 1.4 Contribution

This chapter's contribution is not a new liquidity metric — the metrics used
(turnover ratio, holder concentration, dormancy) are standard constructs
imported from equity market microstructure (Amihud, 2002; Datar, Naik, &
Radcliffe, 1998) and are named as such rather than presented as novel. The
contribution is methodological: (a) classifying every individual transfer
event as issuance, redemption, or secondary trade using the ERC-20
zero-address convention, rather than treating aggregate transfer volume as a
liquidity proxy; (b) verifying every holder-balance reconstruction this
relies on against the token contract's own `totalSupply()`, so the
distribution is checked rather than assumed; and (c) doing both without an
API key, against public Ethereum infrastructure only, so the result is
independently reproducible by a third party with no data-provider
relationship. §2 situates this against the closest existing academic work;
§3 describes the method; §4 reports findings; §5 discusses limitations; §6
concludes.

---

## 2. Literature Review

*(Condensed from `docs/literature-review.md`, which carries a verification
marker on every source. Quotations in this section are taken from sources
retrieved and read directly on 2026-08-25: Amihud (2002), Aquilina et al.
(2025), Ben-David et al. (2016), Ma et al. (2025), Mafrur (2026), Nassr et
al. (2024), Sai et al. (2021), and the DOJ page. Six sources remain at
abstract or search-summary depth and are cited without quotation — Li (2025),
Mafrur (2025), the ECB bulletin, the New York Fed post, the Nature/HSSC
article, and the DeFi survey literature. Read those before quoting them. §8
of the review file records three errors the unverified first pass contained,
which is the reason this distinction is tracked at all.)*

### 2.1 Tokenization market context

Tokenised money market funds (TMMFs) are described by Aquilina, Lewrick,
Ravenna and Schönleber (2025) as a fast-growing collateral asset within
decentralised finance, subject to liquidity-mismatch risks that mirror those
of conventional money market funds. Their finding bears directly on how the
concentration results in §4.7 should be read: "Based on Ethereum data,
companies operating DeFi protocols are the main investors in BUIDL, the
largest TMMF to date" — so a small, institutional on-chain holder base is the
expected structure for this asset class, not an anomaly of measurement. They
also identify OUSG, likewise in this chapter's sample, as a fund-of-fund
investing through BUIDL.

Li (2025) surveys 180+ RWA products across their industrial organization,
legal structure, regulatory framework, and on-chain activity — the
largest-sample survey of the product space located for this review.

### 2.2 The closest prior empirical work

Two papers by Mafrur (2025, 2026) are the closest existing work to this
chapter, and the second deserves direct engagement rather than a passing
citation.

Mafrur (2025) documents low trading volume, long holding periods, and
limited participation across tokenized real estate, private credit, and
Treasury funds, using aggregate data from the commercial platform RWA.xyz.

Mafrur (2026), "Tokenized but Illiquid? Evidence from Real-World Asset
Markets," is methodologically the nearest prior study: a panel of nine
Ethereum RWA tokens (including BUIDL, OUSG, and PAXG — three of the eleven
assets in this chapter's own sample), 54 token-month observations from
RWA.xyz between December 2025 and May 2026, measuring turnover (monthly
transfer volume over asset value), active-address counts, and an
active-month indicator, with Kruskal–Wallis tests and a fixed-effects panel
regression. The central finding is that liquidity is highly heterogeneous by
asset class — gold-backed tokens (PAXG, XAUT) show the broadest and most
persistent activity, Treasury tokens are intermediate, and private-credit
tokens are weakest — and that raw asset size does not predict liquidity once
class and holder count are controlled for.

Critically, Mafrur (2026) explicitly identifies the measurement gap this
chapter is built to close: "on-chain transfers are not equivalent to
economic trades ... [they] may also include minting and redemption events,
treasury movements, custodial rebalancing, or other operational flows," and
states that the paper's results should be read as "evidence on relative
on-chain activity ... not a complete market microstructure assessment." The
paper measures raw transfer turnover throughout and reports this conflation
as a stated limitation rather than resolving it. This chapter's method
resolves it, for the subset of tokens issuing through the standard ERC-20
zero-address mint/burn pattern, by classifying every transfer event
individually rather than aggregating first and caveating second.

It is also worth stating plainly where the comparison runs the other way:
Mafrur (2026) finds gold-backed tokens the most liquid class in the sample,
and PAXG specifically is the asset this chapter's own method could **not**
measure (§4.5) — its transfer history exceeds what a free, keyless public
endpoint can exhaustively scan. The aggregator-based approach reaches an
asset class the independently-verifiable, on-chain approach cannot, which is
a genuine trade-off between verifiability and coverage rather than a
weakness to elide.

### 2.3 Liquidity as a measured construct

Turnover — shares (or tokens) traded divided by shares outstanding — has an
established lineage as a liquidity proxy independent of the Amihud (2002)
price-impact measure, on the argument that liquidity and trading frequency
are correlated in equilibrium (Datar, Naik, & Radcliffe, 1998, building on
Amihud & Mendelson, 1986). This chapter uses turnover rather than a
price-impact measure because most tokenized RWA products lack a continuous,
liquid secondary price series, which price-impact measures require as an
input and which is exactly what is in question for a fund with a near-zero
secondary market.

### 2.4 Precedent for separating primary and secondary activity

The primary/secondary distinction this chapter treats as central is not novel
outside crypto markets. Ben-David, Franzoni and Moussawi (2016) set out the
ETF case: "Two mechanisms keep ETF prices in line with those of the basket
that they aim to track: primary and secondary market arbitrage." Creation and
redemption occur in the primary market between the fund and authorized
participants — "a small group of institutions that are allowed to trade with
the ETF sponsor directly" — in large blocks, while ordinary investors trade
existing shares on an exchange. That is structurally the same distinction
drawn here between minting/redemption and holder-to-holder transfer, in a
literature with no connection to blockchains.

Within crypto markets, Ma, Zeng and Zhang (2025) are the closest
methodological precedent. They collect "transaction-level data on each
stablecoin creation and redemption event for the six largest fiat-backed
stablecoins" across Ethereum, Avalanche and Tron — deriving primary-market
classification from the ledger rather than from issuer-reported figures, as
this chapter does. They draw the ETF parallel themselves: stablecoin
redemption at $1 "is restricted to a specific set of institutional
arbitrageurs. The vast majority of investors can only trade stablecoins on
secondary market exchanges, similar to investors trading ETF shares on
secondary markets."

Their concentration findings also anticipate §4.7's: USDT has "six
arbitrageurs redeeming stablecoins during the average month," with the
largest accounting for 66% of redemption activity, against 521 for USDC. One
methodological difference is worth naming, because it is the same question
this chapter's `totalSupply()` check exists to answer: they read the chain
through commercial explorers (Etherscan, Snowtrace, Tronscan), whereas the
measurements here query a node directly and verify the reconstruction against
the contract's own supply.

### 2.5 Concentration measurement

Holder concentration is measured here with the Herfindahl-Hirschman Index
(HHI) on the conventional 0–10,000 scale. The 2010 U.S. Horizontal Merger
Guidelines treat an HHI above 2,500 as "highly concentrated"; the 2023
revision lowered that threshold to 1,800 (U.S. Department of Justice,
Antitrust Division; Merger Guidelines § 2.1, 2023). Both thresholds are
reported in §4 to avoid citing a number without a guideline year attached.

Sai, Buckley and Le Gear (2021) provide the contrast baseline for
general-purpose cryptocurrencies, reporting a Gini coefficient of 0.65 for
Bitcoin and a **top-100** address share of 13.52% of supply. The tokenized
RWA products measured in §4.7 show **top-10** shares of 82–100%. The gap is
large enough that the two should not be read on the same scale: an RWA fund's
holder list is structurally closer to a cap table than to a payment network's
address distribution, and this chapter treats the comparison as context
rather than as a like-for-like benchmark.

---

## 3. Methodology

### 3.1 Data source and verification

Measurements are drawn from a single source — direct Ethereum JSON-RPC
queries against a public node — requiring no API key and no data-provider
relationship. For each asset, the adapter replays every `Transfer` event
since contract deployment to reconstruct holder balances, then checks the
reconstruction against the contract's own `totalSupply()` call. Where the two
agree, the distribution is treated as exact; where they disagree (as with the
rebasing token USDM, §4.6), the affected metrics are reported as undefined
rather than published as an estimate. This is the basis for RQ3: the result
does not depend on trusting a third party's aggregation methodology, only on
the correctness of the ERC-20 standard's own accounting invariant — a
non-mint transfer cannot move more value than currently exists in supply —
which is checked mechanically rather than assumed.

### 3.2 Primary/secondary classification

Every transfer is classified using the ERC-20 zero-address convention: a
transfer originating from `0x000...000` is a mint; one directed to it, or to
the conventional burn address `0x000...dEaD`, is a burn; everything else is
classified as secondary unless an issuer treasury address is separately
configured, in which case transfers to or from it are also treated as
primary. This is the single largest source of potential error in the method:
an issuer distributing from an unconfigured treasury address would have its
issuance miscounted as trading. Section 4.4 reports a direct check of this
assumption across the full sample.

### 3.3 Metric definitions

For an asset `a` observed over a half-open window `P = [t₀, t₁)` (default 30
days):

| Metric | Definition | Notes |
|---|---|---|
| Turnover ratio | `V(P, m) / S(t₁)` | `V` is transfer volume under mode `m`; `S(t₁)` is supply at window end |
| Active holder ratio | `\|A(P, m)\| / H(t₁)` | `A` is the set of addresses on either side of a counted transfer |
| Volume per active address | `V(P, m) / \|A(P, m)\|` | |
| Top-10 holder share | `Σ(top 10 balances) / S(t₁)` | Burn addresses excluded; issuer/custody addresses included by default |
| Holder HHI | `10,000 × Σᵢ(bᵢ / S(t₁))²` | Conventional 0–10,000 scale |
| Dormancy | `Σ(balances not in A(P, m)) / S(t₁)` | Share of supply held by addresses inactive in the window |

Every volume-based metric is computed in three modes — `all`, `secondary_
only`, `primary_only` — with `secondary_only` as the default, on the
argument that under-reporting liquidity is the safer failure direction for
published research than over-reporting it. Full derivations, edge cases
(e.g., why the active holder ratio can legitimately exceed 1, why a metric
returns `None` rather than `0.0` when undefined), and the exact provenance
schema returned alongside every value are documented in
`docs/methodology.md`.

### 3.4 Sample construction

The eleven assets were not hand-selected. Every protocol DeFiLlama
categorizes as `RWA` was resolved on-chain via its contract's own `symbol()`
and `name()` calls; approximately three-quarters of the resulting addresses
were governance tokens of RWA-adjacent protocols rather than tokenized assets
themselves and were discarded (the full procedure is recorded in
`src/rwa_liquidity/sources/data/defillama.toml`). The resulting sample spans
Treasury funds, private credit, gold, carbon allowances, and a green bond.

### 3.5 Historical reconstruction for trend analysis

Supply and holder distributions for a past observation window are replayed
from the ledger to that window's end rather than approximated from the
present state — using today's supply to compute an earlier window's turnover
would be a measurement error, not an approximation, since BUIDL's supply
alone varied from 148 million to 225 million tokens across the six trended
windows in this sample.

---

## 4. Findings

*(Full tables and per-asset discussion in `docs/findings.md`; summarized
here.)*

### 4.1 What was observed

Of eleven assets in the registry, ten were measurable; one (PAXG) exceeded
the transfer-log volume a free public RPC endpoint can exhaustively scan and
was excluded rather than estimated (§4.5).

| Asset | Supply | Holders | Transfers | Mint | Burn | Secondary |
|---|---|---|---|---|---|---|
| BUIDL | 224,830,404 | 59 | 731 | 696 | 3 | 32 |
| ZTLN | 150,000,000 | 2 | 0 | 0 | 0 | 0 |
| FDIT | 63,287,229 | 3 | 28 | 9 | 6 | 13 |
| OUSG | 1,455,455 | 53 | 51 | 15 | 15 | 21 |
| USDM | 1,276,201 | 1,587 | 256 | 0 | 1 | 255 |
| RCOIN | 452,083 | 25 | 0 | 0 | 0 | 0 |
| CGT | 100,771 | 272 | 3 | 0 | 0 | 3 |
| CANA | 30,837 | 222 | 102 | 0 | 0 | 102 |
| ATT | 1,825 | 29 | 0 | 0 | 0 | 0 |
| HLSCOPE | 160 | 3 | 2 | 0 | 0 | 2 |

### 4.2 RQ1 — raw volume overstates secondary liquidity, by an asset-specific factor

For BUIDL, the largest fund in the sample, raw ("all-mode") turnover reads
0.2015 — roughly a fifth of outstanding supply moving in 30 days. Restricting
to secondary trades only, turnover falls to 0.0187, a **10.8x** overstatement
in the raw figure. The correction factor is not constant across the sample:
OUSG and FDIT are overstated 2.1x; CANA, HLSCOPE, USDM, and the four
zero-secondary-activity assets are overstated 1.0x (i.e., not at all, because
their activity was already entirely secondary or entirely absent). A model
that calibrates liquidity from raw transfer volume is calibrating from a
figure wrong by a factor between 1x and 11x depending on the specific asset,
which by construction cannot be corrected with a single scalar applied
across the sample.

### 4.3 RQ1 (continued) — four of ten assets show no secondary market at all

ZTLN, RCOIN, ATT, and CGT recorded zero holder-to-holder transfers in the
measurement window; their dormancy is 100%. ZTLN specifically has $150
million in outstanding supply, two holders, and no transfers beyond the
twelve that created it, across its entire on-chain history. Raw transfer
volume under `all` mode also reads 0.0000 for these four — the
primary/secondary split does not change the number for these specific
assets, but it establishes that a *non-zero* reading elsewhere (as with
BUIDL) is not by itself evidence of a functioning secondary market, since a
reader cannot distinguish "0.2015 of raw activity, almost none of it
secondary" from "0.2015 of raw activity, all of it secondary" without the
split.

### 4.4 RQ3 (issuance verification) — the primary/secondary classification checks out

Because the on-chain adapter replays full transfer history rather than a
recent window, it can check whether a token has *ever* minted through the
zero address — and a token with at least one such mint has, by construction,
visible issuance, meaning a window with no mints reflects timing rather than
a hidden treasury distribution. Across all ten measurable assets, every one
mints through the zero address (mint counts over full history ranging from 2
for ZTLN to 11,622 for BUIDL). This converts what would otherwise be a
blanket, unfalsifiable caveat — "issuance might be happening through an
unconfigured treasury address" — into a checked fact for this specific
sample: the secondary-only figures reported here are measurements, not upper
bounds subject to an undetectable issuance leak.

### 4.5 RQ3 (continued) — where verifiability has a cost

PAXG's transfer history exceeds roughly 250,000 logs, past what a free
public RPC endpoint will serve for an exhaustive scan; it is reported as
*not measurable*, deliberately distinct from a measured value of zero. This
is the direct counterpart to the finding noted in §2.2: the same asset class
an aggregator-based study (Mafrur, 2026) finds most liquid is the one this
chapter's verifiable, keyless method cannot reach. Read together, the two
findings suggest a general trade-off rather than a flaw specific to either
method: exhaustive, independently-verifiable on-chain reconstruction is
tractable exactly for the thin, low-activity assets whose liquidity is most
in question, and intractable for the actively-traded assets a licensed
aggregator can summarize but a third party cannot independently re-derive
from public infrastructure alone.

### 4.6 A verification failure that improved the result

USDM is a rebasing token: holder balances change without emitting `Transfer`
events. The ledger reconstruction disagreed with the contract's own
`totalSupply()` by a wide margin (439 addresses reconstructed to a negative
balance), and the concentration and dormancy metrics for USDM are reported
as undefined rather than as numbers. Before this check was added, the same
data produced a top-10 holder share of 2.21 and a dormancy of 1.53 — both
above the mathematical maximum of 1.0 for a share. This is offered as direct
evidence for the value of §3.1's verification step: an aggregator without an
equivalent supply-reconciliation check would have no signal that a
plausible-looking distribution was wrong.

### 4.7 RQ2 — concentration is extreme and largely static over six months

Eight of the ten measurable assets exceed an HHI of 2,500 (the 2010 DOJ/FTC
"highly concentrated" threshold); the same eight also clear the stricter
1,800 threshold introduced in the 2023 revision. Top-10 holder share exceeds
92% for nine of ten assets. Tracked across six consecutive 30-day windows
(with supply and holder distributions reconstructed at each window's end,
per §3.5, rather than taken from the present), top-10 concentration moved by
less than one percentage point for seven of nine measurable assets over six
months; OUSG is the one clear mover, rising from 82.4% to 92.9%. Secondary
turnover over the same six windows shows no aggregate trend: two assets rose,
four fell, four remained flat at zero in every window. On this sample, over
six months, tokenization did not measurably broaden ownership.

---

## 5. Discussion and Limitations

Several limitations bound how far these findings should be generalized, and
are stated here rather than left implicit.

**On-chain visibility is not market visibility.** Trading settled off-chain —
inside a custodian's internal register, on a centralized venue, or via
book-entry at a transfer agent — is invisible to this method entirely. An
actively-traded asset whose trades settle off-chain would read as dormant.

**Addresses are not investors.** Concentration figures are computed over
addresses. A custodian holding for a thousand retail clients behind one
address is indistinguishable here from a single large holder, and one
investor split across ten addresses is indistinguishable from ten separate
investors. Both directions of error are possible and neither is corrected;
HHI and top-10 share should be read as bounds rather than precise investor
concentration.

**Single-chain scope.** All measurements are Ethereum-only. BUIDL, for
example, also exists on Aptos, Solana, Avalanche, and several other chains,
and roughly a third of its total value sits outside Ethereum; cross-chain
bridging is indistinguishable from an ordinary transfer under this method.
This is the same scope restriction Mafrur (2026) imposes deliberately, and
is a shared limitation of on-chain, single-chain methods generally rather
than one specific to this implementation.

**Sample size and time depth.** Ten measurable assets and six monthly
windows support a directional finding, not a growth-rate estimate. The trend
results in §4.7 are reported as direction only for this reason.

**Two of five data adapters remain unverified against live APIs.** The
keyless on-chain adapter that produced every finding in §4 has been run
live; two keyed adapters (against rwa.xyz and Dune Analytics), included for
architectural completeness and cross-source reconciliation, have been tested
only against documented response shapes because API access was either
unavailable (rwa.xyz's API is gated behind an Enterprise-tier commercial
plan with no published price) or unused at time of writing.

---

## 6. Conclusion and Future Work

Measured directly from public Ethereum data, without any commercial data
license, ten real tokenized RWA products show that raw transfer volume
overstates secondary-market liquidity by a factor that varies by asset
(1.0x–10.8x), that four of ten have no secondary trading at all across a
six-month observation period, and that holder concentration is both extreme
and largely static over the same period. These findings are consistent with
concurrent academic work (Mafrur, 2025, 2026) documenting the same general
pattern from an independent, differently-sourced sample, and extend it
methodologically by resolving — for tokens using the standard ERC-20
issuance convention — the primary/secondary conflation that Mafrur (2026)
explicitly leaves as an open limitation.

Mafrur (2026) names three directions for future research: longer token
histories, richer concentration data, and broader multi-chain coverage. This
chapter's method already addresses the first two directly — full-history
ledger reconstruction and verified concentration metrics are exactly what it
computes — and shares the third as an open limitation rather than a
contribution: extending the method to non-EVM chains (Solana, Aptos), where
a meaningful share of tokenized RWA value already sits, is the most direct
next step for this line of work.

---

## References

*(Format lightly for your institution's citation style before submission.
Verification status per source is in `docs/literature-review.md`.)*

- Amihud, Y. (2002). Illiquidity and stock returns: cross-section and
  time-series effects. *Journal of Financial Markets*, 5, 31–56.
- Aquilina, M., Lewrick, U., Ravenna, F., & Schönleber, L. (2025). The rise of
  tokenised money market funds. *BIS Bulletin*, No. 115, 26 November 2025.
- Ben-David, I., Franzoni, F., & Moussawi, R. (2016). Exchange traded funds
  (ETFs). NBER Working Paper 22829.
- Datar, V. T., Naik, N. Y., & Radcliffe, R. (1998). Liquidity and stock
  returns: an alternative test. *Journal of Financial Markets*, 1(2), 203–219.
- Li, J. (2025). Current landscape of the real-world asset (RWA)
  tokenization ecosystem. SSRN Working Paper 6077226, George Mason University.
- Ma, Y., Zeng, Y., & Zhang, A. L. (2025). Stablecoin runs and the
  centralization of arbitrage. NBER Working Paper 33882, May 2025.
- Mafrur, R. (2025). Tokenize everything, but can you sell it? RWA liquidity
  challenges and the road ahead. arXiv:2508.11651.
- Mafrur, R. (2026). Tokenized but illiquid? Evidence from real-world asset
  markets. arXiv:2606.01131.
- Nassr, I. K., Kostika, E., & Melachrinos, A. (2024). Concentration of DeFi's
  liquidity. OECD. https://doi.org/10.1787/4ed08440-en
- Sai, A. R., Buckley, J., & Le Gear, A. (2021). Characterizing wealth
  inequality in cryptocurrencies. *Frontiers in Blockchain*, 4.
  https://doi.org/10.3389/fbloc.2021.730122
- U.S. Department of Justice, Antitrust Division. Herfindahl-Hirschman
  Index (page updated 17 January 2024), citing U.S. Department of Justice &
  FTC, *Merger Guidelines* § 2.1 (2023).
  justice.gov/atr/herfindahl-hirschman-index
