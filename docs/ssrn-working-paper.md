# Event-Level Classification of On-Chain Transfers Resolves a Measurement Gap in Tokenized Real-World Asset Liquidity

**Atay Tümer**

*Working paper. Draft for SSRN submission. Code, cached data, and every
figure below are reproducible from the open-source `rwa-liquidity` package:
[github.com/atytmr07/rwa-liquidity](https://github.com/atytmr07/rwa-liquidity).*

---

## Abstract

Tokenized real-world assets (RWAs) are commonly presented as more liquid
than their off-chain equivalents because they trade on a continuously
operating public ledger. Mafrur (2026) tests this claim against on-chain
activity for nine Ethereum RWA tokens and reaches a stated limitation: an
ERC-20 `Transfer` event does not distinguish a fund's own issuance and
redemption activity from trading between two investors, so raw transfer-based
turnover measures a mix of both. That paper reports this conflation as an
open measurement problem rather than resolving it. This paper resolves it.
Using a keyless, directly-queried Ethereum adapter that classifies every
individual transfer as issuance, redemption, or secondary trade via the
ERC-20 zero-address convention, and that verifies every reconstructed
holder-balance distribution against the token contract's own `totalSupply()`,
this paper measures ten real, currently-trading tokenized RWA products.
Raw transfer volume is found to overstate secondary-market liquidity by a
factor of 1.0x to 10.8x depending on the asset (up to 39.0x on a widened
fourteen-asset registry), four of ten assets record no peer-to-peer trading
at all across six consecutive monthly windows, and holder concentration is
extreme and largely static over the same period. The method's own
verification step is shown to matter as much as its transfer-side
classification: excluding a DeFi contract miscounted as a single large
investor is shown, in one case, to invert the direction of a previously
reported concentration trend rather than merely shift its magnitude. The
paper's coverage has a real cost, symmetric to the paper it extends: the
verifiable, keyless method cannot reach gold-backed tokens (PAXG, XAUT), the
asset class Mafrur's own results find most liquid, because their transfer
history exceeds what an exhaustive scan against a free public endpoint can
complete.

**Keywords:** tokenization, real-world assets, liquidity, blockchain,
secondary markets, market microstructure

---

## 1. Introduction

Real-world asset (RWA) tokenization — representing claims on Treasury
bills, private credit, commodities, and other traditional instruments as
tokens on a public blockchain — has grown from a marginal experiment to a
market institutions now analyze directly. The stated case for tokenization
rests substantially on a liquidity argument: that moving an asset onto a
continuously operating, programmable settlement layer makes it easier to
buy, sell, and price. That argument is testable, and it has rarely been
tested directly against transaction-level, on-chain data rather than
against reported market values or aggregator-supplied summary statistics.

Mafrur (2026), "Tokenized but Illiquid? Evidence from Real-World Asset
Markets" (arXiv:2606.01131), tests it directly against on-chain activity
and names the limitation this paper is built to close. Every transfer of an
ERC-20 token — the standard almost all tokenized RWA products use — emits
an identical `Transfer` event regardless of its economic meaning. Three
distinct events are indistinguishable at the event level without further
processing: an investor subscribing to a fund (the fund mints tokens to
them), an investor redeeming (tokens are burned or returned to the issuer),
and two investors trading with each other. Only the third is evidence of a
secondary market. Mafrur (2026) states this plainly: *"on-chain transfers
are not equivalent to economic trades... [they] may also include minting
and redemption events, treasury movements, custodial rebalancing, or other
operational flows,"* and frames the paper's own results as *"evidence on
relative on-chain activity... not a complete market microstructure
assessment."* The paper measures raw transfer turnover throughout and
reports the conflation as a stated limitation rather than resolving it.

This paper closes that specific gap: classifying every transfer event
individually, rather than aggregating first and caveating second. Applied
to BlackRock's BUIDL — a token in both this paper's sample and Mafrur's,
which describes it only qualitatively as combining *"relatively large scale
with modest participation breadth and uneven activity intensity"* — the
answer is a number, not an adjective: 696 of 731 transfers in a single
30-day window were issuance, not trading. Raw turnover overstates the
fund's actual secondary-market activity by a factor of 10.8. The correction
is asset-specific rather than a fixed discount — it reaches 39x elsewhere
in a wider sample (§4.2) — and it is not free: this paper cannot reach the
one asset class (gold-backed tokens) Mafrur's own results find most liquid,
which is a real cost of verifiability stated here rather than left for a
reader to discover in a limitations section.

### 1.1 Research questions

- **RQ1.** For real, currently-trading tokenized RWA products, how large is
  the gap between raw transfer-based liquidity measures and liquidity
  measures that isolate secondary trading?
- **RQ2.** Is holder concentration in tokenized RWA markets consistent with
  the "broadened ownership" narrative commonly attached to tokenization, and
  does that concentration change over time?

Both are answered under a binding methodological constraint: every figure
reported here is derivable from public Ethereum infrastructure alone, with
no licensed data feed and no API key, and every holder distribution is
checked against the token contract's own `totalSupply()` rather than
accepted on a provider's word.

---

## 2. Data and Method

### 2.1 Data source and verification

Measurements are drawn from a single source — direct Ethereum JSON-RPC
queries against a public node — requiring no API key and no
data-provider relationship, in contrast to Mafrur (2026), which draws from
RWA.xyz, a commercial aggregator, with Etherscan used for selective
contract-level checks. For each asset, the adapter replays every `Transfer`
event since contract deployment to reconstruct holder balances, then checks
the reconstruction against the contract's own `totalSupply()` call. Where
the two agree, the distribution is treated as exact; where they disagree
(as with the rebasing token USDM), the affected metrics are reported as
undefined rather than published as an estimate.

### 2.2 Primary/secondary classification

Every transfer is classified using the ERC-20 zero-address convention: a
transfer originating from `0x000...000` is a mint; one directed to it, or
to the conventional burn address `0x000...dEaD`, is a burn; everything else
is classified as secondary unless an issuer treasury address is separately
configured and independently confirmed (via an Etherscan label or protocol
documentation — never inferred from balance size alone), in which case
transfers to or from it are also treated as primary. Anything the rules
cannot decide is labelled unclassified rather than assumed secondary,
because assuming secondary is the specific error this method exists to
prevent.

### 2.3 Holder-side verification

Holder-balance concentration figures are computed over addresses, and an
address is not necessarily an investor: a DeFi lending vault or AMM pool
holding a balance is indistinguishable from a single large investor by
balance alone. Every measurable asset's top holders were checked against
Etherscan's own contract labels (never inferred from behavior), and
confirmed contracts were excluded from concentration and dormancy figures.
This is not a hypothetical concern: it materially reversed a previously
reported six-month concentration trend for one asset in this sample (§4.3).

### 2.4 Sample construction

Ten real, currently-measurable tokenized RWA products, selected by a
reproducible on-chain procedure: every protocol DeFiLlama categorizes as
`RWA` was resolved on-chain via its contract's own `symbol()` and `name()`
calls, and roughly three-quarters of the resulting addresses were
discarded as governance tokens rather than tokenized assets themselves. A
widened fourteen-asset registry, constructed the same way, is used where
noted. Two assets in the registry — BUIDL on this specific run, and PAXG
structurally — could not be measured by this method; §4.4 discusses both.

### 2.5 Metric definitions

Over an observation window `P` (default 30 days): **turnover ratio** =
total transfer volume over `P` / total asset value at `P`'s end; **top-10
holder share** and **holder HHI** (Herfindahl-Hirschman index, 0–10,000
scale) over the reconstructed holder distribution; **dormancy** = share of
supply held by addresses with no transfer in `P`. Every volume-based metric
is computed in three modes — `all`, `secondary_only`, `primary_only` — with
`secondary_only` as the default, on the argument that under-reporting
liquidity is the safer failure direction for published research than
over-reporting it.

---

## 3. Results

### 3.1 RQ1 — raw volume against secondary-only volume

For BUIDL, raw ("all-mode") turnover reads 0.2015 over a 30-day window —
roughly a fifth of outstanding supply moving. Restricting to secondary
trades only, turnover falls to 0.0187: a **10.8x overstatement** in the raw
figure. The correction is not constant across the sample: OUSG and FDIT are
overstated 2.0–2.3x; CANA, HLSCOPE, USDM, and the four zero-secondary-activity
assets are overstated 1.0x (not at all, because their activity was already
entirely secondary or entirely absent). On a widened fourteen-asset
registry, Circle's USYC reaches **39.0x** — 78 of its 100 window transfers
were mint or burn. The claimed range on the observed sample is therefore
1x to 39x, asset-specific, and by construction not correctable with a
single scalar.

**Table 1 — comparison with Mafrur (2026)'s pooled turnover distribution.**
Mafrur (2026) reports log(turnover) over 54 token-months (raw transfer
volume / asset value, all nine sample tokens pooled, Dec 2025–May 2026,
his own Table 2): mean **−1.667**, median **−1.184**, range −8.782 to
1.165. Computing the same statistic — log of secondary-only turnover, zero
values excluded exactly as his specification excludes them — over this
paper's ten measured assets gives: mean **−2.581**, median **−2.025**,
range −4.948 to −0.245.

| | Mafrur (2026), raw turnover, log | This paper, secondary-only turnover, log |
|---|---|---|
| n | 46 (token-months, log-defined subset of 54) | 10 (assets, log-defined subset of 14) |
| Mean | −1.667 | −2.581 |
| Median | −1.184 | −2.025 |
| Min | −8.782 | −4.948 |
| Max | 1.165 | −0.245 |

*The two rows are not a matched comparison — different tokens (four of
Mafrur's nine overlap this paper's registry: BUIDL, OUSG, USTB, PAXG, of
which PAXG is unmeasured here), a different window, and a different data
provenance (RWA.xyz-sourced monthly snapshots vs. directly-queried,
supply-verified on-chain replay). It is reported as two independent
measurements of a related universe, not a controlled experiment. Read
that way, the gap is directionally consistent with — and one candidate
explanation for — the conflation Mafrur (2026) names as unresolved in his
own raw-turnover figure: an uncorrected mint/redeem component pushes a raw
turnover distribution higher than a secondary-only one drawn from a
similar population.* The one genuinely matched data point is qualitative
rather than numeric: Mafrur's own text describes BUIDL as showing *"modest
participation breadth and uneven activity intensity"* — this paper attaches
an exact number to that same asset (10.8x, above).

### 3.2 RQ1 (continued) — assets with zero secondary activity

ZTLN, RCOIN, ATT, and CGT recorded zero holder-to-holder transfers in the
measurement window; their dormancy is 100%. ZTLN has $150 million in
outstanding supply and no transfers beyond the twelve that created it,
across its entire on-chain history — though one of its two nominal holders
is confirmed, via Etherscan's own label, to be a Balancer V2 pool contract,
not an investor (§3.4), so only one confirmed investor (holding a third of
total supply) is actually established as dormant; the rest is opaque.

### 3.3 RQ2 — holder concentration, cross-sectional and over time

Eight of the ten measurable assets exceed an HHI of 2,500 (the 2010 DOJ/FTC
"highly concentrated" threshold); the same eight also clear the stricter
1,800 threshold from the 2023 revision. Tracked across six consecutive
30-day windows, most series are flat. **One correction matters more than
the rest of this finding**: an earlier reading of this same data reported
OUSG as the sample's one clearly *concentrating* asset, 82.4% to 92.9% over
six months. A DeFi lending vault (`Flux Finance: fOUSG Token`) had been
counted as a single large holder; excluded, per §2.3's verification step,
the corrected series instead **deconcentrates**, 81.6% to 70.1%, throughout.
Holding the window fixed and toggling only the exclusion moves OUSG's
top-10 share by 24 points — far more than a five-week window shift could
produce — so the exclusion, not measurement noise, is the cause. This is
offered as the strongest available evidence that the address-versus-investor
problem this paper checks for is not a formality: it inverted the sign of
a reported finding, not merely its magnitude.

### 3.4 What the constraint costs

Two assets in this paper's registry could not be measured. PAXG's transfer
history exceeds roughly 250,000 logs, past what a free public RPC endpoint
will serve for an exhaustive scan — reported as *not measurable*,
deliberately distinct from a measured value of zero. This is the direct
counterpart to Mafrur (2026)'s own finding: gold-backed tokens (PAXG,
XAUT) are the asset class his results find most liquid (Table 4: Treasury
and Private Credit both significantly below Gold in raw turnover, p<0.01),
and it is exactly the class this paper's verifiable, keyless method cannot
reach. To test whether this boundary makes the paper's low-liquidity
findings an artifact of the method's own reach rather than a property of
the market, PAXG was separately measured over the same window using Dune
Analytics, with the same classification rules re-expressed in SQL. Its
reconstructed balances matched the contract's own `totalSupply()` to
0.00027%, and its measured HHI (378) sits below even the "unconcentrated"
floor — the method is not built to find illiquidity, and does not find it
here, when applied to an asset outside the boundary.

BUIDL, separately, was not measurable on the most recent run: a free
public RPC endpoint refused a full-history scan after sustained attempts.
Its figures above are its last successful measurement, not a live read —
disclosed here rather than silently substituted.

### 3.5 A supplementary exploratory regression, and why it is not a panel

Mafrur (2026) tests H2/H3 (holder breadth and size as predictors of
liquidity) with a true panel: asset-class and month fixed effects over 46–54
token-month observations. This paper's own data, as collected, is a single
cross-section per asset rather than a time series of holder counts and
asset values at each of the six trend windows — reconstructing that would
require additional per-window data engineering not completed here. What
can be reported honestly with what is already computed is a simple
cross-sectional OLS, in the same spirit as Mafrur's own descriptive-first
approach, over the nine assets with strictly positive secondary-only
turnover (the same log-turnover-defined subset used in Table 1):

$$\log(\text{Turnover}_i) = \alpha + \beta_1 \log(\text{Supply}_i) + \beta_2 \log(\text{Holders}_i) + \varepsilon_i$$

| | Coefficient | Std. error | t |
|---|---|---|---|
| Constant | −4.673 | 4.345 | −1.08 |
| log(Supply) | 0.256 | 0.222 | 1.15 |
| log(Holders) | −0.432 | 0.313 | −1.38 |

n = 9, degrees of freedom = 6, R² = 0.494. **Neither coefficient is
statistically distinguishable from zero** at conventional levels — with 6
degrees of freedom, nothing short of a very large effect could be. This
result is reported for transparency, not as a finding: it neither confirms
nor contradicts Mafrur (2026)'s H2 (log holders positive and significant
in his active-month specification) or H3 (log size insignificant, which
this regression's point estimate is at least directionally consistent
with). The negative point estimate on log(holders) — the opposite sign
from Mafrur's — is noted rather than interpreted, since a sample this
small cannot distinguish a real reversal from noise. A properly-powered
version of this test, with per-window holder and supply reconstruction
extending this paper's six monthly windows to a finer (e.g. weekly)
granularity from already-cached transfer data, is the natural next step
and is not attempted here under this draft's time budget.

---

## 4. Limitations

- **On-chain visibility is not market visibility.** Off-chain settlement
  is invisible, so an actively traded asset can read as dormant.
- **Addresses are not investors**, beyond what §2.3's audit has checked.
  An asset absent a confirmed exclusion has not been verified clean, only
  unexamined.
- **Sample size and time depth.** Ten measurable assets and six monthly
  windows support a directional finding, not a growth-rate estimate.
- **The verifiable method cannot reach actively-traded, high-volume
  assets** — PAXG and XAUT specifically, the class Mafrur (2026) finds
  most liquid — because exhaustive log replay against a free endpoint is
  only tractable for thin transfer histories. This is a structural
  trade-off between independent verifiability and market coverage, not an
  oversight.
- **No formal significance test is applied to the six-window series.** Six
  points per asset is too short to fit a trend model or compute a
  confidence interval that would mean anything; every trend claim here is
  stated as a direction observed in this sample, not a population-level
  estimate — unlike Mafrur (2026)'s own fixed-effects panel regression,
  which is doing exactly that inferential work over a longer,
  differently-sourced series.
- **Two of the adapter's five source integrations are unverified against
  live third-party APIs** (rwa.xyz, Dune Analytics used only as noted in §3.4).
- **§3.5's regression is a nine-observation cross-section, not a panel.**
  Unlike Mafrur (2026)'s fixed-effects estimation over 46–54 token-months,
  this paper's holder and supply data were collected as a single snapshot
  per asset rather than at each of the six trend windows, so no time
  dimension is available for that specific test without further data
  engineering. Both coefficients reported there are statistically
  indistinguishable from zero and should be read as such.

---

## 5. Conclusion

Measured directly from public Ethereum data, without any commercial data
license, ten real tokenized RWA products show that raw transfer volume
overstates secondary-market liquidity by a factor that varies by asset
(1.0x–10.8x on this sample, up to 39.0x on a widened registry), that four
of ten have no secondary trading at all across a six-month observation
period, and that holder concentration is both extreme and largely static —
with the one exception itself being a finding: a previously-reported
concentration trend had the wrong sign until an unexcluded DeFi contract
was identified and removed. These findings are consistent with, and
extend, Mafrur (2026), which identifies the same primary/secondary
conflation as an open measurement problem in a differently-sourced,
longer-period sample; this paper resolves it, for tokens using the
standard ERC-20 issuance convention, at the cost of coverage over the
asset class — gold-backed tokens — that an aggregator-based approach can
reach but an independently-verifiable one, at present, cannot.

---

## References

- Mafrur, R. (2026). Tokenized but illiquid? Evidence from real-world
  asset markets. arXiv:2606.01131.
- Mafrur, R. (2025). Tokenize everything, but can you sell it? RWA
  liquidity challenges and the road ahead. arXiv:2508.11651.
- Amihud, Y. (2002). Illiquidity and stock returns: cross-section and
  time-series effects. *Journal of Financial Markets*, 5, 31–56.
- Aquilina, M., Lewrick, U., Ravenna, F., & Schönleber, L. (2025). The rise
  of tokenised money market funds. *BIS Bulletin*, No. 115.
- Ben-David, I., Franzoni, F., & Moussawi, R. (2016). Exchange traded funds
  (ETFs). NBER Working Paper 22829.
- Datar, V. T., Naik, N. Y., & Radcliffe, R. (1998). Liquidity and stock
  returns: an alternative test. *Journal of Financial Markets*, 1(2), 203–219.
- Ma, Y., Zeng, Y., & Zhang, A. L. (2025). Stablecoin runs and the
  centralization of arbitrage. NBER Working Paper 33882.
- Sai, A. R., Buckley, J., & Le Gear, A. (2021). Characterizing wealth
  inequality in cryptocurrencies. *Frontiers in Blockchain*, 4.
- U.S. Department of Justice, Antitrust Division. Herfindahl-Hirschman
  Index, citing U.S. DOJ & FTC, *Merger Guidelines* § 2.1 (2023).

*Full methodology, per-asset tables, and every caveat this working paper
condenses: `docs/thesis-chapter-draft.md`, `docs/findings.md`,
`docs/methodology.md` in the linked repository.*
