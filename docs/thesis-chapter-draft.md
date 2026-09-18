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
on the asset -- rising to 39.0x for one asset (USYC) once the registry is
widened to fourteen -- four of ten assets record no peer-to-peer trading at
all across six consecutive monthly windows, and holder concentration is
extreme (eight of ten assets exceed an HHI of 2,500; eleven of fourteen on
the widened registry) and largely static over six months. One exception
demonstrates why the method's holder-side verification matters as much as
its transfer-side classification: the sample's one clear, sustained
concentration trend was found to have the wrong sign, reporting one asset
(OUSG) as concentrating when a lending vault miscounted as a single large
holder was excluded and the corrected series instead falls throughout the
same six months. These findings are consistent with, and extend,
contemporaneous academic work (Mafrur, 2026) that identifies the same
primary/secondary conflation as an open measurement problem; this chapter's
contribution is a method that resolves it for the addressable subset of
tokens using the standard ERC-20 issuance convention, and that the same
address-aggregation failure mode this chapter checks for is large enough,
in at least one case, to invert a published trend's direction rather than
merely shift its magnitude.

---

## 1. Introduction

### 1.1 Motivation

Real-world asset (RWA) tokenization — representing claims on Treasury bills,
private credit, commodities, and other traditional instruments as tokens on a
public blockchain — has grown from a marginal experiment to a market
institutions now analyze directly (Li, 2025; Aquilina et al., 2025). The
stated case for tokenization rests substantially on a
liquidity argument: that moving an asset onto a continuously operating,
programmable settlement layer makes it easier to buy, sell, and price. That
argument is testable, and it has rarely been tested directly against
transaction-level, on-chain data rather than against reported market values
or aggregator-supplied summary statistics.

Mafrur (2026) tests it directly against on-chain activity and names the
limitation this chapter is built to close: on-chain transfers are not
equivalent to economic trades, since a transfer may record a subscription, a
redemption, a treasury movement, or custodial rebalancing rather than a
trade between two investors. That paper states the conflation as an open
measurement problem rather than resolving it, and measures raw transfer
turnover throughout. This chapter closes that specific gap by classifying
every transfer event individually rather than aggregating first and
caveating second: for BlackRock's BUIDL, the largest fund in this chapter's
sample, 696 of 731 transfers in a single 30-day window were issuance, not
trading, so raw turnover overstates the fund's actual secondary-market
activity by a factor of 10.8. The correction is asset-specific rather than a
fixed discount — §4.2 reports a factor as high as 39 elsewhere in the
sample — and it is not free: §4.5 reports the one asset class this chapter's
verifiable, keyless method cannot reach, which happens to be the class
(gold-backed tokens) Mafrur's own results find most liquid. That is a real
cost of verifiability, stated here rather than left for a reader to
discover in the limitations section.

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

This chapter addresses two questions empirically:

- **RQ1.** For real, currently-trading tokenized RWA products, how large is
  the gap between raw transfer-based liquidity measures and liquidity
  measures that isolate secondary trading?
- **RQ2.** Is holder concentration in tokenized RWA markets consistent with
  the "broadened ownership" narrative commonly attached to tokenization, and
  does that concentration change over time?

Both are answered under a **binding methodological constraint rather than a
third research question**: every figure reported here must be derivable from
public Ethereum infrastructure alone, with no licensed data feed and no API
key, and every holder distribution must be checked against the token
contract's own `totalSupply()` rather than accepted on a provider's word.
This is a constraint on admissible evidence, not an empirical question — the
answer to "can this be built" is settled by the working implementation, and
the interesting content lies in what the constraint costs and what it buys.
§3.1 states how it is enforced, §4.4 reports what the verification step
actually caught, and §4.5 reports the one asset the constraint puts out of
reach entirely.

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

One further implication follows from combining the two studies, and it is
stated here as an implication rather than a tested claim: Mafrur (2026)
measures liquidity from raw transfer turnover and explicitly flags, without
correcting for, the primary/secondary conflation this chapter resolves; its
finding that Treasury-token turnover is "intermediate" between gold-backed
and private-credit tokens is therefore a finding about *raw* turnover for
that class. This chapter's own sample includes several Treasury-fund tokens
(BUIDL, OUSG, USTB, USYC, mTBILL, TBILL) for which raw turnover overstates
secondary-market turnover by factors ranging from 2.0x to 39.0x (§4.2). The
two studies do not share a sample or window, so this is not a direct
re-measurement of Mafrur's result — but it does mean that his Treasury-token
turnover figures, uncorrected for issuance, most plausibly sit closer to the
private-credit tier than the "intermediate" label suggests once the same
correction this chapter applies is taken into account. That reclassification
is left as a testable claim for future work with a shared sample, not
asserted here as established.

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
rather than published as an estimate. This is how §1.3's methodological
constraint is enforced: the result
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

**Notation.** Fix an asset $a$ and a half-open observation window
$P = [t_0, t_1)$ (default 30 days). Let $\mathcal{T}(P)$ be the set of
`Transfer` events emitted by $a$'s contract with block timestamp in $P$. Each
event $\tau \in \mathcal{T}(P)$ carries a sender $s(\tau)$, a recipient
$r(\tau)$, a value $v(\tau) \ge 0$ in the token's own units, and a class
$k(\tau) \in \{\textsf{mint}, \textsf{burn}, \textsf{secondary},
\textsf{unclassified}\}$ assigned by §3.2. A *mode* $m$ is a subset of those
classes; write

$$\mathcal{T}_m(P) = \{\tau \in \mathcal{T}(P) : k(\tau) \in m\}$$

for the counted events, with the three modes used here being
$m_{\text{all}} = \{\textsf{mint}, \textsf{burn}, \textsf{secondary}\}$,
$m_{\text{sec}} = \{\textsf{secondary}\}$, and
$m_{\text{pri}} = \{\textsf{mint}, \textsf{burn}\}$.

Let $\mathcal{B}$ denote the burn addresses (the zero address and the
conventional `0x…dEaD`), and $\mathcal{X}$ the excluded contract addresses of
§5 — DeFi contracts confirmed to aggregate many end-holders behind a single
balance. Let $H(t_1)$ be the set of addresses holding a non-zero balance at
$t_1$, with $b_i(t_1)$ the balance of address $i$, and let

$$S(t_1) = \sum_{i \in H(t_1)} b_i(t_1)$$

be total supply at the window's end, reconstructed from full transfer history
and checked against the contract's own `totalSupply()` per §3.1.

**Counted volume and active addresses.**

$$V(P, m) = \sum_{\tau \in \mathcal{T}_m(P)} v(\tau)
\qquad
A(P, m) = \bigl(\{s(\tau) : \tau \in \mathcal{T}_m(P)\} \cup
                \{r(\tau) : \tau \in \mathcal{T}_m(P)\}\bigr) \setminus \mathcal{B}$$

**The six metrics.** Let $\tilde{H}(t_1) = H(t_1) \setminus (\mathcal{B} \cup \mathcal{X})$
be the holder set after exclusions. $\tilde{H}(t_1)$ narrows which addresses
are *eligible to be counted as a holder* — ranked for Top-$n$, summed into
HHI, checked for dormancy — but it does **not** change the denominator: every
share-valued metric below divides by $S(t_1)$, the full reconstructed supply,
never by a re-summed total of $\tilde{H}(t_1)$ alone. An earlier draft of
this section defined a separate excluded-adjusted denominator
$\tilde{S}(t_1) = \sum_{i \in \tilde{H}(t_1)} b_i(t_1)$ and used it here.
That was wrong, caught by directly testing the implementation rather than by
inspection (§5 reports how). The correct, and actually implemented, reading
is deliberate rather than an oversight. An excluded DeFi contract's balance
is still real supply in existence, and shrinking the denominator to match a
shrunk numerator would let an exclusion manufacture certainty about
concentration that the data does not support. The ZTLN case in §5 shows
this directly: excluding a Balancer pool holding two-thirds of supply left
one confirmed investor holding *one third of total supply*, not "all of
what remains."

$$\text{Turnover}(P, m) = \frac{V(P, m)}{S(t_1)}
\qquad
\text{ActiveHolderRatio}(P, m) = \frac{\lvert A(P, m) \rvert}{\lvert H(t_1) \rvert}$$

$$\text{VolumePerActive}(P, m) = \frac{V(P, m)}{\lvert A(P, m) \rvert}
\qquad
\text{Top-}n\text{Share}(t_1) = \frac{1}{S(t_1)} \sum_{i \in \tilde{H}_{(n)}(t_1)} b_i(t_1)$$

$$\text{HHI}(t_1) = 10^4 \sum_{i \in \tilde{H}(t_1)} \left( \frac{b_i(t_1)}{S(t_1)} \right)^{\!2}
\qquad
\text{Dormancy}(P, m) = \frac{1}{S(t_1)} \sum_{i \in \tilde{H}(t_1) \setminus A(P, m)} b_i(t_1)$$

where $\tilde{H}_{(n)}(t_1) \subseteq \tilde{H}(t_1)$ denotes the $n$ addresses
with the largest balances, $n = 10$ by default.

**Domain notes.** $\text{ActiveHolderRatio}$ is *not* bounded above by 1: an
address may trade during $P$ and hold nothing at $t_1$, so it enters the
numerator without entering the denominator. Values above 1 are reported with
a warning rather than clamped, since the churn they indicate is itself a
liquidity signal. $\text{Top-}n\text{Share}$ and $\text{Dormancy}$ *are*
bounded in $[0, 1]$ by construction — each numerator is a sum over some
subset of $H(t_1)$, and $S(t_1)$ sums over all of $H(t_1)$, so a computed
value outside that interval proves the holder reconstruction disagrees with
reported supply; the metric is then returned as undefined rather than
published (this is the guard that fires on USDM, §4.6). Every metric is
undefined when its denominator is zero — an empty $A(P, m)$, or
$S(t_1) = 0$ — and returns $\varnothing$ rather than $0$, since "no
denominator" and "measured zero" are different findings.

Every share-valued metric divides by the same, unexcluded $S(t_1)$ for the
same reason: a DeFi vault's holdings are part of supply in existence, and
netting an exclusion out of the denominator as well as the numerator would
manufacture certainty about the excluded balance's concentration — zero
information, reported as zero risk — that the exclusion itself does not
provide. Concretely, this means excluding a large, uninformative holder does
not necessarily *raise* the reported concentration of the rest; it can lower
it, if what is excluded was large enough that the remaining confirmed
investors turn out to hold a smaller share of the whole than their share of
each other implied. §5's ZTLN case is exactly this.

Every volume-based metric is computed in all three modes, with
$m_{\text{sec}}$ as the default, on the argument that under-reporting
liquidity is the safer failure direction for published research than
over-reporting it. Full derivations, further edge cases, and the exact
provenance schema returned alongside every value are documented in
`docs/methodology.md`.

### 3.4 Sample construction

The eleven assets were not hand-selected. Every protocol DeFiLlama
categorizes as `RWA` was resolved on-chain via its contract's own `symbol()`
and `name()` calls; approximately three-quarters of the resulting addresses
were governance tokens of RWA-adjacent protocols rather than tokenized assets
themselves and were discarded (the full procedure is recorded in
`src/rwa_liquidity/sources/data/defillama.toml`). The resulting sample spans
Treasury funds, private credit, gold, carbon allowances, and a green bond.

**Second pass (2026-08-27).** The same procedure was re-run against the
category's current membership, specifically to test whether the first pass's
sample was unrepresentatively thin. Seven further candidates were resolved
on-chain and five were added: USYC (Circle), USTB (Invesco), mTBILL (Midas),
TBILL (OpenEden) and STBT (MatrixDock). Two were excluded for exceeding the
scan ceiling, and are discussed in §4.5. The resolution step earned its place
here as well: one address, approached under the label "Superstate USTB",
returned `name() = "Invesco Short Duration US Government Securities Fund"` and
is recorded under the issuer its contract actually names. The findings reported
in §4 predate this expansion and are stated over the original ten measurable
assets; the enlarged registry is available for replication and is noted here so
the sample's construction is not mistaken for a fixed list.

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

### 4.2 RQ1 — raw volume against secondary-only volume

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

**The widened registry pushes the upper bound considerably higher.** Measured
on 2026-08-28 across fourteen assets (`docs/findings.md` §2), Circle's USYC
returns an overstatement factor of **39.0x** — raw turnover of 7.99 against
secondary-only turnover of 0.2048. Seventy-eight of its hundred transfers in
the window were mint or burn. A product whose published on-chain volume reads
as eight complete turns of supply per month, and whose actual investor-to-
investor trading is a fifth of one turn, is a starker instance of the same
mechanism than BUIDL, and it was not visible in the original ten-asset sample.
The claimed range is therefore **1x to 39x on the observed sample**, and should
be read as a lower bound on the dispersion rather than as its limit: nothing in
the method establishes that 39x is extreme for the population, only that it
occurs.

**On what this result is, and is not, surprising.** That BUIDL exhibits
almost no secondary trading should not be read as a finding about BUIDL's
design being defective — it is a regulated, permissioned money-market-fund
share whose transfer function enforces a whitelist of KYC-verified investors.
Subscription and redemption through the issuer *are* the intended mechanism;
free peer-to-peer circulation on a public venue is neither expected nor, for
most of these products, permitted. A finance reader who knows the instrument
class will find a low secondary-turnover figure for an institutional
tokenized MMF unremarkable in itself.

The contribution here is therefore not the discovery that permissioned funds
trade little. It is that the *published, widely-cited* on-chain figures for
these products do not distinguish the two mechanisms at all, so a reader
outside the instrument class — and, more consequentially, a model calibrated
on those figures — cannot tell an asset whose 0.2015 of monthly activity is
mostly subscription flow from one whose 0.2015 is mostly investor-to-investor
trading. Both read identically on a dashboard. The 10.8x figure is the size of
that ambiguity for one asset, and §4.3 shows the same split distinguishes
"thin but functioning" from "no secondary market whatsoever," which is a
distinction raw volume cannot express even in principle.

### 4.3 RQ1 (continued) — assets with zero secondary activity

ZTLN, RCOIN, ATT, and CGT recorded zero holder-to-holder transfers in the
measurement window; their dormancy is 100%. ZTLN specifically has $150
million in outstanding supply and no transfers beyond the twelve that
created it, across its entire on-chain history. Its holder count is stated
here as one *confirmed investor*, not two: checked against Etherscan's own
address labels (§5), one of ZTLN's two nominal holders is `Balancer: Vault`,
a DeFi pool contract, holding two-thirds of supply on behalf of an unknown
number of liquidity providers. The confirmed investor holds the remaining
third and has never moved it; whether anything backed by the pooled
two-thirds has traded is not something this method can see, since an AMM
position can change hands without the underlying token moving. Raw transfer
volume under `all` mode also reads 0.0000 for these four — the
primary/secondary split does not change the number for these specific
assets, but it establishes that a *non-zero* reading elsewhere (as with
BUIDL) is not by itself evidence of a functioning secondary market, since a
reader cannot distinguish "0.2015 of raw activity, almost none of it
secondary" from "0.2015 of raw activity, all of it secondary" without the
split.

### 4.4 Checking the zero-address assumption against full transfer history

Because the on-chain adapter replays full transfer history rather than a
recent window, it can check whether a token has *ever* minted through the
zero address. Across all ten measurable assets, every one does (mint counts
over full history ranging from 2 for ZTLN to 11,622 for BUIDL). This rules out
one specific failure: an asset that issues *exclusively* through an
unconfigured treasury and would therefore show zero zero-address mints, ever,
under this method.

It does not rule out the narrower and more consequential version of the same
risk — an asset that mints its initial tranche through the zero address and
distributes some later portion of supply from a treasury address instead,
which this method would classify as ordinary secondary trading. An earlier
draft of this chapter argued that at least one historical zero-address mint
converts the treasury-distribution caveat into "a checked fact for this
specific sample." That argument does not hold: a single mint proves the asset
*can* issue through the zero address, not that everything counted as
secondary here *did* trade rather than get distributed later through an
unconfigured address. The correction matters most for the assets with
meaningful secondary-classified volume, since an asset with zero secondary
transfers has nothing for this failure mode to inflate: BUIDL (32 secondary
transfers), USDM (255), CANA (102), OUSG (21).

Ruling this out for a specific asset requires that asset's actual treasury or
transfer-agent address, supplied through `issuer_addresses`
(`known_addresses.toml`, §5). Rather than leave that as an open caveat, a
targeted search was run on 2026-08-27 for the on-chain signature of a
distributor — an address that took delivery of a mint from the zero address and
then sent onward to many distinct recipients — across the assets whose windows
classified every transfer as secondary. Two candidates were confirmed by
Etherscan's own address labels, one was rejected for lacking any:

| Asset | Address | Label | Status |
|---|---|---|---|
| CANA | `0xccadea5c…` | "Maseer: Deployer" | **confirmed**, 113 distinct recipients |
| CGT | `0x6522b05f…` | "CACHE Gold: Old Backed Treasury" | **confirmed**, dormant since 2021 |
| OUSG | `0x3d85c41e…` | *(none)* | **rejected** — behaviour only, no label |

The measured impact is small and is reported as such. CANA's issuer address
appears in 146 of that token's 6,157 lifetime transfers but in **zero** of the
transfers inside the measurement window, so §4.2's figures do not move; it
appears in 11 of the 1,885 transfers spanning the six trend windows (0.6%).
CGT's treasury has been inactive since 2021-10-30, roughly five years before
the window, and touches none of the transfers reported here. For OUSG, where
no address could be confirmed, the exposure is bounded instead of resolved: 3
of its 50 window transfers involve the rejected candidate, so at most 3 of 50
could be misclassified on that account.

The zero-address check therefore establishes that the classification's
foundational assumption is not violated in the one way full history can detect,
and the search above bounds the residual risk at a few transfers per asset for
this sample. Neither is a proof that every secondary-classified transfer here
is genuinely secondary, and that is not claimed.

### 4.5 What the free-endpoint constraint costs

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

The second pass over DeFiLlama's RWA category (§3.4) met the same boundary
with different assets: of seven candidates resolved on-chain, five were added
to the registry and two — Ethena's USDtb (approximately 450,000 transfer logs)
and Usual's USD0 (approximately 475,000) — were excluded for the same reason as
PAXG. Both are DeFi-native and heavily traded, which is precisely the profile
that would most enrich the sample and precisely what a free endpoint cannot
reconstruct.

### 4.5a Testing the boundary from the other side: PAXG through a paid source

The §4.5 constraint invites an objection that should be stated at full
strength: if the method reaches only assets thin enough to scan exhaustively,
then the finding that these assets barely trade may describe the method's
reach rather than the market, making §4.2 and §4.7 close to circular.

Answering it requires measuring an asset from beyond the boundary and seeing
whether the method still discriminates. PAXG was therefore measured over the
identical 30-day window using Dune Analytics, with the primary/secondary
classification re-expressed in SQL — the same two rules (zero address, burn
address), a different execution engine and a different underlying index. The
reconstruction was subjected to the same invariant as every other figure in
this chapter: reconstructed balances sum to 441,940.72 PAXG against the
contract's own `totalSupply()` of 441,941.91, a discrepancy of 1.19 tokens or
**0.00027%**.

| | PAXG (Dune) | The ten permissioned assets (`evm_rpc`) |
|---|---|---|
| Holders | 84,962 | 2 – 1,587 |
| Secondary transfers in window | 135,145 | 0 – 255 |
| Turnover, secondary-only | 0.7172 | 0.0000 – 1.0767 |
| Overstatement factor | 1.03x | 1.0x – 10.8x |
| Top-10 holder share | 34.0% | above 92% for nine of ten |
| Holder HHI | 378 | 1,385 – 9,362 |
| Dormancy | 73.0% | 0% – 100% |

**The method discriminates.** Applied to a tokenized RWA that genuinely trades,
it reports one: an HHI of 378 sits below even the 1,500 "unconcentrated" floor,
against a sample in which eight of ten exceed 2,500; a top-10 share of 34%
against 92%-plus for nine of ten. The instrument is not constructed to find
illiquidity, and it does not find it here.

Two consequences follow, and both **narrow** this chapter's claims rather than
widening them:

1. **The primary/secondary correction is near-irrelevant where a real secondary
   market exists.** PAXG's overstatement factor is 1.03x, the smallest measured
   anywhere in this study: only 37 of 135,182 transfers in the window were
   issuance. §4.2's finding is therefore properly scoped as *raw volume
   overstates secondary liquidity for permissioned funds that issue and redeem*,
   not for tokenized RWAs generally.
2. **Tokenization is capable of producing broad ownership; these funds do not
   exhibit it.** PAXG is a tokenized real-world asset with 84,962 holders and
   low concentration. §4.7's concentration result is thus a finding about
   regulated, whitelist-gated fund shares as an instrument class — a narrower
   and more defensible claim than one about tokenization as such.

**Limits of this test.** These figures traverse a different code path from every
other number reported here: Dune's indexed event tables queried in SQL, rather
than this chapter's own log replay. The supply cross-check is a genuine
verification but a single one, not the full per-asset reconciliation §3.1
performs. PAXG remains outside what a third party can reproduce without a data
provider relationship, which is the actual substance of the §4.5 boundary. One
control case also cannot establish that every asset past the boundary behaves
as PAXG does; it establishes only that the method's findings are not an artifact
of which assets it can reach.

### 4.6 The USDM rebasing check

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

### 4.7 RQ2 — holder concentration, cross-sectional and over six months

Eight of the ten measurable assets exceed an HHI of 2,500 (the 2010 DOJ/FTC
"highly concentrated" threshold); the same eight also clear the stricter
1,800 threshold introduced in the 2023 revision. Top-10 holder share exceeds
92% for nine of ten assets.

**This is weaker over the widened registry than a factor of two, and the
weakening is informative.** Re-measured on 2026-08-28 across fourteen
assets, eleven rather than eight of ten exceed 2,500, and twelve of fourteen
clear the stricter 1,800 threshold. Only OUSG (779) and Invesco's USTB
(1,067) fall below 1,800; mTBILL (2,052) falls short of 2,500 but still
clears 1,800, so it sits in neither "below the line" count despite being one
of the three lowest HHI values in the sample. Two of those three are assets
the second registry pass added, and OUSG clears neither line unless its
lending vault is excluded (§5). The qualitative finding survives — most of
these assets are concentrated by any antitrust standard, more so than a
naive reading of "nine of fourteen" would suggest — but the original
sample's near-uniformity was partly an artifact of its composition: ten assets
that happened to share an instrument type. A tokenized RWA can have a broad
holder base, as PAXG (§4.5a) shows at the extreme and USTB shows within the
keyless method's own reach.

Tracked across six consecutive 30-day windows
(with supply and holder distributions reconstructed at each window's end,
per §3.5, rather than taken from the present), and **regenerated 2026-08-31
over the widened fourteen-asset registry** with `known_addresses.toml`'s
exclusions in effect throughout (`docs/findings.md` §7b has both full tables):
most series are flat. OUSG is the one asset with a clear, sustained direction
across all six windows, and CANA shows a late rise not present in the original
ten-asset series. Secondary turnover over the same six windows shows no
aggregate trend: four assets recorded no secondary trading in any window
(RCOIN, ZTLN, CGT, ATT), three rose, five fell, and two moved without a clear
direction. On this sample, over six months, tokenization did not measurably
broaden ownership.

**A correction, and the reason it matters.** An earlier version of this section
reported OUSG as "the one clear mover," rising from 82.4% to 92.9%, and read
that as concentration increasing. That series was computed before the
holder-side exclusions of §5 existed. Regenerated with Flux Finance's fOUSG
lending vault excluded, OUSG instead **falls, 81.6% to 70.1%** — the direction
of the only sustained-direction series in the dataset reverses, and every
point in the corrected series sits below the corresponding point in the
uncorrected one.

The confound is isolable. Two things differ between the two runs: the exclusion,
and the window positions, which slide with the present. Holding the window fixed
and toggling only the exclusion moves OUSG's top-10 share from 94.2% to 70.0%,
a 24-point swing that no five-week shift in window placement could produce. The
exclusion is the cause; OUSG was deconcentrating while a growing vault position
made it appear to concentrate.

This is offered as the clearest available evidence that the address-versus-
investor limitation stated in §5 is not a formality. It did not blur a
coefficient at the margin: it inverted the sign of a reported finding. Any
study computing holder concentration from raw on-chain balances, without
identifying which addresses are contracts aggregating many end-holders, is
exposed to the same failure — and the failure is silent, since a wrong series is
as smooth and as plausible as a right one.

BUIDL could not be re-measured on the regenerated run (the public endpoint
refused the scan partway, §4.5), so its previous flat reading stands
unconfirmed. No exclusion applies to BUIDL, so its figure is not expected to
move — an expectation, not a verification.

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
investors. This is not a hypothetical failure mode: checking every
measurable asset's top holders against Etherscan's own contract labels
(2026-08-26 through 2026-09-01, in three passes as the registry grew) found,
for five of the fourteen, an address that is by construction many
end-holders behind one balance rather than one investor. OUSG's largest
holder, at roughly 25% of supply, is `Flux Finance: fOUSG Token`, a lending
vault that accepts OUSG as collateral; USDM's largest holder is Mountain
Protocol's own `wUSDM` wrapper contract; CANA's top holders include both an
asset-specific Uniswap V2 pool and Uniswap V4's global pool-manager contract;
USYC's largest holder is Usual's `DaoCollateral` treasury, backing its
stablecoin's supply; USTB's third-largest is Midas's `Instant Redemption
Vault`, the liquidity behind another registry asset's (mTBILL's) instant
redemptions; and — the case that most changes a reported finding rather than
just a number — ZTLN's larger of its two nominal holders is `Balancer:
Vault`, holding two-thirds of its supply. These are recorded, with their
citation, in `known_addresses.toml`
(`src/rwa_liquidity/sources/known_addresses.py`) and excluded from this
chapter's top-10-share, HHI, and dormancy figures by default when computed
through the CLI (`docs/methodology.md` §2.4).

**The consequences are not marginal, and not always a change in magnitude.**
Excluding OUSG's vault moves its HHI from 1,422 to 779 — across the DOJ/FTC
"highly concentrated" threshold — and its top-10 share from 94.2% to 70.0%.
More seriously, it reverses the direction of the only non-flat trend series
in the study (§4.7): OUSG reads as concentrating with the vault counted and
as deconcentrating without it. USYC moves further still: excluding Usual's
treasury drops its top-10 share by 31.7 points and nearly halves its HHI
(§4.5a's full isolated-diff table is in `docs/findings.md` §5a). ZTLN's case
is different in kind, not degree: it is one of the four assets §4.3 reports
as having no secondary market, and the two-holder framing used there and in
this chapter's abstract is itself imprecise once one of the two is confirmed
to be a pool contract rather than an investor. Every share-valued metric in
this method divides by an asset's full total supply regardless of exclusion
(§3.3), so removing the pool does not inflate ZTLN's remaining investor to
"100% concentrated" — it correctly reports that one confirmed investor holds
33.3% of total supply and says nothing about the rest, which is a narrower
and more defensible claim than either the original "two holders" framing or
a naive full-renormalization would produce. A study that computes holder
concentration from raw balances, without separating contracts that aggregate
many end-holders from individual investors, is exposed to a failure that can
be large, silent, and — as ZTLN shows — not always in the direction of
overstating concentration.

The correction is, as of this writing, applied to every measurable asset in
the registry, but it is bounded by what an explorer label can identify: an
unlabeled contract, or a labeled one this project's search did not think to
check, is not caught by this method, and the other nine assets recorded no
DeFi-aggregation contract among their top holders only in the sense that
none was *found*, which is not the same guarantee as none *existing*. HHI
and top-10 share should still be read as bounds rather than as precise
investor concentration wherever this file's citation is silent.

**Single-chain scope.** All measurements are Ethereum-only. BUIDL, for
example, also exists on Aptos, Solana, Avalanche, and several other chains,
and roughly a third of its total value sits outside Ethereum; cross-chain
bridging is indistinguishable from an ordinary transfer under this method.
This is the same scope restriction Mafrur (2026) imposes deliberately, and
is a shared limitation of on-chain, single-chain methods generally rather
than one specific to this implementation.

**Sample size and time depth.** Ten measurable assets and six monthly
windows support a directional finding, not a growth-rate estimate. The trend
results in §4.7 are reported as direction only for this reason. Four of the
ten recorded no secondary transfers at all, so the volume-based results rest
in practice on six assets and the trend results on fewer. The registry has
since been widened to sixteen entries (§3.4) and PAXG measured as a control
case (§4.5a), which addresses the question of whether the sample was
*systematically* thin, but does not convert ten observations into a panel.
Claims here are stated for this sample and this window rather than for
tokenized RWA markets in general.

This is also why §4.7's six-window series are read by eye ("rising,"
"falling," "flat") rather than tested for statistical significance: six
points per asset is too short a series to fit a trend model or compute a
confidence interval that would mean anything, and this chapter's stated
contribution (§1.4) is a verified measurement method, not a set of
inferential claims about the population of tokenized RWAs — unlike Mafrur
(2026), whose fixed-effects panel regression is doing exactly that
inferential work over a longer, differently-sourced series. Reading six
points by eye is a real limitation of what can be claimed from them, not an
oversight; it is the reason every trend claim here is stated as a direction
observed in this sample, never as a rate or a population-level estimate.

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
(1.0x–10.8x on this sample, 1.0x–39.0x once the registry is widened to
fourteen), that four of ten have no secondary trading at all across a
six-month observation period, and that holder concentration is both extreme
and largely static over the same period — eleven of fourteen assets on the
widened registry exceed an HHI of 2,500. The one exception to "largely
static" is itself a finding: the sample's only sustained concentration trend
was found to have the wrong sign, because a lending vault counted as a
single large holder made OUSG appear to concentrate over six months when the
corrected series, with that vault excluded, instead deconcentrates
throughout. That reversal — not a marginal revision, but a sign flip in a
previously reported result — is offered as the strongest available evidence
that the address-versus-investor problem this chapter checks for is not a
formality. These findings are consistent with concurrent academic work
(Mafrur, 2025, 2026) documenting the same general pattern from an
independent, differently-sourced sample, and extend it methodologically by
resolving — for tokens using the standard ERC-20 issuance convention — the
primary/secondary conflation that Mafrur (2026) explicitly leaves as an open
limitation. §2.2 draws out one further implication: because that paper's
turnover figures are not corrected for issuance, its "intermediate"
liquidity classification for Treasury-token turnover is plausibly an
overstatement, on the evidence of this chapter's own Treasury-fund sample,
though the two studies do not share a sample or window and this is stated
as a testable claim rather than a re-measurement.

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
