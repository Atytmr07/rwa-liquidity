# Methodology

Definitions of every measure the package computes, the conventions behind them,
and their limitations.

Notation: an asset `a` is observed over a half-open window `P = [t₀, t₁)`, so
that consecutive windows tile without counting a transfer on a boundary twice.
The default window is 30 days; the paper uses calendar months.

---

## 1. Transfer classification

Every movement of an ERC-20 token emits the same `Transfer` event, whether it
records issuance, redemption, or a transfer between holders. Each transfer is
therefore labelled before any measure is computed:

| Kind | Rule | Interpretation |
|---|---|---|
| `mint` | Out of the zero or dead address, or from a configured issuer address | Issuance or issuer-side distribution |
| `burn` | Into the zero or dead address, or to a configured issuer address | Redemption or other supply reduction |
| `secondary` | No rule above applies | Residual transfer activity (section 1.1) |
| `unclassified` | Out of the zero or dead address and into the zero or dead address | Conflicting conventions |

Volume measures take a mode: `secondary_only` (the default) counts only
`secondary` transfers, `primary_only` counts `mint` and `burn`, and `all`
counts everything. `unclassified` transfers are counted only under `all`, and
narrow-mode results report the share set aside.

A fund that only issues and redeems can record large transfer volume with no
circulation among its holders. Measures that add issuance, redemption and
holder-to-holder transfers together cannot distinguish the two cases.

### 1.1 What `secondary` establishes

`secondary` is defined by exclusion. A `secondary` transfer may still be an
operational movement by an issuer whose address is not documented, a custody
transfer, or a reallocation between addresses controlled by one entity. Nothing
in the transfer log distinguishes these from a trade between two investors.
`secondary_only` therefore measures residual transfer activity, not verified
secondary-market trading. Because off-chain trades leave no transfer at all,
residual volume is in general neither an upper nor a lower bound on trading.

### 1.2 What `mint` establishes

A mint is a contract-recognised increase in supply, not necessarily a
subscription. BUIDL accrues dividends daily and pays them monthly as newly
minted tokens, so part of its creation volume consists of distributions to
existing holders. No field in the transfer distinguishes the two, so a mint
total covers issuance of every kind.

### 1.3 Issuer addresses

Many issuers distribute from a treasury address rather than minting per
subscription, and many redeem through a contract that receives the holder's
tokens and burns them in a second transfer. Transfers to or from such addresses
are classified with issuance and redemption rather than as residual activity.

An address is listed for an asset only when the asset's own issuer documents it
in a published list of contracts or it carries the issuer's label on Etherscan.
Transaction behaviour alone does not qualify an address. The rule is applied in
the same way to every asset; the lists and their sources are in
`src/rwa_liquidity/sources/data/known_addresses.toml`.

Where an asset issues from an undocumented address, its issuance is counted as
residual activity. The classifier warns when every transfer in a window is
`secondary` and no issuer address is configured.

---

## 2. Measures

`V(P, m)` is transfer volume over `P` under mode `m`, `S(t₁)` is supply at the
end of the window, and `H(t₁)` is the number of holders at the end of the
window.

### 2.1 Turnover ratio

```
turnover(P, m) = V(P, m) / S(t₁)
```

Two denominations are implemented. `native` (the default) divides token volume
by token supply and needs no price data. `usd` divides dollar volume by market
value and inherits the pricing convention of the provider. For a fund with a
constant net asset value the two nearly coincide. The denomination is recorded
in the provenance. Turnover is undefined when supply is missing or not positive.

### 2.2 Active holder ratio

```
active_holder_ratio(P, m) = |A(P, m)| / H(t₁)
```

`A(P, m)` is the set of addresses on either side of a counted transfer,
excluding burn addresses. The mode applies, so an address that only received a
mint is not active under `secondary_only`. The ratio can exceed one, because an
address can transfer during the window and hold nothing at its end; such values
carry a warning. The paper uses a bounded version (section 6).

### 2.3 Volume per active address

```
volume_per_active(P, m) = V(P, m) / |A(P, m)|
```

Undefined when no address was active.

### 2.4 Top-n holder share and ownership coverage

```
top_n_share = (sum of the n largest balances) / S(t₁)
```

with `n = 10` by default. Burn addresses are never counted as holders.

Contracts that hold the token on behalf of many end holders, such as pools,
lending vaults, wrappers and bridges, can be excluded through the `exclude`
argument. The library excludes nothing by default; the CLI excludes the
contracts listed in `known_addresses.toml`, each with its Etherscan label, from
the asset they are listed under only.
Issuer treasuries and custodians are not excluded, since each is one economic
entity.

Excluding an address keeps total supply as the denominator, so the remaining
shares sum to the retained coverage `C`. A retained statistic then combines how
much supply the retained addresses hold with how concentrated they are among
themselves. Both are reported:

```
C          = Σ_{retained} bᵢ / S(t₁)
HHI_ret    = 10,000 × Σ_{retained} (bᵢ / S(t₁))²
HHI_cond   = 10,000 × Σ_{retained} (bᵢ / Σ_{retained} bⱼ)²
HHI_ret    = C² × HHI_cond
```

and likewise the top-10 share against total supply and against retained
balances, the latter equal to the former divided by `C`. Without an exclusion
`C = 1` and the two coincide. When an excluded vault grows, every retained
holder's share of total supply falls mechanically, so a falling full-supply
figure does not by itself indicate deconcentration.

When `C` is below one half, conditional figures are not reported, because they
would describe a minority of supply among itself. The paper's panel marks such
windows `assessable = false`.

### 2.5 Holder HHI

```
HHI = 10,000 × Σᵢ (bᵢ / S(t₁))²
```

on the 0 to 10,000 scale: one holder of everything reads 10,000 and ten equal
holders read 1,000. A provider that returns only its top holders biases the
index downward; the metric warns when the rows received cover less than 99% of
the reported holders. If supply is missing, shares fall back to the sum of
observed balances, which hides truncation, and the result carries a warning.
Holder distributions reconstructed on chain are complete and are not affected.

### 2.6 Dormancy

```
dormancy(P, m) = (sum of balances of holders not in A(P, m)) / S(t₁)
```

The share of supply held by addresses with no counted transfer in the window.
Under `secondary_only`, an address that only received a mint is dormant.
Addresses are compared case-insensitively.

---

## 3. Provenance

Every measure returns a value and a provenance record:

| Field | Meaning |
|---|---|
| `metric` | The function that produced the value |
| `asset_uid` | The asset, as `chain:address` |
| `sources` | Every source that contributed |
| `window` | The observation window |
| `mode`, `denomination` | The conventions applied |
| `n_records` | The number of underlying rows after filtering |
| `exclusions` | What was left out, and why |
| `warnings` | Caveats that should accompany the value |

A value that cannot be computed is `None`, never zero. A turnover of `0.0`
records an asset that did not move.

---

## 4. Units and precision

* Token amounts are divided by the token's `decimals`.
* Amounts are stored as `Float64`, exact to about 15 significant digits; the
  package is not intended for unit-level accounting.
* All timestamps are timezone-aware UTC. A timezone-naive column is rejected at
  validation rather than assumed to be UTC.

---

## 5. Limitations

**Off-chain activity.** Transfers settled inside a custodian, on a centralised
venue or by book entry at the issuer are not observed, so an actively traded
asset can appear dormant.

**Addresses are not owners.** One custodian holding for many clients looks like
a single large holder, and one investor using several addresses looks like
several holders. Address concentration can therefore differ from ownership
concentration in either direction.

**Issuer classification depends on documentation.** Undocumented operational
addresses remain residual (section 1.3).

**Reconstructed holder distributions.** The on-chain adapter rebuilds balances
from the full transfer history and compares them with `totalSupply()` at the
block the run reads. The result is exported as `reconciled`: true when the
balances sum to supply with no negative balance, false when they do not, and
empty when supply could not be read at that block. When it is false, every
measure derived from the holder distribution is withheld; when it is empty,
those measures carry a warning. Agreement with total supply is necessary but not
sufficient, since a missing transfer between two holders leaves supply
unchanged.

**Historical windows.** Supply and holder distributions for a past window are
replayed to that window's end rather than taken from the present. Where no
distribution is available for a window, the measure is undefined.

**Collection limits.** A full-history replay stops at 250,000 transfer logs, so
heavily traded tokens such as PAXG are not measured. Free endpoints throttle
sustained scanning; responses are cached as they arrive, so an interrupted run
resumes where it stopped. A request that fails in transit is reported as a
failure rather than retried with a narrower block range.

**Cross-source figures.** Where sources disagree, the package reports the
difference. Where a measure needs one denominator, it takes the most recent
non-null value per field, with ties broken by source name.

**Unverified adapter.** The rwa.xyz adapter has not been run against its live
API (`docs/data-sources.md`).

**Sample data.** The shipped sample dataset is synthetic
(`data/sample/README.md`).

---

## 6. Reproducing a run

**One block per run.** Every command that reads the chain first reads the
current head and pins all later requests to that block, so every asset in a run
describes the same moment. Each exported row records the window's
`start_block` and `end_block`, the first and last blocks whose timestamps fall
in `[t₀, t₁)`, and the `head_block` read. `EVM_RPC_BLOCK_STEP` fixes the block
span of each log request, so a repeated run requests the same ranges and reads
them from the cache.

**Dropped transfers.** A log that moves more tokens than exist at that point in
the ledger is dropped before any measure is computed. The number dropped per
asset is exported as `dropped_transfers`.

**Measured assets.** An asset counts as measured only if both its transfers and
its holder distribution were fetched; otherwise its row states which is
missing, and its measures are undefined.

**The paper's panel.** `rwa-liquidity paper --first-month YYYY-MM
--last-month YYYY-MM --head BLOCK` measures every registry asset over each
calendar month from one block and writes four files to `paper/`: `panel.csv`,
one row per asset and month; `table_turnover.tex`, Table 2 of the paper for the
last month; `table_months.tex`, the median and range of `X` and `F` over the
months for each asset; and `numbers.tex`, macros for the figures quoted in the
text. The panel follows the paper's definitions (`src/rwa_liquidity/paper.py`),
which differ from sections 1 and 2 in two respects:

* **Five event categories.** Creation (out of the zero address), destruction
  (into the zero or dead address), issuer-linked (to or from an issuer
  address), residual (all other transfers) and unresolved (zero address to
  burn address). Creation and destruction take precedence over the issuer rule.
* **Bounded participation.** `P = |A ∩ H| / |H|`, where `H` is the set of
  holders at the window end and `A` the set of addresses on either side of a
  residual transfer of positive value between two different addresses. It
  cannot exceed one.

With `V_all` the total volume and `V_res` the residual volume,
`F = V_all / V_res` is undefined when residual volume is zero, and
`X = 1 − V_res / V_all` is undefined when there was no volume at all.
