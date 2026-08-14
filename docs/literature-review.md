# Literature Review

This review situates `rwa-liquidity` against existing academic and institutional
work on tokenized real-world assets (RWA), market liquidity measurement, and
on-chain data analysis. It was compiled in August 2026 by searching current
academic and institutional sources; each entry notes whether it was read in
full, at abstract level, or from a search summary, so a reader can judge how
much weight to put on a given claim before checking the primary source
themselves.

## 1. Real-world asset tokenization: market context

Tokenization of real-world assets — Treasury funds, private credit, commodities
— has grown from a niche experiment to a market institutions now write about
directly.

- **Li, J. (2025). "Current Landscape of the Real-World Asset (RWA)
  Tokenization Ecosystem."** SSRN 6077226. *(abstract/search-summary level)*
  Reviews more than 180 tokenized products across six asset classes —
  private credit, stocks, global bonds, commodities, institutional funds, and
  U.S. Treasuries — and reports "a persistent divergence between the
  theoretical advantages of 24/7 trading and the empirical reality of limited
  secondary-market activity and predominantly passive holding patterns." This
  is an independent, much larger-sample confirmation of the same pattern this
  project found in ten assets: dormancy, not turnover, is the default state.

- **Bank for International Settlements (2026). "The rise of tokenised money
  market funds."** BIS Bulletin No. 115.
  [bis.org/publ/bisbull115.pdf](https://www.bis.org/publ/bisbull115.pdf)
  *(search-summary level)* Institutional framing of tokenized money market
  funds (TMMFs) as a bridge technology toward tokenized government bonds.
  Cites analysis (Aquilina et al., 2025) finding that DeFi protocols, not
  retail investors, are the dominant holder class of BUIDL — relevant context
  for why BUIDL's 59 on-chain holders in this project's dataset skew
  institutional rather than retail.

- **European Central Bank (2026). "Tokenised money market funds: new
  technology, familiar risks?"** Macroprudential Bulletin, issue 202604.
  [ecb.europa.eu](https://www.ecb.europa.eu/press/financial-stability-publications/macroprudential-bulletin/html/ecb.mpbu202604_04.en.html)
  *(search-summary level)* Regulatory perspective: TMMFs replicate money
  market fund risk (redemption pressure, run dynamics) on new rails, rather
  than eliminating it.

- **Federal Reserve Bank of New York, Liberty Street Economics (2025). "The
  Emergence of Tokenized Investment Funds and Their Use Cases."**
  [libertystreeteconomics.newyorkfed.org](https://libertystreeteconomics.newyorkfed.org/2025/09/the-emergence-of-tokenized-investment-funds-and-their-use-cases/)
  *(search-summary level)* Federal Reserve staff description of the same
  fund category this project measures (BUIDL, OUSG), useful as a citation for
  why these specific eleven assets are a reasonable, representative sample
  rather than an arbitrary selection.

## 2. RWA liquidity as an open empirical question — the closest prior work

Two papers, both by the same author and both published within the same window
this project was built, measure almost exactly what this project measures.
They are the most important comparison in this review and deserve to be read
in full before the thesis is finalized, not just cited from search summaries.

- **Mafrur, R. (2025). "Tokenize Everything, But Can You Sell It? RWA
  Liquidity Challenges and the Road Ahead."** arXiv:2508.11651.
  [arxiv.org/abs/2508.11651](https://arxiv.org/abs/2508.11651) *(abstract
  read)* Documents that most RWA tokens show low trading volume, long holding
  periods, and limited investor participation despite over $25B tokenized
  on-chain by 2025, using RWA.xyz market data across tokenized real estate,
  private credit, and treasury funds. Identifies regulatory restriction,
  custodial concentration, and lack of decentralized venues as structural
  causes.

- **Mafrur, R. (2026). "Tokenized but Illiquid? Evidence from Real-World
  Asset Markets."** arXiv:2606.01131.
  [arxiv.org/html/2606.01131](https://arxiv.org/html/2606.01131) *(full text
  read)* **This is the paper to position against directly.**

  **Methodology.** Nine Ethereum RWA tokens (BUIDL, BENJI, OUSG, USTB, USDY,
  SCOPE, STAC, PAXG, XAUT), 54 token-month observations, December 2025 to May
  2026, month-end snapshots from RWA.xyz with Etherscan for contract-level
  checks; USDC collected as a scale benchmark but excluded from estimation.
  Four core measures: turnover (`monthly transfer volume / total asset
  value`), log active addresses, a binary active-month indicator, and an
  active-address ratio (`active addresses / total holders`). Three-stage
  empirical strategy: descriptive statistics (medians alongside means given
  the small, non-normal sample), Kruskal–Wallis tests across asset classes
  plus Spearman rank correlations, then a fixed-effects panel regression
  (`Liquidity_it = α + β₁log(Size_it) + β₂log(Holders_it) + γ_asset-class +
  τ_month + ε_it`).

  **Findings.** Log turnover and log active addresses both differ sharply by
  asset class (Kruskal–Wallis statistics 29.6 and 32.5, both p<0.001).
  Gold-backed tokens (PAXG, XAUT) show the broadest holder bases and the most
  persistent activity; Treasury tokens are intermediate; private-credit
  tokens are weakest (turnover coefficient −7.4, p<0.01, relative to gold).
  Raw size does not predict turnover once class and holder count are
  controlled for (size coefficient not significant in any specification).
  BUIDL specifically is described as "relatively large scale with modest
  participation breadth and uneven activity intensity" — directly consistent
  with this project's own BUIDL finding (59 holders, secondary turnover
  0.0187). Central conclusion: "tokenization changes the form of ownership,
  but liquid secondary markets require additional conditions ... that cannot
  be assumed to emerge automatically once an asset is placed on-chain."

  **The paper explicitly names the limitation this project is built to
  close:** "on-chain transfers are not equivalent to economic trades ...
  [they] may also include minting and redemption events, treasury movements,
  custodial rebalancing, or other operational flows." Results are
  accordingly framed as "evidence on relative on-chain activity and
  tradability ... not a complete market microstructure assessment." The
  paper measures raw transfer turnover throughout and states the conflation
  as an open problem rather than resolving it.

  **Three concrete differences from this project, stated precisely rather
  than as a vague "we did it better":**
  1. **Data provenance.** Mafrur draws from RWA.xyz, a third-party aggregator
     whose own methodology is not independently auditable from outside.
     `rwa-liquidity`'s on-chain adapter queries Ethereum directly and
     verifies every holder-balance reconstruction against the token
     contract's own `totalSupply()` — the claim is checkable by anyone
     re-running the code against the same public RPC endpoint, with no
     intermediate data provider to trust.
  2. **Primary/secondary separation.** Mafrur measures raw transfer turnover
     and flags mint/redeem conflation as a caveat. `rwa-liquidity` classifies
     every individual transfer as mint, burn, or secondary via the ERC-20
     zero-address convention, and reports turnover in `secondary_only` mode
     by default — this project's BUIDL result (696 of 731 transfers were
     issuance, a 10.8x overstatement in raw turnover) is a direct,
     event-level measurement of the exact gap Mafrur's paper leaves open.
  3. **Time depth.** Mafrur's sample is 54 token-months of periodic snapshots
     from an external aggregator. `rwa-liquidity` replays a token's complete
     transfer history from deployment, so both the six trended windows and
     the "has this token ever minted through the zero address" issuance check
     are reconstructed from primary chain data rather than sampled from a
     provider's reporting cadence.

  **A finding worth stating honestly rather than hiding.** Mafrur's paper
  finds gold-backed tokens (PAXG, XAUT) the *most* liquid class in the whole
  sample. PAXG is also the one asset in this project's own eleven-asset
  registry marked `not measurable` — its transfer log volume (~250,000
  events) exceeds what a free public RPC endpoint will serve, so the
  on-chain method refuses to scan it rather than publish an unverified
  number (`docs/methodology.md`). That is not a contradiction to paper over;
  it is a genuine limit of the trustless approach worth stating directly in
  the thesis: **the asset class an aggregator-based study finds most liquid
  is exactly the one this project's independently-verifiable method cannot
  reach**, which is itself a finding about the cost of verifiability, not
  just a gap to apologize for.

  **This project answers two of Mafrur's own three stated future-research
  directions.** The paper's conclusion explicitly calls for: (a) "longer
  token histories ... to allow more credible analysis of liquidity
  persistence and changes over time" — this project's full-history ledger
  replay and six-window trend (`rwa-liquidity trend`) is exactly that; (b)
  "richer data on ... ownership concentration" — this project's HHI and
  top-10 share metrics, computed from a verified reconstruction rather than
  a reported holder count, are exactly that. The third — "broader token
  coverage across multiple chains" — this project does not address either;
  it is Ethereum-only, the same scope restriction Mafrur imposed
  deliberately "to reduce cross-chain measurement inconsistency." Framing
  the contribution this way (two of three, named directions, not invented
  ones) is more defensible in front of a committee than a general claim of
  novelty.

  This should be framed in the thesis as building on Mafrur's problem framing
  (RWA liquidity is empirically low and heterogeneous — confirmed here on an
  independent, smaller, differently-sourced sample) while resolving a
  limitation the same author's more recent paper names explicitly, and being
  candid about the one place their aggregator-based approach reaches further
  than this project's verified-from-chain approach can.

## 3. Liquidity as a measured construct in financial economics

Turnover ratio is not a project-specific invention; it has a defined lineage
in market microstructure literature, which grounds this project's metric 1.

- **Amihud, Y. (2002). "Illiquidity and stock returns: cross-section and
  time-series effects."** *Journal of Financial Markets*, 5, 31–56. PDF:
  [cis.upenn.edu/~mkearns/finread/amihud.pdf](https://www.cis.upenn.edu/~mkearns/finread/amihud.pdf)
  *(search-verified, primary source located)* The canonical illiquidity
  measure in equity market microstructure — price impact per dollar of
  volume. One of the most cited liquidity proxies in finance (100+ papers in
  top-three finance journals 2009–2015 alone per secondary sources). Useful
  as the reason turnover-based measures need a companion note explaining why
  this project used turnover rather than Amihud's price-impact measure: RWA
  tokens mostly lack a continuous secondary price series to compute a return,
  which is Amihud's numerator — turnover requires only volume and supply,
  both of which are directly observable on-chain for every asset in this
  dataset, including the four with zero secondary trades.

- **Datar, V. T., Naik, N. Y., & Radcliffe, R. (1998). "Liquidity and Stock
  Returns: An Alternative Test."** *Journal of Financial Markets*, 1,
  203–219. *(search-verified via secondary citation)* Establishes turnover
  rate — shares traded divided by shares outstanding — as a standalone
  liquidity proxy, independent of Amihud's price-impact framing, on the
  argument that liquidity and trading frequency are correlated in
  equilibrium (following Amihud & Mendelson, 1986). This is the direct
  academic precedent for this project's `turnover_ratio` metric definition
  (`docs/methodology.md`), and worth citing as such rather than presenting
  the formula as if it were invented for this project.

## 4. Separating primary issuance from secondary trading — precedent outside crypto

This project's central methodological claim — that mint/redeem and
peer-to-peer trading must be measured separately — has a direct precedent in
two literatures that predate tokenization entirely.

- **ETF creation/redemption literature.** *(search-summary level; the
  specific $0.14-per-$1.00 figure below could not be traced to a single named
  paper through search and should be verified against the primary source
  before being quoted directly in the thesis — see caveat in §7.)* ETF
  shares trade in two structurally separate markets: authorized participants
  create and redeem shares directly with the fund (the primary market,
  analogous to this project's mint/burn classification), while most investor
  activity happens between third parties on an exchange (the secondary
  market). Search results cited a finding that only roughly $0.14 of every
  $1.00 in total ETF trading volume corresponds to creation/redemption
  activity — structurally the same distinction this project draws for
  tokenized funds, and a useful citation for *why* the primary/secondary
  split is standard practice in adjacent, non-crypto fund structures, not a
  novel requirement invented for this project. See also: "ETF effects: The
  role of primary versus secondary market activities," ScienceDirect,
  [doi link via S1386418125000230](https://www.sciencedirect.com/science/article/pii/S1386418125000230).

- **Ma, Y., Zeng, Y., & Zhang, A. L. "Stablecoin Runs and the Centralization
  of Arbitrage."** NBER Working Paper 33882.
  [nber.org/system/files/working_papers/w33882/w33882.pdf](https://www.nber.org/system/files/working_papers/w33882/w33882.pdf)
  *(search-summary level)* Analyzes transaction-level creation and redemption
  events for six major fiat-backed stablecoins (Tether, USDC, BUSD, Paxos,
  TrueUSD, Gemini dollar) across Ethereum, Avalanche, and Tron, finding
  redemption arbitrage is highly concentrated among a handful of addresses
  (as few as six for USDT). Methodologically the closest precedent to this
  project's on-chain mint/burn classification: both identify primary-market
  events directly from ledger data rather than from a self-reported issuer
  disclosure. Worth citing specifically for the arbitrager-concentration
  parallel to this project's own holder-concentration findings (HHI, §5).

## 5. Concentration and holder distribution

- **U.S. Department of Justice, Antitrust Division. "Herfindahl-Hirschman
  Index."** [justice.gov/atr/herfindahl-hirschman-index](https://www.justice.gov/atr/herfindahl-hirschman-index)
  *(primary source read)* **Correction needed in this project's own docs.**
  This project's `README.md` and `docs/findings.md` currently cite 2,500 (on
  the 0–10,000 scale) as the threshold for "highly concentrated" under "US
  antitrust guidelines" — that figure is from the 2010 Horizontal Merger
  Guidelines. Current DOJ guidance (reflecting the 2023 Merger Guidelines
  revision) states markets are "highly concentrated" above **1,800**, with
  1,000–1,800 "moderately concentrated." Both figures are defensible with the
  right citation attached (2010 vs. 2023 guidelines), but the docs should
  either cite the specific guideline year or switch to the current 1,800
  figure — right now they state a number without a year, which reads as
  imprecise once a reviewer checks it. Recommend fixing this before
  publishing the thesis; flagged here rather than silently changed since it
  affects a headline claim in `README.md`.

- **Frontiers in Blockchain (2021). "Characterizing Wealth Inequality in
  Cryptocurrencies."**
  [frontiersin.org/.../fbloc.2021.730122](https://www.frontiersin.org/journals/blockchain/articles/10.3389/fbloc.2021.730122/full)
  *(search-summary level)* Uses Gini coefficient and related inequality
  measures across multiple cryptocurrencies, providing a comparison baseline:
  Bitcoin's Gini coefficient has been reported near 0.99, with the top 10
  addresses historically holding single-digit percentage shares of total
  supply — a much flatter distribution than this project found for RWA
  tokens (top-10 share 82–100% across the ten measured assets). This contrast
  is worth a sentence in the thesis: tokenized RWA funds are structurally
  closer to a cap table than to a payment network, and their concentration
  numbers should not be read against Bitcoin/Ethereum baselines without
  saying so explicitly.

- **"Distributional equality in Ethereum? On-chain analysis of Ether supply
  distribution and supply dynamics."** *Humanities and Social Sciences
  Communications* (Nature, 2025).
  [nature.com/articles/s41599-025-04728-9](https://www.nature.com/articles/s41599-025-04728-9)
  *(search-summary level)* Methodologically the closest published precedent
  to this project's `holder_snapshots`/`supply_snapshots` reconstruction:
  supply distribution is derived directly from on-chain data rather than
  taken from a provider's report. Worth citing as precedent for the general
  method (reconstruct distribution from the ledger, don't trust a reported
  count), separately from the RWA-specific Mafrur papers in §2.

## 6. On-chain data as a research method

- **OECD (2024). "Concentration of DeFi's liquidity."**
  [oecd.org](https://www.oecd.org/content/dam/oecd/en/publications/reports/2024/04/concentration-of-defi-s-liquidity_5df1e8f9/4ed08440-en.pdf)
  *(search-summary level)* Institutional (non-academic but peer-reviewed
  internally) confirmation that liquidity concentration is a recognized
  policy concern in on-chain markets generally, not just RWA tokens — 20% of
  liquidity pools were found to account for over 90% of trading volume in
  some DEXs. Useful as framing for why concentration metrics (HHI, top-10
  share) matter as *risk* indicators, not just descriptive statistics.

- **General DeFi empirical survey literature** — e.g. "Decentralized Finance
  (DeFi): A Survey," arXiv:2308.05282, and "A Survey of Transaction Tracing
  Techniques for Blockchain Systems," arXiv:2510.09624. *(search-summary
  level, not read in full)* Establish on-chain event logs (`Transfer`,
  contract calls) as an accepted primary data source for empirical financial
  research, and document the general challenge this project's `_sanitize`
  and `_drop_implausible` guards address in a narrow form: raw chain data
  contains adversarial or malformed entries (fake tokens, contract-supplied
  display strings, implausible transfer amounts) that must be filtered before
  they reach a metric.

## 7. What this review does not establish

Stated plainly, matching this project's own documentation style:

- **Most entries above are search-summary or abstract-level, not full-text
  reads.** The exception is Mafrur (2026), read in full because it is close
  enough to this project's topic that a thesis committee will expect a
  precise, first-hand comparison, not one built from an abstract. The other
  entries — Amihud (2002), Datar/Naik/Radcliffe (1998), the ETF and
  stablecoin primary/secondary literature, and the crypto concentration
  papers — should still be read in full before being quoted directly in a
  submitted thesis; they are cited here at the depth needed to scope the
  review, not to finish it.
- **The $0.14-per-$1.00 ETF creation/redemption figure (§4) is unverified
  against a named source.** It came back from a search summary without a
  clean attribution and should not be quoted as a hard number until traced to
  its origin paper.
- **This is not an exhaustive review.** It covers the sources that came back
  from a focused search session in August 2026 across roughly ten queries. A
  thesis-grade literature review should also search Google Scholar and a
  university library database directly (arXiv and SSRN searches undercount
  published journal literature that sits behind a paywall and does not post
  a preprint), and should include Turkish-language sources if the thesis is
  submitted to a Turkish institution that expects them.
- **No paper found here evaluates a public, reproducible, no-API-key
  measurement pipeline for RWA liquidity.** Every comparable study (Mafrur
  2025/2026, Li 2025) relies on RWA.xyz or a comparable licensed data
  provider. Whether that absence is a genuine gap or simply something this
  search didn't surface is worth checking directly with a supervisor before
  stating it as a contribution in the thesis — it is the single strongest
  claim available here, and also the easiest one to overstate.
