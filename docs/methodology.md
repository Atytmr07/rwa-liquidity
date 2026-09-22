# Methodology

Every metric this package computes, how it is computed, and what is wrong with
it. If a number from `rwa-liquidity` appears in a paper, this document is what
justifies it.

Notation: an asset `a` is observed over a half-open period `P = [t₀, t₁)`.
Half-open so consecutive windows tile without double-counting a transfer that
lands exactly on a boundary. The default is 30 days.

---

## 1. The primary/secondary distinction

This is the package's central methodological claim, and it comes before the
formulas because it changes all of them.

Every movement of an ERC-20 token emits the same `Transfer` event, but three
economically different things hide behind it:

| Kind | What happened | Liquidity meaning |
|---|---|---|
| `mint` | Tokens created and issued to an investor | The investor bought **from the issuer**. No secondary market involved. |
| `burn` | Tokens returned to the issuer and destroyed | The investor redeemed. Again no secondary market. |
| `secondary` | Neither end of the transfer is a burn address or a confirmed issuer address | Not issuance. Consistent with trading, but see §1.1. |
| `unclassified` | Could not be determined | Unknown. |

A tokenized fund that only mints and redeems **has no secondary market**,
however large its raw transfer volume looks. Its investors cannot trade with
each other, only with the issuer; if the issuer stops redeeming, there is no
exit. That is a categorically different liquidity position from an asset whose
holders trade among themselves, and any measure that adds the two together
obscures it.

Every volume-based metric therefore takes a **mode**:

* `secondary_only` — **the default.** Counts only transfers that are not
  issuance or redemption.
* `primary_only` — counts issuance and redemption only.
* `all` — counts everything.

`secondary_only` is the default because the error it produces runs in the safe
direction. A careless user under-reports liquidity rather than over-reporting
it, which is the right way round for published work.

### 1.1 What `secondary` does and does not establish

`secondary` is defined by exclusion: neither end of the transfer is a burn
address, and neither is an issuer address that has been configured and
confirmed. That is a weaker statement than "two investors traded with each
other," and the difference matters when the figure is quoted.

A `secondary` transfer may still be any of the following, none of which is a
trade:

* a treasury or operational movement by an issuer whose address is **not**
  in `known_addresses.toml`, because nobody has identified and verified it yet;
* a custody transfer, for instance an investor moving a position into or out
  of a custodian's wallet;
* wallet restructuring, where one entity moves its own holdings between
  addresses it controls.

Nothing in an `eth_getLogs` scan distinguishes those from a genuine
holder-to-holder trade. Identifying them would need address-level entity
resolution applied to transfers, which this package does not attempt. The
`issuer_addresses` mechanism handles one slice of the problem, the
issuer-side slice, and only for addresses that a block-explorer label or
issuer documentation has confirmed by hand.

**The correct reading, therefore, is that `secondary_only` measures
non-issuance transfer activity, and that this is an upper bound on genuine
secondary-market trading.** This cuts in a useful direction for the headline
comparison: if the secondary-only figure is an upper bound on real trading,
then the ratio between raw turnover and secondary-only turnover is a *lower*
bound on how much raw transfer volume overstates real trading. An asset
reported at 10.8x is overstated by at least that much, not at most.

### Why `unclassified` exists

An ambiguous transfer is not assigned to either bucket. Calling it secondary
would overstate liquidity — the exact failure this package exists to prevent —
and calling it primary would understate it. It is counted only under `all`, and
any narrow-mode result reports what share was set aside, so the value is
understood as a lower bound on activity.

### How the classification is made

1. **Zero-address rule.** A transfer out of `0x0000…0000` is a `mint`; one into
   it, or into `0x0000…dEaD`, is a `burn`.
2. **Issuer rule.** Many RWA issuers do not mint per subscription. They mint one
   large tranche and distribute from a treasury address, so a subscription looks
   like an ordinary transfer on chain. Where the treasury address is known it is
   supplied through `issuer_addresses`, and transfers to or from it are primary.
3. Anything else is `secondary`. A zero-to-burn transfer is `unclassified`.

**This is the largest single source of error in the package.** If an asset
issues from a treasury and no issuer address is configured, its issuance is
counted as trading and its liquidity is overstated. It cannot be detected with
certainty, so the classifier warns whenever every transfer in a window comes out
secondary and no issuer addresses were supplied. Treat that warning as a request
to go and look.

---

## 2. The metrics

Throughout, `V(P, m)` is total transfer volume over `P` under mode `m`, `S(t₁)`
is total supply at the end of the window, and `H(t₁)` is the reported holder
count at the end of the window.

### 2.1 Turnover ratio

```
turnover(P, m) = V(P, m) / S(t₁)
```

**Units.** The specification defines this as volume over *total asset value*.
Two readings are possible and both are implemented:

* `native` (**the default**) divides token volume by total supply. It needs no
  price series, so it is exactly reproducible from the transfer data alone.
* `usd` divides dollar volume by market value. It matches the specification's
  wording literally, but no source publishes a price for every individual
  transfer, so a USD figure inherits whatever pricing convention the provider
  used — rarely documented, never uniform across providers.

For a constant-NAV fund the two nearly coincide. For anything whose price moves
they do not. **The default is a deviation from the literal specification, taken
because reproducibility mattered more than literalism.** Set
`denomination="usd"` for the other reading; the choice is recorded in the
provenance either way.

**Undefined when** supply is absent or non-positive. Reported as `None`, never
as zero — a turnover of `0.0` means an asset with supply that did not trade,
which is a finding, while `None` means we could not tell.

### 2.2 Active holder ratio

```
active_holder_ratio(P, m) = |A(P, m)| / H(t₁)
```

where `A(P, m)` is the set of addresses appearing on **either side** of a
counted transfer. An address that received tokens participated in the market;
counting senders only would treat every buyer as dormant.

Burn addresses are excluded. The zero address is a bookkeeping artifact of
issuance, not a participant, and leaving it in would add one phantom active
address to every asset that has ever minted.

**The mode filter applies here too.** An address that received a mint and never
traded is not active under `secondary_only`. Applying the filter only to volume
metrics would let one dataset report an asset as fully active and never traded
at the same time.

**This ratio can exceed 1**, and is reported rather than clamped when it does.
An address can trade during the window and hold nothing at the end of it, so the
numerator counts people the denominator does not. That is churn, which is itself
a liquidity signal; clamping would hide it. A value above 1 carries a warning
saying so.

### 2.3 Volume per active address

```
volume_per_active(P, m) = V(P, m) / |A(P, m)|
```

Same active-address definition as above. **Undefined when** no address was
active — a denominator that does not exist, which is different from every active
address having moved nothing.

### 2.4 Top-N holder share

```
top_n_share = (Σ of the n largest balances) / S(t₁)
```

Default `n = 10`.

**Exclusions.** Burn addresses are always excluded: tokens sent there are
destroyed and their holder is not a participant. Beyond that, `build_report`'s
`exclude` argument defaults to empty -- calling the library directly excludes
nothing but burns unless the caller says otherwise, because excluding an
address is an editorial judgement that must be visible, not assumed.

The CLI (`report`, `trend`) does supply a default: every address listed in
`known_addresses.toml`, a hand-checked file of contracts confirmed to
aggregate many end-holders behind one balance -- an AMM pool, a lending vault
that accepts the asset as collateral -- with an Etherscan label or equivalent
citation for each entry (`src/rwa_liquidity/sources/known_addresses.py`). This
is deliberately narrower than "everything that isn't an individual investor":
issuer treasuries and custody addresses are left in because they are usually
one economic entity, same as an investor's own wallet, and bridge contracts
are left in and disclosed rather than excluded, because this package measures
one chain and a bridge holding an asset in escrow is a fact about supply
leaving that chain, not a DeFi contract standing in for many end-holders. Only
the assets in `known_addresses.toml` have been checked; an asset absent from
it has not been, which is not the same as "checked and clean" -- see that
file's own notes for what was found and when.

For tokenized funds this matters a lot regardless of which exclusions apply. A
lending vault or an issuer holding unsold inventory can dominate the holder
list, and the resulting concentration figure then describes vault or inventory
concentration rather than investor concentration. Read the exclusions field
before quoting the number.

### 2.5 Holder HHI

```
HHI = 10,000 × Σᵢ (bᵢ / S(t₁))²
```

The Herfindahl-Hirschman index on the conventional 0–10,000 scale, so that a
single holder owning everything reads 10,000 and ten equal holders read 1,000.

**The truncation problem.** Providers routinely return only the top N holders.
Shares are computed against total supply, so a truncated list produces shares
summing to less than one and an HHI biased **downward** — the asset looks less
concentrated than it is. This cannot be corrected, only disclosed. The metric
compares the rows it received against the reported holder count and warns when
coverage falls below 99%, stating the true value is higher than reported.

If `total_supply` is missing entirely, shares fall back to the sum of observed
balances. That forces them to sum to one, which *hides* truncation instead of
revealing it, so this case is warned about explicitly and the result should be
read as an upper bound on concentration.

### 2.6 Dormancy

```
dormancy(P, m) = (Σ of balances of holders not in A(P, m)) / S(t₁)
```

The share of supply held by addresses that did not transfer during the window.

Under the default `secondary_only` mode, **an address that received a mint and
never traded is dormant**. That is the intended reading: taking delivery of an
issuance is not market participation. It is also why the sample dataset's
`SYNTH-TBILL` reads 100% dormant under the default and 3% under `all`.

Address comparison is case-insensitive, because one source may report EIP-55
checksummed addresses where another reports lowercase, and a case mismatch would
silently mark every active holder dormant.

---

## 3. Provenance

Every metric returns a value **and** a record:

| Field | Meaning |
|---|---|
| `metric` | Which function produced the value |
| `asset_uid` | The asset, as `chain:address` |
| `sources` | Every source label that contributed |
| `window` | The observation period |
| `mode`, `denomination` | The conventions applied |
| `n_records` | How many underlying rows survived filtering |
| `exclusions` | What was deliberately left out, and why |
| `warnings` | What is doubtful about the value |

A non-empty `warnings` list does not mean the value is wrong. It means it should
not be quoted without the caveat.

### `None` means undefined, never zero

This is enforced throughout. Collapsing "we could not compute this" into `0.0`
would put a fabricated number in a table, and a fabricated zero is worse than a
gap because it looks like a measurement.

---

## 4. Units and precision

* **Token amounts are human-scaled**, already divided by the token's `decimals`.
* They are stored as `Float64`, exact to about 15 significant digits. That is
  far beyond the precision any liquidity ratio can carry, but it means **this
  package must not be used for wei-level accounting.**
* **All timestamps are timezone-aware UTC.** A timezone-naive column is rejected
  at the validation boundary rather than assumed to be UTC: every metric is
  defined over an observation window, so a source reporting local time would
  produce windows wrong by its offset with no visible symptom.

---

## 5. Limitations

Things this package cannot do, stated plainly.

**On-chain data is not the whole market.** Transfers settled off-chain — inside a
custodian, on a centralised venue, or via book-entry at the issuer — are
invisible. An asset can be actively traded and read as dormant here.

**Addresses are not people.** Concentration is measured over addresses, not
beneficial owners. One custodian holding for a thousand retail clients is
indistinguishable from a single whale, and one investor split across ten
addresses is indistinguishable from ten investors. Both HHI and top-N share are
therefore bounds, not measurements, and in opposite directions.

**Issuer classification is configuration, not detection.** See §1. An unconfigured
treasury silently converts issuance into apparent trading.

**Holder lists are usually truncated.** See §2.5.

**Snapshot timing is uneven.** rwa.xyz publishes no observation timestamp at all,
so its `as_of` is only an upper bound on the figure's age. A disagreement between
it and a precisely-timestamped source may be nothing but elapsed time, which the
reconcile layer flags rather than assumes away.

**Cross-source figures are reconciled, not resolved.** Where two sources disagree
the package reports the gap and picks neither. Where a metric needs a single
denominator, it takes the most recent non-null value per field with ties broken
deterministically by source name — a mechanical rule, not a judgement about which
provider is right.

**The holder distributions behind the published findings are verified, not trusted.** They are reconstructed from the full on-chain transfer history and checked against each contract's `totalSupply()`; a mismatch is reported as making the distribution unreliable. That removes the truncation caveat in SS2.5 for any asset measured through `evm_rpc`, and only for those.

**Historical windows use historical state.** Supply and holder distributions for
a past window are replayed from the ledger to that window's end, not taken from
the present. Using today's figures would be an error rather than an
approximation: a share computed from today's balances against an earlier, smaller
supply exceeds 1, which the metrics refuse outright. Where no distribution is
known for a window the metric is undefined rather than filled in from a later
one.

**Full-history reconstruction has a ceiling.** Past roughly 250,000 transfer logs the scan is refused rather than run against a free public endpoint, so actively traded tokens cannot be measured this way at all.

**The free endpoint rate-limits sustained scanning, and a full-history walk is
sustained scanning.** A cold scan of the whole registry is roughly 6,000 log
queries, and the endpoint answers a few hundred of those before replying "service
temporarily unavailable" for a while. The adapter waits and retries, then reports
the asset as unfetched rather than pressing; every window already retrieved stays
cached, so resuming later costs only what is left. This is a property of free
infrastructure rather than of the method: `EVM_RPC_URL` points the adapter at an
endpoint with more headroom, at the cost of the no-credentials property that
makes the published findings reproducible by a stranger.

**A scan gives up on a network fault rather than working around it.** A node
that refuses a log query because it would return too many results is answered
by halving the block range; a request that never reached the node is not. The
difference matters because the two are indistinguishable from inside the
adapter unless the transport says which happened, and treating a dropped
connection as a verdict on the range subdivides it into two requests that fail
the same way, then four. An asset whose scan hits a network fault is therefore
reported as a failure and skipped, with the rest of the registry unaffected;
because responses are cached individually as they arrive, re-running resumes
from where it stopped rather than starting over.

**Two of the five adapters have never run against their live APIs.** rwa.xyz and
Dune were implemented against published documentation because no keys were
available. Their tests prove they handle the documented shapes and nothing more.
See `docs/data-sources.md` for the specific assumptions that remain unverified.

**The shipped sample dataset is synthetic.** It demonstrates the metrics; it
measures nothing. See `data/sample/README.md`.
