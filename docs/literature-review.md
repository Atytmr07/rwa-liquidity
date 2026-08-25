# Literature Review

This review situates `rwa-liquidity` against existing academic and institutional
work on tokenized real-world assets (RWA), market liquidity measurement, and
on-chain data analysis.

**Verification status.** Every entry carries a marker saying how far it was
checked, because that distinction is the difference between a review and a list
of search results:

* **[primary]** — the source document itself was retrieved and read, and every
  claim attributed to it below was located in its text.
* **[abstract]** — the abstract or landing page was read from the publisher;
  bibliographic details are confirmed, body claims are not.
* **[secondary]** — the entry rests on a search summary or another paper's
  citation. Treat as a lead, not as evidence.

A first pass of this review was assembled at [secondary] depth throughout. A
verification pass on 2026-08-25 retrieved the primary sources and **found three
substantive errors in that first pass** — a misattributed authorship, a set of
wrong numbers, and an unattributable statistic. All three are corrected below,
and what they were is recorded in §8 rather than quietly fixed, since the
failure mode they share is the main thing this review can teach its next reader.

## 1. Real-world asset tokenization: market context

- **Li, J. (2025). "Current Landscape of the Real-World Asset (RWA)
  Tokenization Ecosystem."** Donald G. Costello College of Business, George
  Mason University, Research Paper. SSRN 6077226, 15 September 2025.
  *[abstract]* Covers **180+ RWA products**, examining industrial
  organization, legal structure, regulatory framework, and on-chain activity.
  The largest-sample survey of the RWA product space located in this review.

  *Not verified:* the first pass quoted this paper as reporting "a persistent
  divergence between the theoretical advantages of 24/7 trading and the
  empirical reality of limited secondary-market activity." That sentence came
  from a search summary and **could not be located in the paper** (SSRN
  returned 403 to automated retrieval). It is removed from the quotation here.
  The paper should be read directly before its findings are characterised in a
  submitted thesis.

- **Aquilina, M., Lewrick, U., Ravenna, F., & Schönleber, L. (2025). "The rise
  of tokenised money market funds."** BIS Bulletin No. 115, 26 November 2025.
  [bis.org/publ/bisbull115.pdf](https://www.bis.org/publ/bisbull115.pdf)
  *[primary]* Frames tokenised money market funds (TMMFs) as a fast-growing
  collateral asset within DeFi, subject to liquidity-mismatch risks that mirror
  conventional money market funds.

  Directly relevant to this project's BUIDL results, in the Bulletin's own
  words: **"Based on Ethereum data, companies operating DeFi protocols are the
  main investors in BUIDL, the largest TMMF to date."** It gives the use case —
  TMMFs pledged as collateral to borrow stablecoins — and names OUSG, also in
  this project's registry, as a fund-of-fund investing through BUIDL. This is
  the citation for *why* BUIDL's on-chain holder count is small and
  institutional rather than retail, which bears directly on how this project's
  concentration figures should be read (§5).

- **European Central Bank (2026). "Tokenised money market funds: new
  technology, familiar risks?"** Macroprudential Bulletin, issue 202604.
  [ecb.europa.eu](https://www.ecb.europa.eu/press/financial-stability-publications/macroprudential-bulletin/html/ecb.mpbu202604_04.en.html)
  *[secondary]* Regulatory perspective: TMMFs reproduce money market fund risk
  (redemption pressure, run dynamics) on new rails rather than removing it.

- **Federal Reserve Bank of New York, Liberty Street Economics (2025). "The
  Emergence of Tokenized Investment Funds and Their Use Cases."**
  [libertystreeteconomics.newyorkfed.org](https://libertystreeteconomics.newyorkfed.org/2025/09/the-emergence-of-tokenized-investment-funds-and-their-use-cases/)
  *[secondary]* Federal Reserve staff description of the fund category this
  project measures, useful for arguing the registry is a recognised category
  rather than an arbitrary selection.

## 2. RWA liquidity as an open empirical question — the closest prior work

- **Mafrur, R. (2025). "Tokenize Everything, But Can You Sell It? RWA
  Liquidity Challenges and the Road Ahead."** arXiv:2508.11651, 3 August 2025.
  [arxiv.org/abs/2508.11651](https://arxiv.org/abs/2508.11651) *[abstract]*
  Documents low trading volumes, long holding periods and limited investor
  participation across tokenized real estate, private credit and treasury
  funds, against $25B+ tokenized on-chain by 2025. Identifies regulatory
  restriction, custodial concentration and lack of decentralized venues as
  structural causes.

- **Mafrur, R. (2026). "Tokenized but Illiquid? Evidence from Real-World Asset
  Markets."** arXiv:2606.01131, submitted 31 May 2026 (v2 17 July 2026).
  [arxiv.org/abs/2606.01131](https://arxiv.org/abs/2606.01131) *[primary]*
  **This is the paper to position against directly.**

  **Methodology.** Nine Ethereum non-stablecoin RWA tokens (BUIDL, BENJI,
  OUSG, USTB, USDY, SCOPE, STAC, PAXG, XAUT), 54 token-month observations,
  December 2025 to May 2026, month-end snapshots from RWA.xyz with Etherscan
  for contract-level checks; USDC retained as a scale benchmark but excluded
  from estimation. Four measures: turnover (`monthly transfer volume / total
  asset value`), log active addresses, a binary active-month indicator, and an
  active-address ratio. Three-stage design: descriptives emphasising medians
  given the small non-normal sample, Kruskal–Wallis tests across asset classes
  with Spearman correlations, then fixed-effects panel regressions.

  **Findings.** Log turnover and log active addresses differ sharply by asset
  class (Kruskal–Wallis 29.6 and 32.5, both p<0.001). Gold-backed tokens show
  the broadest holder bases and most persistent activity; Treasury tokens are
  intermediate; private-credit tokens weakest. Size does not predict turnover
  once class and holder count are controlled for. The abstract states the
  conclusion plainly: *"outstanding asset value alone does not reliably predict
  observed liquidity"*, and tokenization and liquidity *"should be analyzed as
  distinct outcomes."*

  **The paper names the limitation this project is built to close:** on-chain
  transfers are not equivalent to economic trades, since a transfer may be a
  mint, a redemption, a treasury movement or custodial rebalancing. Its results
  are accordingly framed as evidence on *observed on-chain activity* rather
  than a market microstructure assessment. It measures raw transfer turnover
  throughout and reports the conflation as an open problem rather than
  resolving it.

  **Three differences from this project, stated precisely:**
  1. **Data provenance.** Mafrur draws from RWA.xyz, an aggregator whose
     methodology is not independently auditable from outside.
     `rwa-liquidity`'s adapter queries Ethereum directly and checks every
     holder-balance reconstruction against the contract's own `totalSupply()`.
  2. **Primary/secondary separation.** Mafrur measures raw transfer turnover
     and flags mint/redeem conflation as a caveat. `rwa-liquidity` classifies
     each transfer as mint, burn or secondary via the zero-address convention
     and defaults to `secondary_only`; this project's BUIDL result (696 of 731
     transfers were issuance, a 10.8x overstatement in raw turnover) is an
     event-level measurement of exactly the gap that paper leaves open.
  3. **Time depth.** Mafrur's sample is 54 token-months of provider snapshots.
     `rwa-liquidity` replays each token's complete transfer history from
     deployment.

  **Where the comparison runs the other way.** Mafrur finds gold-backed tokens
  (PAXG, XAUT) the *most* liquid class in the sample. PAXG is the one asset in
  this project's registry marked *not measurable* — its transfer volume exceeds
  what an exhaustive scan against a free public endpoint can complete
  (`docs/methodology.md`). The asset class an aggregator-based study finds most
  liquid is exactly the one the independently-verifiable method cannot reach.
  That is a real cost of verifiability and belongs in the thesis as such.

  **This project answers two of the paper's three stated future directions** —
  longer token histories (the full-history replay and six-window trend) and
  richer ownership-concentration data (verified HHI and top-10 share). The
  third, multi-chain coverage, it does not: it is Ethereum-only, the same
  restriction Mafrur imposes to avoid cross-chain measurement inconsistency.
  Claiming two of three named directions is more defensible before a committee
  than a general claim of novelty.

## 3. Liquidity as a measured construct in financial economics

- **Amihud, Y. (2002). "Illiquidity and stock returns: cross-section and
  time-series effects."** *Journal of Financial Markets* 5, 31–56.
  [PDF](https://www.cis.upenn.edu/~mkearns/finread/amihud.pdf) *[primary]*
  Bibliographic details confirmed against the article's own title page.

  ILLIQ is defined in the paper as *"the daily ratio of absolute stock return
  to its dollar volume, averaged over some period"*, interpreted as *"the daily
  price response associated with one dollar of trading volume, thus serving as
  a rough measure of price impact."*

  **Two passages from this paper directly justify this project's metric
  choice**, which is a stronger position than citing it merely as background:

  1. Amihud chose a coarse measure for a data-availability reason structurally
     identical to this project's. He notes that finer measures — quoted or
     effective bid–ask spread, transaction-by-transaction market impact,
     probability of information-based trading — *"require a lot of
     microstructure data that are not available in many stock markets."* RWA
     tokens are in precisely that position: most lack a continuous secondary
     price series, so the return that forms ILLIQ's numerator does not exist,
     while volume and supply are directly observable on-chain for every asset
     in this dataset, including the four with zero secondary trades.
  2. Amihud explicitly treats turnover as a sibling proxy rather than a rival.
     He describes *"turnover, the ratio of trading volume to the number of
     shares outstanding"*, cites Datar et al. (1998) among studies using it,
     and concludes: *"These measures of liquidity as well as the illiquidity
     measure presented in this study can be regarded as empirical proxies that
     measure different aspects of illiquidity. It is doubtful that there is one
     single measure that captures all its aspects."*

  The second passage is the citation to use when a reviewer asks why this
  project measures turnover rather than price impact: the canonical
  price-impact paper says itself that these are complementary proxies.

- **Datar, V. T., Naik, N. Y., & Radcliffe, R. (1998). "Liquidity and stock
  returns: an alternative test."** *Journal of Financial Markets* 1(2),
  203–219. *[abstract]* Bibliographic record confirmed via RePEc
  ([eee/finmar/v1y1998i2p203-219](https://ideas.repec.org/a/eee/finmar/v1y1998i2p203-219.html)).
  Proposes the turnover rate — shares traded as a fraction of shares
  outstanding — as a liquidity proxy, testing Amihud & Mendelson's (1986)
  model. This is the direct academic precedent for this project's
  `turnover_ratio`, and the reason that metric should be presented as an
  imported construct rather than a project-specific invention.

  *A citation detail worth knowing:* Amihud's (2002) own bibliography lists
  this article as pages **205**–219. RePEc, the publisher's own metadata, gives
  **203**–219. Use 203–219.

## 4. Separating primary issuance from secondary trading — precedent outside crypto

This project's central methodological claim — that mint/redeem and
peer-to-peer trading must be measured separately — is standard practice in two
literatures that predate tokenization.

- **Ben-David, I., Franzoni, F., & Moussawi, R. (2016). "Exchange Traded Funds
  (ETFs)."** NBER Working Paper 22829, November 2016.
  [nber.org/papers/w22829](https://www.nber.org/papers/w22829) *[primary]*
  Sets out the two-market structure precisely: *"Two mechanisms keep ETF prices
  in line with those of the basket that they aim to track: primary and
  secondary market arbitrage."* Creation and redemption happen in the primary
  market between the fund and **authorized participants**, described as *"a
  small group of institutions that are allowed to trade with the ETF sponsor
  directly in the primary market"*, in large blocks called creation units,
  while ordinary investors trade existing shares on an exchange.

  This is the structural precedent for this project's mint/burn versus
  secondary classification: a fund's primary-market flow and its secondary-market
  trading are different economic events, measured separately, in a
  literature with no connection to blockchains.

- **Ma, Y., Zeng, Y., & Zhang, A. L. (2025). "Stablecoin Runs and the
  Centralization of Arbitrage."** NBER Working Paper 33882, May 2025.
  [nber.org/papers/w33882](https://www.nber.org/papers/w33882) *[primary]*
  Every claim below located in the paper's text.

  **Method — the closest published precedent to this project's approach.** The
  authors *"collect transaction-level data on each stablecoin creation and
  redemption event for the six largest fiat-backed stablecoins: Tether (USDT),
  Circle USD Coin (USDC), Binance USD (BUSD), Paxos (USDP), TrueUSD (TUSD),
  and Gemini dollar (GUSD) from the Ethereum, Avalanche, and Tron
  blockchains."* Like this project, they identify primary-market events from
  ledger data rather than issuer disclosure. Unlike this project, they source
  that data from chain explorers (Etherscan, Snowtrace, Tronscan) rather than
  querying nodes directly — a difference worth naming, since it is the same
  intermediary-trust question this project's `totalSupply()` check exists to
  remove.

  **The paper draws the ETF analogy itself**, tying §4's two halves together:
  stablecoin redemption at $1 *"is restricted to a specific set of
  institutional arbitrageurs. The vast majority of investors can only trade
  stablecoins on secondary market exchanges, similar to investors trading ETF
  shares on secondary markets."*

  **Concentration findings**, a direct parallel to this project's holder
  concentration (§5): *"USDT only has six arbitrageurs redeeming stablecoins
  during the average month, and the largest arbitrageur accounts for 66% of the
  total redemption activity. In contrast, arbitrage at USDC is more
  competitive, with 521 redeeming arbitrageurs in an average month."* From
  their Table 2, the top five arbitrageurs account for **97%** of USDT
  redemption activity and **85%** of USDC's.

## 5. Concentration and holder distribution

- **U.S. Department of Justice, Antitrust Division. "Herfindahl-Hirschman
  Index."** [justice.gov/atr/herfindahl-hirschman-index](https://www.justice.gov/atr/herfindahl-hirschman-index)
  (page updated 17 January 2024) *[primary]* Verbatim: *"The agencies generally
  consider markets in which the HHI is between 1,000 and 1,800 points to be
  moderately concentrated, and consider markets in which the HHI is in excess
  of 1,800 points to be highly concentrated. See U.S. Department of Justice &
  FTC, Merger Guidelines § 2.1 (2023)."*

  The 2,500 threshold this project's earlier drafts cited is the **2010**
  Horizontal Merger Guidelines figure; the 2023 Guidelines lowered it to 1,800.
  `README.md` and `docs/findings.md` now name both with their guideline year,
  which is the honest form — citing a bare number invites a reviewer to check
  the current one and find a mismatch. Cite as *Merger Guidelines § 2.1 (2023)*
  when the current figure is meant.

- **Sai, A. R., Buckley, J., & Le Gear, A. (2021). "Characterizing Wealth
  Inequality in Cryptocurrencies."** *Frontiers in Blockchain* 4.
  [doi.org/10.3389/fbloc.2021.730122](https://doi.org/10.3389/fbloc.2021.730122)
  *[primary]* **The first pass of this review reported these numbers wrongly;
  the corrected figures are below.**

  Reported Gini coefficients (January 2021): **Bitcoin 0.65**, Dogecoin 0.82
  (highest in their dataset), Dash 0.28 (lowest). Address concentration is
  reported at the **top-100** level, not top-10: Bitcoin's top 100 addresses
  hold **13.52%** of supply, Dogecoin's 64.67%, Bitcoin Cash's 22.74%, Dash's
  16.52%.

  The comparison to this project survives the correction and is in fact
  sharper: Bitcoin's **top 100** addresses hold about 13.5% of supply, while
  this project's RWA tokens show **top-10** shares of 82–100%. Tokenized funds
  are structurally closer to a cap table than to a payment network, and their
  concentration figures should not be read against general-purpose
  cryptocurrency baselines without saying so.

- **"Distributional equality in Ethereum? On-chain analysis of Ether supply
  distribution and supply dynamics."** *Humanities and Social Sciences
  Communications* (2025).
  [nature.com/articles/s41599-025-04728-9](https://www.nature.com/articles/s41599-025-04728-9)
  *[secondary]* Retrieval redirected to an authentication gate, so nothing
  here is confirmed from the text. Cited as a lead for the general method —
  deriving supply distribution from on-chain data rather than a provider's
  report — which parallels this project's `holder_snapshots` /
  `supply_snapshots`. Read before citing.

## 6. On-chain data as a research method

- **Nassr, I. K., Kostika, E., & Melachrinos, A. (2024). "Concentration of
  DeFi's liquidity."** OECD, April 2024.
  [doi.org/10.1787/4ed08440-en](https://doi.org/10.1787/4ed08440-en)
  *[primary]* Built on *"an original on-chain dataset covering the largest
  DEXs"* — an institutional precedent for treating chain data as a primary
  research source.

  Concentration findings, verified in the text: *"20% of the pools of some of
  the DEXs examined accounting for more than 90% of the trading volume of that
  DEX."* More precisely, for Uniswap V3 over March 2021 to April 2023, *"only
  20% of the pools ... accounting for 92.46% of the trading volume,
  corresponding to 53 out of the 265 pre-selected pools"*, and 10% of pools
  above USD 100m volume account for 88.21%. Useful for framing concentration
  metrics as risk indicators that regulators already track, not merely
  descriptive statistics.

- **General DeFi empirical survey literature** — e.g. "Decentralized Finance
  (DeFi): A Survey," arXiv:2308.05282; "A Survey of Transaction Tracing
  Techniques for Blockchain Systems," arXiv:2510.09624. *[secondary]*
  Establish on-chain event logs as an accepted primary data source, and
  document in general terms the data-hygiene problem this project's
  `_sanitize` and `_drop_implausible` guards address in a narrow one.

## 7. The gap this project occupies

No source located here evaluates a **public, keyless, independently
reproducible** measurement pipeline for RWA liquidity. Every comparable study
found — Mafrur (2025, 2026), Li (2025) — relies on RWA.xyz or a comparable
licensed provider; the closest methodological precedent, Ma, Zeng & Zhang
(2025), reads the chain but through commercial explorers. That combination —
primary/secondary separation at event level, holder distributions verified
against the contract's own supply, and no credential required to reproduce any
of it — is where this project's contribution sits.

Two honest qualifications. First, absence of evidence: this review covers what
a focused search surfaced, not the whole literature (§8). Second, the gap is
partly a *consequence* of a limitation, not purely an achievement — the keyless
method cannot reach PAXG, the very asset class the aggregator-based literature
finds most liquid (§2).

## 8. What this review does not establish

- **The first pass of this review contained three substantive errors, all
  produced the same way: attributing search-summary content to a source
  without opening it.** Recorded rather than silently fixed, because the
  pattern is the lesson:
  1. **Misattributed authorship.** BIS Bulletin 115 was described as *citing*
     "Aquilina et al. (2025)". Aquilina, Lewrick, Ravenna and Schönleber **are
     its authors**. The date was also given as 2026; it is 26 November 2025.
  2. **Wrong numbers.** Bitcoin's Gini was given as "near 0.99" with "top 10
     addresses holding single-digit percentage shares", attributed to the
     Frontiers paper. That paper reports Gini **0.65** and **top-100** holding
     **13.52%**. The 0.99 figure belongs to a different study entirely and was
     transplanted across sources by a search summary.
  3. **An unattributable statistic.** The claim that only $0.14 of every $1.00
     of ETF trading volume corresponds to creation/redemption activity could
     not be traced to any named paper across repeated searches, and is
     **removed**. §4 now rests on Ben-David, Franzoni & Moussawi (2016) for the
     structural distinction, which is verified and makes the same point without
     a number nobody can source.
- **Six entries remain below [primary] depth**: Li (2025), the ECB bulletin,
  the New York Fed post, Mafrur (2025), the Nature/HSSC article, and the DeFi
  survey literature. Their bibliographic details are confirmed where marked
  [abstract]; their body claims are not. Read before quoting.
- **One specific claim carried here is unverified**: that Amihud's ILLIQ was
  used in 100+ papers in top-three finance journals over 2009–2015. It comes
  from a secondary source and is not needed for any argument above; drop it
  unless traced.
- **This is not an exhaustive review.** It reflects a focused search across
  roughly a dozen queries in August 2026. A thesis-grade review should also
  search Google Scholar and a university library database directly — arXiv and
  SSRN undercount published journal literature behind paywalls — and should
  include Turkish-language sources if the submitting institution expects them.
