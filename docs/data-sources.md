# Data sources

What each provider actually supplies, and what is wrong with it.

The DeFiLlama and Dune sections were verified against the live API on the dates
noted rather than taken from documentation alone. The rwa.xyz section was
**not**: it is gated behind an Enterprise plan with no published price, so that
adapter was written against published documentation and every assumption that
could not be checked is marked as such. The distinction is kept explicit
throughout, because "the docs say" and "we saw it do this" are not the same
claim.

## Summary

| Source | Asset snapshots | Transfers | Holders | Key required |
|---|---|---|---|---|
| `evm_rpc` | yes | yes | yes | **no** |
| `defillama_prices` | yes | no | no | no |
| `defillama_protocol_tvl` | yes | no | no | no |
| `rwa_xyz` | yes* | no | no | yes |
| `dune` | no | yes | yes | yes |

\* **Implemented against published documentation, never run against the live API.**
rwa.xyz's Enterprise gate made a key unreachable for this project. Its tests use
payloads built from the docs, which proves the adapter handles the documented
shape and nothing more. The `network`-marked tests in
`tests/test_sources_keyed_live.py` skip themselves when no credential is set.

Dune was verified live on 2026-08-25: real saved queries against the registry
(with `PAXG` excluded from both -- see below), a real API key, `evm_rpc`'s own
BUIDL figures as an independent cross-check. Dune's 30-day BUIDL transfer count
came back 727 against `evm_rpc`'s 731, and 58 holders against 59 -- close
enough to be the same underlying reality read through two different windows
of "now", not a coincidence worth chasing further.

A source declares its capabilities rather than implementing every method and
returning nothing for the parts it cannot serve. This matters: an empty transfer
frame means "this asset did not trade", which is a finding. A source that cannot
see transfers at all must not be able to produce that finding by accident.

---

## Ethereum JSON-RPC (`evm_rpc`)

Keyless, and the only source that answers all three questions. Verified against a
public endpoint on 2026-07-30.

### Endpoint selection

Most "public RPC" endpoints do **not** serve `eth_getLogs`. Measured across nine
candidates:

| Endpoint | `eth_call` | `eth_getLogs` |
|---|---|---|
| `rpc.mevblocker.io` | yes | **yes, 10,000-result cap** |
| `ethereum-rpc.publicnode.com` | yes | 403 Forbidden |
| `1rpc.io/eth` | yes | capped at 50 blocks |
| `eth.drpc.org` | yes | 400, "can't route your request" |
| `eth-mainnet.public.blastapi.io` | yes | 400 |
| `eth.merkle.io` | yes | method not found |
| `cloudflare-eth.com`, `rpc.ankr.com/eth` | no | no |

`rpc.mevblocker.io` is the default. Override it with `EVM_RPC_URL`.

### What it reads

* `eth_call` for `decimals()`, `totalSupply()`, `symbol()` and `name()`. These are
  contract state, so they are exact rather than a provider's index of it.
  `symbol()` and `name()` are decoded for both the conformant dynamic `string`
  encoding and the older `bytes32` one, because real RWA tokens use both.
* `eth_getLogs` filtered on the `Transfer` topic, from block 0 to the head.

### Sharp edges, all handled

* **Result caps, not pagination.** Nodes reject an over-large log query instead of
  paginating it, and the cap differs by provider. The adapter halves the block
  range on rejection rather than guessing a safe span, which adapts to any
  endpoint at the cost of one wasted request per split. BUIDL's full history took
  nine requests, four of them splits.
* **`blockTimestamp` on logs.** This endpoint includes it, avoiding a request per
  block. Where absent, the adapter looks the block up and caches it. A guessed
  timestamp would move a transfer into or out of its observation window.
* **ERC-721 shares the ERC-20 event signature.** It indexes the token id as well,
  giving four topics instead of three. Four-topic logs are skipped and counted in
  a warning; treating NFT movements as fungible volume would be nonsense.
* **Addresses arrive left-padded** to a full 32-byte word inside indexed topics.
* **Rate limiting.** A full scan issues its requests in a burst, which trips
  Cloudflare's limiter on the endpoint above. Requests are paced 150 ms apart, and
  a 429 is retried after a longer pause than a transient 5xx.

### Holder reconstruction, and why it is verifiable

Balances come from replaying every `Transfer` since deployment as a ledger. The
result is summed and compared against `totalSupply()`.

For BUIDL and OUSG the two matched **to the raw unit**, with zero negative
balances. That makes the distribution correct by construction: there is no
provider to trust and no truncated top-N list, which removes the single largest
caveat on every concentration metric in this package.

A mismatch means balances change by some mechanism other than transfers, most
often a rebasing token, and is reported as making the distribution unreliable.
Negative balances mean the log history is incomplete, and are reported too.

### Where it stops

Tractability rests on tokenized funds being thin. Full histories measured:

| Asset | Logs since deployment | Result |
|---|---|---|
| OUSG | ~2,200 | 1 request |
| BUIDL | ~15,000 | 9 requests, ~3 s |
| PAXG | ~254,600 | refused, over the 250,000 budget |
| XAUt | ~254,300 | refused |

Tokenized commodities trade like ordinary crypto assets. The adapter refuses with
an explanation rather than issuing thousands of requests against a free endpoint.

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

`GET https://api.rwa.xyz/v4/tokens`, authenticated with
`Authorization: Bearer $RWA_XYZ_API_KEY`. Documentation read 2026-07-29.

Filters, sorting and pagination travel in a single `query` parameter holding
URL-encoded JSON: `{"pagination": {"page": 1, "perPage": 100}}`. Pages are
1-based and `perPage` caps at 100.

Three properties of the published schema shape the adapter:

* **There is no symbol field.** Tokens carry `name` but no ticker, so `symbol`
  is left null. Deriving a ticker from a fund's name would be inventing data.
* **There is no observation timestamp.** The response says what a token is worth
  but never when that was true. `as_of` therefore falls back to the retrieval
  time, which is an *upper bound* on the figure's age rather than its age. Any
  comparison of an rwa.xyz figure against a timestamped source inherits that
  uncertainty, and reconciliation should treat small disagreements accordingly.
* **Metrics are nested objects.** `market_value_dollar` is
  `{"val": ..., "val_7d": ..., "chg_7d_pct": ...}`. Only `val` is read; taking
  the object, or the wrong key, would put a week-old figure in a current column.

### Unverified assumptions

* **Chain naming.** The docs do not state the format of `network_name`. The
  adapter lowercases and hyphenates it, so `Ethereum` becomes `ethereum` and
  `BNB Chain` becomes `bnb-chain`. If the real values differ, the fix is a
  `chain_aliases` entry rather than a code change. A wrong chain produces a key
  that fails to match, not one that silently measures the wrong contract.
* **Server-side filtering is not used.** The documented filter syntax could not
  be checked, and a filter that silently matches nothing is indistinguishable
  from an asset that does not exist. The adapter pages the token list and
  matches client-side instead: more requests, but a checkable result, and the
  responses are cached.

## Dune Analytics

`GET https://api.dune.com/api/v1/query/{query_id}/results`, authenticated with
the `X-Dune-Api-Key` header. Documentation read 2026-07-29; verified against
the live API on 2026-08-25, both saved queries actually returning data through
`DuneSource`, not just matching the documented shape.

**PAXG is excluded from both saved queries**, deliberately, not because the SQL
can't express it. `evm_rpc` already can't measure PAXG at all -- its transfer
volume exceeds what a full-history scan against a free endpoint will finish
(`docs/methodology.md`) -- so there is nothing for a Dune figure to reconcile
against, and PAXG is by far the most actively traded asset in the registry:
included, the transfers query returned roughly 453,000 rows for a 90-day
window across eleven assets, almost all of it PAXG. At Dune's free-tier export
rate (1 credit per 1,000 data points), that alone is past the entire monthly
allowance in one pull. Excluding it costs nothing this package can use and
avoids burning a month's credits on a single `--refresh`.

This endpoint returns the **last cached execution** and does not trigger a new
one, though it still consumes credits proportional to result size. Executing a
query costs substantially more, so refreshing the underlying data is a
deliberate act performed in Dune, not a side effect of asking this package a
question.

Pagination follows `next_offset` until it is absent.

### The column contract

Dune has no fixed schema; it runs whatever SQL you saved. The adapter therefore
states what a saved query must return and fails immediately, naming the missing
columns, if it does not. That matters more than it sounds: a query returning the
wrong columns would otherwise produce an empty frame, which reads downstream as
the finding "this asset did not trade".

**Transfers query** must return `block_time`, `tx_hash`, `log_index`,
`contract_address`, `from_address`, `to_address`, `amount`. `amount_usd` is
optional; without it, USD-denominated metrics report themselves undefined rather
than guessing a price. Amounts must be human-scaled, i.e. already divided by the
token's decimals -- **per token**, not by one shared divisor. The registry's
eleven assets are not uniform: checked on-chain, decimals run 6 (BUIDL,
HLSCOPE), 8 (RCOIN, CGT), and 18 (the other seven). The single-address example
below divides by a fixed `power(10, 6)`, which is only correct for BUIDL; a
query scoped to the whole registry needs a `case contract_address when ...`
switch on the divisor, or every non-BUIDL asset comes back scaled a million to
a quintillion times too large. This is exactly the kind of error the column
contract above cannot catch, because the columns are still the right shape --
only the numbers in them are wrong.

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

**Holders query** must return `contract_address`, `address`, `balance`.
`balance_usd` is optional.

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
client-side, so a single saved query can serve many assets and windows off one
cached execution.

### Timestamps

Dune's JSON timestamp format has varied between plain ISO, a `Z` suffix, and a
trailing ` UTC`. The adapter tries explicit formats in order and treats all three
decorations as UTC. A value it cannot parse is an **error**, not a null: a
dropped block time would silently remove a transfer from its observation window
and lower every volume figure.

Timestamps carrying an explicit non-UTC offset are not handled. Adjust the saved
query to emit plain UTC.

### Classifying issuance

The adapter labels every transfer before the metrics layer sees it:

1. Out of the zero address is a mint; into the zero address or a conventional
   burn address is a burn.
2. To or from an address listed in `issuer_addresses` is also primary. Many RWA
   issuers mint one large tranche and then distribute from a treasury, so a
   subscription looks like ordinary trading on chain.
3. Anything else is secondary, and a zero-to-burn transfer is `unclassified`.

**Configuring `issuer_addresses` is the single highest-leverage thing a user of
this package does.** Get it wrong and treasury issuance is counted as trading,
which is the exact overstatement the package exists to prevent. It cannot be
detected with certainty, so the adapter warns whenever every transfer in a window
classifies as secondary and no issuer addresses were supplied.

The CLI does not leave this entirely to the user. `known_addresses.toml`
(`src/rwa_liquidity/sources/known_addresses.py`) is a hand-checked, per-asset
record of `issuer_addresses` and of `excluded_contracts` -- holder-side
addresses (AMM pools, lending vaults) that the concentration and dormancy
metrics should drop before computing a share, for the same underlying reason:
a contract that aggregates many end-users behind one balance is not one
investor. `report` and `trend` load it automatically; the library functions
default to neither list, since supplying either is an editorial act that must
be visible in the call, not assumed on a caller's behalf. As of 2026-08-26 the
file documents holder-side findings for OUSG, USDM, and CANA -- all found by
checking Etherscan's own contract labels, not guessed from balance size --
with no `issuer_addresses` yet verified for any asset; see the file itself for
what was checked and what remains open.
