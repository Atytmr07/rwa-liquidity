# Data sources

What each source supplies, how the adapter reads it, and its limitations.

## Summary

| Source | Asset snapshots | Transfers | Holders | Key required | Run against the live API |
|---|---|---|---|---|---|
| `evm_rpc` | yes | yes | yes | no | yes |
| `defillama_prices` | yes | no | no | no | yes |
| `defillama_protocol_tvl` | yes | no | no | no | yes |
| `rwa_xyz` | yes | no | no | yes | no |
| `dune` | no | yes | yes | yes | yes |

The rwa.xyz adapter is written against the published documentation only; its
tests use payloads built from that documentation, and its unverified
assumptions are listed below. The `network`-marked tests in
`tests/test_sources_keyed_live.py` skip themselves when no credential is set.

A source declares its capabilities instead of returning empty frames for the
parts it cannot serve. An empty transfer frame means that the asset did not
move, which is a result; a source that cannot see transfers must not be able to
produce that result by accident.

---

## Ethereum JSON-RPC (`evm_rpc`)

Keyless, and the only source that supplies supply, transfers and holder
balances together. The default endpoint is `rpc.mevblocker.io`, one of the few
public endpoints that serve `eth_getLogs` over wide block ranges. Override it
with `EVM_RPC_URL`.

### What it reads

* `eth_call` for `decimals()`, `totalSupply()`, `symbol()` and `name()`, read
  at the run's pinned block. `symbol()` and `name()` are decoded for both the
  dynamic `string` encoding and the older `bytes32` one.
* `eth_getLogs` on the `Transfer` topic, from the contract's deployment block to
  the pinned block. The deployment block is found by a binary search on
  `eth_getCode`.

### Handling

* **Block ranges.** Endpoints cap a log query by block span. The adapter
  discovers the cap once per run, or takes it from `EVM_RPC_BLOCK_STEP`, and
  scans in aligned windows of that size, so cache keys stay stable from run to
  run. A window whose results the node refuses is split in half.
* **Throttling.** A node that answers with JSON-RPC error `-32603` is
  throttling; the request is retried after a pause rather than split. Calls
  that reach the node are paced 150 ms apart; cache hits are not paced.
* **Caching.** Every successful response is cached by request. Error responses
  are never cached, and an error found in an older cache is requested again.
* **Timestamps.** Logs carry `blockTimestamp` on the default endpoint. Where it
  is absent, the block is looked up and cached.
* **ERC-721.** ERC-721 transfers share the ERC-20 event signature but carry a
  fourth topic. Four-topic logs are skipped and counted in a warning.
* **Implausible logs.** A log that moves more tokens than exist at that point in
  the ledger is dropped before any metric is computed, and the number dropped is
  exported per asset.

### Holder reconstruction

Balances are replayed from every `Transfer` since deployment. The positive
balances are summed and compared with `totalSupply()` at the pinned block, and
the outcome is exported as `reconciled`. A mismatch means balances change by
some mechanism other than transfers, as with a rebasing token, or that the
history is incomplete; negative balances indicate the latter. Holder metrics are
withheld when the check fails.

### Limits

A full-history replay is feasible because most tokenized funds have short
histories: at block 26,086,416, BUIDL's history is 16,527 logs and OUSG's about
2,200. Actively traded tokens are not: a scan stops at 250,000 logs, and PAXG
and XAUT both exceed it.

---

## DeFiLlama

Public, no key. Two endpoints are used, and they measure different things.

### `coins.llama.fi/prices/current/{keys}` (`defillama_prices`)

Returns price, symbol and decimals for a token contract, keyed by
`chain:address`, the same canonical key this package uses.

* The endpoint echoes the key as sent, so a lowercase key joins directly.
* An unknown key returns HTTP 200 with an empty `coins` object rather than an
  error. The adapter compares request and response and logs every omission.
* Symbol casing is inconsistent across tokens and is passed through unchanged.
* The record's `timestamp` is when DeFiLlama observed the price and becomes
  `as_of`; the fetch time becomes `retrieved_at`.

### `api.llama.fi/protocol/{slug}` (`defillama_protocol_tvl`)

Returns the value of a protocol, not of a token contract.

* The adapter reads `chainTvls[Chain].tvl` for the asset's own chain, not the
  multi-chain total.
* A protocol often covers more than one token, so its figure is an upper bound
  on any single contract.
* An unknown slug returns HTTP 400 with a plain-text body.

### The registry

DeFiLlama's own `address` field cannot be used to map protocols to tokens: most
RWA protocols have none, the format is inconsistent, and many listed addresses
are governance tokens. `src/rwa_liquidity/sources/data/defillama.toml` therefore
states each mapping explicitly, with a note on any imprecision.

DeFiLlama publishes no transfer-level or holder-level data, so it supplies value
figures and a cross-check on supply, not the activity measures.

---

## rwa.xyz

`GET https://api.rwa.xyz/v4/tokens`, authenticated with
`Authorization: Bearer $RWA_XYZ_API_KEY`. Filters, sorting and pagination are
passed as URL-encoded JSON in a single `query` parameter; pages are 1-based and
`perPage` is at most 100.

* Tokens have a `name` but no ticker, so `symbol` is left empty.
* Responses carry no observation timestamp, so `as_of` falls back to the
  retrieval time, an upper bound on the figure's age.
* Metrics are nested objects such as `{"val": ..., "val_7d": ...}`; only `val`
  is read.

### Unverified assumptions

* **Chain naming.** The format of `network_name` is not documented. The adapter
  lowercases and hyphenates it; a different format would need a
  `chain_aliases` entry.
* **Filtering.** The documented server-side filters are not used. The adapter
  pages the token list and matches client-side.

---

## Dune Analytics

`GET https://api.dune.com/api/v1/query/{query_id}/results`, authenticated with
the `X-Dune-Api-Key` header. The endpoint returns the last cached execution of
a saved query and does not run it again. Pagination follows `next_offset`.

### Column contract

A saved query must return the columns the adapter needs, or the adapter fails
and names the missing columns; a query with the wrong columns would otherwise
produce an empty frame that reads as "this asset did not move".

**Transfers query:** `block_time`, `tx_hash`, `log_index`, `contract_address`,
`from_address`, `to_address`, `amount`, and optionally `amount_usd`. Amounts
must be divided by each token's own decimals; a query covering several tokens
needs a per-contract divisor.

```sql
select
    evt_block_time                          as block_time,
    evt_tx_hash                             as tx_hash,
    evt_index                               as log_index,
    contract_address,
    "from"                                  as from_address,
    "to"                                    as to_address,
    value / power(10, 6)                    as amount
from erc20_ethereum.evt_Transfer
where contract_address = 0x7712c34205737192402172409a8f7ccef8aa2aec
  and evt_block_time >= now() - interval '90' day
```

**Holders query:** `contract_address`, `address`, `balance`, and optionally
`balance_usd`.

```sql
with moves as (
    select "to" as address, contract_address, cast(value as int256) as delta
    from erc20_ethereum.evt_Transfer
    where contract_address = 0x7712c34205737192402172409a8f7ccef8aa2aec
    union all
    select "from" as address, contract_address, -cast(value as int256) as delta
    from erc20_ethereum.evt_Transfer
    where contract_address = 0x7712c34205737192402172409a8f7ccef8aa2aec
)
select contract_address, address, sum(delta) / power(10, 6) as balance
from moves
group by 1, 2
having sum(delta) > 0
```

Scope each query to one chain. The adapter filters rows to the asset and window
client-side, so one saved query can serve many assets and windows.

### Timestamps

Dune's timestamps appear in plain ISO, with a `Z` suffix, or with a trailing
` UTC`; all three are read as UTC. A value that cannot be parsed is an error, not
a null, since a dropped timestamp would remove a transfer from its window.

---

## Classification and address lists

Every transfer is labelled before the metrics see it: out of the zero address is
a mint, into the zero or dead address a burn, to or from a configured issuer
address primary, and anything else secondary. The paper's five-category version
of these rules is described in `docs/methodology.md`, section 6.

`src/rwa_liquidity/sources/data/known_addresses.toml` records, per asset, the
issuer addresses and the contracts excluded from the holder distribution, with
the rule each list follows and the evidence for each entry. `report`, `trend`
and `paper` load it automatically; the library functions apply neither list
unless the caller passes it.
