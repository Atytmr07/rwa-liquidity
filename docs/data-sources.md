# Data sources

What each provider actually supplies, and what is wrong with it. Everything here
was verified against the live APIs on the date noted, not taken from
documentation.

## Summary

| Source | Asset snapshots | Transfers | Holders | Key required |
|---|---|---|---|---|
| `defillama_prices` | yes | no | no | no |
| `defillama_protocol_tvl` | yes | no | no | no |
| `rwa_xyz` | planned | planned | planned | yes |
| `dune` | no | planned | planned | yes |

A source declares its capabilities rather than implementing every method and
returning nothing for the parts it cannot serve. This matters: an empty transfer
frame means "this asset did not trade", which is a finding. A source that cannot
see transfers at all must not be able to produce that finding by accident.

---

## DeFiLlama

Public, no key. Two endpoints are used, and they measure different things.

### `coins.llama.fi/prices/current/{keys}` — `defillama_prices`

Returns price, symbol, and decimals for a specific token contract.

**It is keyed by `chain:address`**, which is the same canonical key this package
uses. That is convenient rather than a coincidence: a contract address is the
only identifier every on-chain source agrees on, so both arrived at it.

Verified 2026-07-29:

* Both chain aliases work. `avalanche:` and `avax:`, `bsc:` and `binance:`,
  `era:` and `zksync:` all resolve. No alias table is needed.
* **The endpoint echoes the key exactly as sent**, preserving case, so a
  canonical lowercase key comes back lowercase and joins directly.
* **An unknown key returns HTTP 200 with an empty `coins` object**, not an
  error. Assets that fail to resolve are silently absent. The adapter diffs the
  request against the response and logs every omission at warning level; without
  that, a typo in an address produces an empty result that looks like a finding.
* **The zero address resolves.** `ethereum:0x0000...0000` returns a price for
  ETH. Nothing about the response says the key was meaningless.
* Symbol casing is inconsistent: `BUIDL`, `OUSG`, and `PAXG` come back
  uppercase, `xaut` and `ondo` lowercase. Symbols are passed through unchanged.
  Normalizing would hide a property of the source, and nothing joins on symbol.
* Each record carries a `confidence` field (0.99 on everything observed). It is
  dropped at the boundary because the normalized schema has no place for a
  provider-specific quality score. If confidence ever needs to gate a result,
  the raw response is still in the cache to re-derive from.
* The record's `timestamp` is when DeFiLlama observed the price, which is not
  when we asked. It becomes `as_of`; the fetch time becomes `retrieved_at`.
  Using the fetch time for both would shift every observation window by the age
  of the quote.

### `api.llama.fi/protocol/{slug}` — `defillama_protocol_tvl`

Returns the value of a **protocol**, not of a token contract.

* `chainTvls[Chain].tvl` is a per-chain series of `{date, totalLiquidityUSD}`.
  The adapter takes the chain matching the asset's own chain, **not** the
  multi-chain total. For BUIDL those differ by roughly a factor of three
  ($1.16bn on Ethereum against $3.44bn across all chains); using the total would
  overstate the Ethereum contract by that much while looking entirely
  successful.
* The chain key is a capitalised display name (`Ethereum`, `Binance`), unlike
  the lowercase slug used by the coins endpoint. The registry records which to
  use per asset.
* A protocol frequently covers more than one token. BlackRock's covers BUIDL and
  BUIDL-I; Ondo's umbrella covers several products. **Its figure is an upper
  bound on any single contract, not a measurement of it.**
* `tvl` can be `null` for some protocols.
* An unknown slug returns HTTP 400 with a plain-text body, not JSON.

### Why the mapping file is maintained by hand

DeFiLlama's protocols endpoint has an `address` field. It cannot be used to
derive the asset mapping. Verified 2026-07-29 across the 153 protocols in the
`RWA` category:

* **90 of 153 have no address at all**, including BlackRock BUIDL and Circle
  USYC, two of the largest.
* Where an address is present the format is inconsistent. `paxos-gold` reports a
  bare `0x45804880...`; `blockchain-capital` reports `era:0x57fD71a8...`, prefixed
  with a DeFiLlama-specific chain alias. No field says which form was used.
* **The address often identifies the wrong token.** `ondo-yield-assets` reports
  `0xfaba6f8e...`, which resolves to ONDO, Ondo's governance token, and not to
  any tokenized treasury product the protocol issues. `ondo-global-markets`
  reports the same address.

Guessing from that field would produce confident metrics for the wrong asset. So
`src/rwa_liquidity/sources/data/defillama.toml` states each mapping explicitly,
with a `notes` field recording what is imprecise about it. The OUSG entry is the
clearest case: OUSG has no protocol slug of its own, so it is mapped to the Ondo
umbrella, and its note says so. Reconciliation against that entry is *expected*
to disagree, and the disagreement is informative rather than a bug.

### What DeFiLlama cannot do

Neither endpoint publishes transfer-level or holder-level data. That means
DeFiLlama alone cannot produce a single one of this package's liquidity metrics.
It supplies the value denominators and a cross-check on them; the numerators come
from Dune.

---

## rwa.xyz

*Not yet implemented (Phase 5).* Asset metadata, issuers, networks, market
values, holder counts. Access is gated behind an API key.

## Dune Analytics

*Not yet implemented (Phase 5).* Transfer-level and holder-level on-chain data
via saved queries. Requires an API key and the query IDs named in `.env.example`.

This is the only planned source for the transfer data every volume metric needs,
which is why the sample dataset shipped for demo mode is synthetic: no keyless
source can produce a real one.
