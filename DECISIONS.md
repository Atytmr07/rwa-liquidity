# Design decisions

Every non-trivial architectural choice, with its alternatives and the reason it
went the way it did. Newest first. The point of this file is to make the design
defensible in conversation months from now.

> Most entries here were decided without review, on instruction to keep
> building rather than wait for answers. Each records the alternative that was
> rejected, and every one is a small change to reverse. They are the entries to
> read first if the results ever look wrong.
>
> The two most consequential: turnover is token-denominated by default rather
> than USD-denominated, and `secondary_only` is the default volume mode.

---

## 2026-08-14 -- The window size is read from the node, not inferred from failures

**Decided:** `_discover_step` asks for the whole chain once and reads the limit
out of the refusal ("range 24999999 exceeds limit of 10000"), falling back to
bisection only when the node does not say. A window refused for holding too many
logs splits on its own and no longer narrows the shared step.

**Alternatives:** bisect for the limit; keep narrowing the shared step on any
refusal; hard-code a step per endpoint.

**Why:** both of the things this replaces were mine, and both cost a run.

Narrowing the shared step on any refusal treated one token's log density as a
fact about the endpoint. BUIDL crowds 11,622 mints into a few million blocks, so
its windows were refused for holding too much; the step fell to its 500-block
floor and stayed there for every window afterwards and every asset behind it.
Read back out of the cache, the five-hour run was asking for 500 blocks at a
time, all of it for one address. Density is local and the recursion already
handles it; the step is for the endpoint's span limit alone.

Bisecting for that limit then settled on 6,236 against a real limit of 10,000,
because a probe refused for any other reason -- a rate limit, most likely -- is
indistinguishable from "too wide" and drags the estimate down permanently. Same
conflation as the one below, one level up, and the honest fix is the same: stop
inferring what the node will state outright. One request, exact, and the
bisection survives as a fallback where it is merely slow rather than wrong.

Probes go to the zero address, which emits no `Transfer` anywhere, so the span
is the only thing left to refuse. Probing the token being scanned mixed the
endpoint's limit with that token's density at exactly the wrong place: issuance,
the densest stretch of a fund's history, is where the probe would start.

Measured against the default endpoint: the limit reads exactly 10,000 in a
single request, and BUIDL's walk went from 1,028 windows to 641.

---

## 2026-08-13 -- A rejected request and an unreachable one are different failures

**Decided:** `SourceTransportError` is split out of `SourceFetchError` for
failures where the endpoint never rendered a verdict -- a connection that did not
land, a 429, a 5xx that outlived its retries. `EvmRpcSource._logs` halves its
block range only on a real rejection, and lets a transport fault out.

**Alternatives:** keep one error type and cap the recursion depth; retry
indefinitely inside the scan; treat every failure as a rejection, as before.

**Why:** this was a live bug, not a hypothetical. The splitter existed because
nodes cap `eth_getLogs` results rather than paginating, so a rejected range is
usefully answered by asking for half of it. But every failure arrived as the same
`SourceFetchError`, so when this machine lost DNS part-way through a scan, each
failed query was "answered" by two narrower queries that failed identically, then
four. A registry scan that should take about an hour ran for **seven and a half
hours** and had written 59,000 cache entries when it was stopped, still going.

The tell was that it was not stuck -- it was making steady progress through
exponentially more work than the task required. A depth cap would have bounded
the damage without fixing the cause; the cause is that the adapter was reacting
to information it did not have.

Failing the asset is the right outcome rather than a retreat: the pipeline
already records per-asset failures without discarding the rest of the registry,
and because responses are cached individually as they arrive, a re-run resumes
instead of restarting. Retrying the same request is still done, at the transport
layer where it belongs, three times with a linear backoff.

`max_log_requests` (default 2,000) is a backstop for the whole class of fault
rather than this instance of it. It would not have caught this particular bug
quickly -- a rejection chain does terminate on its own once a span reaches one
block -- but it turns any future non-converging split into an error naming the
cause instead of an unbounded wait.

The regression test asserts the property rather than the symptom: with the
endpoint answering everything except log queries, exactly one distinct block span
may be attempted. Against the old code it records 26 and takes 157 seconds
instead of 7 -- the incident in miniature.

---

## 2026-07-30 -- History is reconstructed, not extrapolated backwards

**Decided:** supply and holder distributions for a past window are replayed from
the transfer ledger to that window's end. `EvmRpcSource.supply_snapshots` and
`holder_snapshots` produce them; `latest_holders` selects the one belonging to the
window being measured.

**Alternatives:** apply the current figures to every window; trend only the
denominator-free metrics.

**Why:** Applying today's supply backwards is not an approximation but an error.
BUIDL's supply across the six trended windows was 172m, 169m, 148m, 178m, 187m
and 225m; dividing an early window's volume by 225m would understate its turnover
by a third. For holders it is worse -- today's balances against an earlier,
smaller supply give a share above 1, which the metrics refuse, so the series came
back full of holes rather than merely wrong.

The ledger already walked for the present distribution answers both exactly, from
the same cached scan. That is the argument for deriving this data rather than
fetching it, made a second time: no provider publishes a supply history or a
holder history, and both fall out of a walk already being done.

`latest_holders` was the missing piece. Without it the metrics summed every
instant in a multi-snapshot holder frame, multiplying the balances and tripping
the share guard on every asset.

---

## 2026-07-30 -- The issuer caveat is checked rather than assumed

**Decided:** `EvmRpcSource.describe_issuance` profiles a token's complete history
and reports whether any issuance passes through the zero address.

**Alternatives:** keep the blanket caveat; try to infer issuer addresses
automatically.

**Why:** The methodology's largest stated weakness was that an issuer
distributing from a treasury would have its issuance counted as trading, and that
this could not be detected. For an adapter that already replays full history, it
partly can: a token that has *ever* minted through the zero address has visible
issuance, so a window without mints simply means issuance happened earlier.

Run against the registry, **all ten measurable assets mint through the zero
address**, which turns a caveat on every published figure into a checked fact.
That is worth more than the code that produces it.

Issuer addresses are still not inferred. Where issuance is invisible the command
names the largest recipient of supply as a *candidate* for review; guessing wrong
would move real trading into the primary bucket, which is the same error in the
opposite direction.

---

## 2026-07-30 -- A keyless on-chain adapter, and holder balances derived rather than fetched

**Decided:** `EvmRpcSource` reads `eth_getLogs` and `eth_call` from a public
Ethereum endpoint, and reconstructs holder balances by replaying a token's entire
`Transfer` history from deployment.

**Alternatives:** wait for a Dune key; ship only synthetic demonstrations; take a
provider's holder index on trust.

**Why:** The package could demonstrate its metrics but had measured nothing. Every
metric needs transfer-level data and every provider selling it needs a key, so the
repository's central claim rested entirely on constructed data. A public node
serves the same data for free.

**The part that makes it worth more than a workaround:** after replaying the
ledger, the reconstructed balances are summed and compared against the contract's
own `totalSupply()`. For BUIDL and OUSG they matched to the raw unit with zero
negative balances, which makes the holder distribution correct *by construction*.
That removes the truncation caveat that would otherwise sit on every concentration
metric, and it is only possible because the data is derived rather than fetched. A
mismatch means balances change by some mechanism other than transfers -- rebasing,
most often -- and is reported as making the distribution unreliable rather than
being quietly absorbed.

**Why it is tractable at all:** replaying a full history sounds prohibitive and is
not, for exactly the assets this package studies. Tokenized funds are thin --
BUIDL's complete history is ~15,000 logs in nine requests. Tokenized commodities
are not: PAXG and XAUt exceed 250,000 logs and are refused. The boundary is
informative in itself, and it is enforced with a budget rather than discovered by
hammering a free endpoint.

**Endpoint choice was measured, not assumed.** Of nine candidate public endpoints,
one served `eth_getLogs`: `rpc.mevblocker.io`. The rest answered `eth_call` and
then returned 403, a 50-block cap, or a routing error. The table is in
`docs/data-sources.md` so the choice can be rechecked rather than trusted.

---

## 2026-07-30 -- An observed holder distribution outranks a reported count

**Decided:** `active_holder_ratio` uses the row count of an observed
`HolderBalance` frame as its denominator when one is available, falling back to a
source's reported `holder_count` only when it is not.

**Alternatives:** always use the reported count; require the caller to choose.

**Why:** A distribution reconstructed from the full transfer history and checked
against on-chain supply is exact. A provider's `holder_count` is a figure taken on
faith, and is frequently absent -- which left the metric undefined for every live
measurement even though the holder set was sitting in the next frame along. The
provenance records which denominator was used and names the reported count when
the two disagree, so the substitution is visible rather than silent.

---

## 2026-07-30 -- Snapshots are accepted up to an hour after a window closes

**Decided:** `latest_snapshot` accepts observations up to `SNAPSHOT_GRACE`
(one hour) past the window's end, and refuses anything later.

**Alternatives:** require every snapshot at or before the window end.

**Why:** A live source reads the chain as it is *now*, and a full-history scan
takes minutes. A snapshot requested for a window ending at the moment of the
request therefore always arrives after it, so the strict rule silently discarded
every on-chain supply figure and reported turnover as undefined.

The first attempt at this applied the grace only when *nothing else* qualified,
which was not enough: a price feed whose timestamp happened to fall inside the
window won outright, and the supply that had been fetched correctly still read as
missing. The grace now applies to the cutoff itself. An hour against a 30-day
window is immaterial; a day is not, and still raises.

---

## 2026-07-29 -- The LaTeX writer is hand-written, not `pandas.to_latex`

**Decided:** `export/writers.py` renders LaTeX itself, in about forty lines.

**Alternatives:** `pandas.to_latex`; `tabulate`.

**Why:** The output of this package is meant for a paper, and a table going into
a paper needs control over column alignment, significant figures, and caption.
`to_latex` gives a table whose formatting then has to be fought, and it would
promote pandas from an optional extra to a real dependency to get there.

Two details that are easy to get wrong and are therefore tested: LaTeX special
characters are escaped, because asset uids and source names contain underscores
and an unescaped table simply fails to compile; and an undefined metric renders
as `--` rather than a blank cell, because a blank reads as an oversight while
`--` reads as a result.

---

## 2026-07-29 -- `latest_snapshot` merges across sources field by field

**Decided:** when several sources describe an asset, each field takes the most
recent non-null value, with ties broken by source name.

**Alternatives:** take the single most recent row; require the caller to pick a
source.

**Why:** Sources publish different subsets. DeFiLlama has no holder counts; an
on-chain source has no stated market value. Taking one winning row discarded
fields another source did report, and *which* row won depended on an unstable
sort -- the demo dataset surfaced this immediately, losing a holder count and
silently switching the supply denominator between runs.

This is not the package deciding which source is right. Where two sources report
the same field differently, `reconcile` reports the disagreement; this rule only
ensures a metric has something to divide by, and it is mechanical rather than a
judgement about provider quality.

---

## 2026-07-29 -- Live `report` refuses rather than printing a table of nulls

**Decided:** `rwa-liquidity report` without `--demo` explains that live mode is
not wired up and exits non-zero.

**Alternatives:** run it anyway and print whatever the keyless sources can
supply.

**Why:** Every metric needs transfer-level data, which only the Dune adapter
supplies, and that adapter has never run against its real API. A table where
every column reads `n/a` looks like a broken install rather than an honest
statement about what is and is not finished. Saying so in a sentence is more
useful than demonstrating it in a grid.

---

## 2026-07-29 -- The normalized model is three frames, not one

**Decided:** `AssetSnapshot`, `TransferEvent`, and `HolderBalance`, sharing an
envelope of `asset_uid`, `source`, and `retrieved_at`.

**Alternatives:** one flat table with a `record_type` discriminator.

**Why:** The sources supply three different shapes of fact: what an asset was
worth at a moment, what moved between two addresses, and who held what. A single
table holding all three would be mostly null, and no column check could say
anything useful about any particular row because the meaning of each column would
depend on the discriminator. Three frames means each schema's checks are total.

The shared envelope is what makes reconciliation and provenance possible: any row
in any frame can name the source that produced it and the moment it was fetched.

---

## 2026-07-29 -- Assets are identified by `chain:address`

**Decided:** the canonical key is a lowercased chain name and a canonicalized
contract address, joined by a colon. `AssetRef` enforces it.

**Alternatives:** rwa.xyz asset IDs as the primary key; a package-assigned
surrogate key with a mapping table.

**Why:** A contract address is the only identifier every on-chain source agrees
on and that no provider can redefine underneath us. Using one provider's IDs
would make that provider a dependency of the data model itself, which is exactly
the coupling this package exists to remove.

**The non-obvious part:** address case is normalized *conditionally*. EVM
addresses are lowercased, because mixed case there is only ever an EIP-55
checksum and not part of the identity. Anything that does not match the EVM shape
keeps its case, because Solana and Stellar addresses are base58/base32 and *are*
case-sensitive -- lowercasing one produces a different, invalid address. The
format is detected from the address itself rather than from a hardcoded list of
chains, which would rot as networks are added.

**Still owed:** DeFiLlama identifies things by protocol slug and does not always
expose a contract address. A hand-maintained mapping file from slug to
`AssetRef` is the plan, and it lands with the DeFiLlama adapter in Phase 3.

---

## 2026-07-29 -- Metric definition ambiguities, resolved

The specification's metric definitions each had a point where two readings were
possible. Resolved as follows; all of these are documented in full in
`docs/methodology.md` when Phase 8 lands.

| Question | Decision | Why |
|---|---|---|
| Turnover denomination: token units or USD? | `native` (volume / supply) is the default; `usd` is available as an explicit variant | The USD reading needs a price for every transfer, which no source supplies, so it would be computed at an end-of-period price -- an assumption baked into a headline number. The native reading needs no price series and is exactly reproducible. |
| Is an "active" address the sender, the receiver, or either? | Either | A holder who received tokens participated in the market. Counting senders only would treat every buyer as dormant. |
| Does the volume mode filter also apply to dormancy and active-holder ratio? | Yes | Under the package's own thesis, an address that received a mint and never traded *is* dormant. Applying the filter only to volume metrics would let the same dataset report an asset as both fully active and untraded. |
| Concentration metrics: exclude issuer, treasury, and bridge addresses? | Include by default; exclude only via explicit per-asset configuration, always recorded in provenance | Excluding by default means a hidden editorial choice inside a published number. Including by default is wrong in a way the reader can see and correct. |
| Truncated holder lists bias HHI downward. Warn or refuse? | Warn, and record observed-vs-reported holder coverage in the provenance record | Refusing would make the metric unusable against any paginated API, which is all of them. The bias is real but it is one-directional and disclosable. |
| How are mints and burns identified? | Zero-address and known burn-address heuristic, plus an optional per-asset issuer address list, with `unclassified` as a third label | Many RWA issuers mint from a treasury address rather than the zero address, so the heuristic alone would misread issuance as trading. `unclassified` exists so an ambiguous transfer is never silently counted as secondary. |

`TransferKind.UNCLASSIFIED` is counted only under `VolumeMode.ALL`. Assigning it
to the secondary bucket would overstate liquidity, which is the error this
package exists to prevent; assigning it to primary would understate it.

---

## 2026-07-29 -- Timezone-naive timestamps are rejected, not assumed UTC

**Decided:** `schema.validate` pre-checks that every timestamp column arrives
timezone-aware, and raises if not.

**Alternatives:** let pandera coerce, which is the default behaviour.

**Why:** Pandera's polars backend relabels a naive datetime column as UTC without
any complaint. Every metric in this package is defined over an observation
window, so a source reporting local time would produce windows wrong by its UTC
offset, with no symptom anywhere -- the numbers would simply be slightly wrong.
An aware timestamp in a non-UTC zone is unambiguous and *is* converted; only the
unlabelled case is an error.

The same pre-check pass also catches missing columns, which pandera surfaces as a
raw `polars.exceptions.ColumnNotFoundError` from inside its coercion pass, naming
neither the schema nor the adapter at fault.

---

## 2026-07-29 -- Cache entries carry their provenance inside the parquet file

**Decided:** retrieval timestamp, source, dataset, query parameters, and a format
version are written to the parquet file's key-value metadata. No sidecar files.

**Alternatives:** a sidecar JSON per entry; a manifest file; a SQLite index.

**Why:** Each entry stays a single self-describing artifact. It cannot be
separated from its provenance by a stray copy, it can be committed as a test
fixture as-is, and `pyarrow` can read the whole story out of it without this
package installed. A manifest would have been faster to scan and is the right
answer at a scale this package will not reach.

Writes go to a temporary file in the destination directory and are renamed into
place, because a rename within a directory is atomic: an interrupted write leaves
the previous entry intact rather than a truncated file that fails to parse on the
next run. An unreadable entry raises rather than being reported as a miss --
treating it as a miss would silently overwrite it, which is data loss disguised
as a cache refresh.

---

## 2026-07-29 -- The demo dataset will be synthetic and labelled as such

**Decided:** `data/sample/` ships a constructed dataset, marked as synthetic in
the README, in `docs/methodology.md`, and in the CLI's own output.

**Alternatives:** wait for Phase 5 and ship a real Dune snapshot.

**Why:** DeFiLlama, the only keyless source, publishes no transfer-level or
holder-level data, so no real dataset can demonstrate the metrics until the paid
adapters land. Deferring demo mode to Phase 5 would remove the property that
makes the repository credible to someone browsing it: that it produces real
output on a clean clone in two commands. Synthetic data is honest as long as it
is never presented as observed, which is why it is labelled in three places
rather than one.

---

## 2026-07-29 -- polars as the primary dataframe library

**Decided:** polars everywhere; pandas only inside `rwa_liquidity.export`, behind
an optional `pandas` extra.

**Alternatives:** pandas throughout; polars with pandas as a hard dependency.

**Why:** Transfer-level data from Dune is the only volume that matters -- asset
metadata and holder snapshots are small enough that the choice is irrelevant to
them. Group-by aggregation over millions of transfer events is exactly where
polars is strongest, and its expression API makes the primary/secondary
partition read as a declarative filter rather than a chain of boolean masks.

Keeping pandas as an *extra* rather than a dependency is an architectural
guardrail, not thrift: if pandas cannot be imported outside `export`, the
boundary cannot be crossed by accident during a late-night refactor.

---

## 2026-07-29 -- pandera for schema validation, on its polars backend

**Decided:** `pandera[polars]` validates at every ingestion boundary.

**Alternatives:** pydantic models over row dicts; hand-written polars assertions.

**Why:** Validation belongs on the frame, not on the row. pydantic is excellent
for the config and envelope layer but validating a million-row frame by
constructing a million models is the wrong shape of tool. pandera expresses
column types, nullability, ranges, and cross-column checks in one declarative
schema that doubles as documentation of the data model.

**Known risk, now partly realised:** pandera's polars backend is younger than its
pandas backend. Two concrete costs have already been paid: the timezone and
missing-column behaviour documented above, and a `DeprecationWarning` that
pandera 0.32.1 triggers inside polars 1.42.1+ when building its failure-case
table. The warning is suppressed by a narrowly-scoped filter in
`pyproject.toml`, with a note to remove it once pandera ships a release built
against current polars.

If the backend becomes untenable, the fallback is pydantic for the config and
envelope layer plus hand-written polars assertions at the boundaries -- **not** a
retreat to pandas. mypy's `follow_untyped_imports` is scoped to `pandera.*` for
the same reason: the relaxation is confined to one library rather than weakening
`--strict` across the package.

---

## 2026-07-29 -- Development targets Python 3.11, the floor of the supported range

**Decided:** `.python-version` pins 3.11; CI tests 3.11 and 3.13.

**Alternatives:** develop on the newest interpreter and let CI catch
incompatibilities.

**Why:** `requires-python = ">=3.11"` is a promise. Developing on 3.13 makes it
easy to write syntax or use stdlib APIs that 3.11 does not have and only find
out at CI time. Developing on the floor makes the promise self-enforcing. CI
still runs the ceiling so that deprecations surface early.

This has already paid for itself once: a PEP 695 generic in `schema/validation.py`
failed immediately on 3.11 instead of shipping and breaking for anyone on the
version the package claims to support.

---

## 2026-07-29 -- uv and hatchling, src layout

**Decided:** `uv` for dependency management, `hatchling` as the build backend,
`src/` layout, no `setup.py` and no `requirements.txt`.

**Alternatives:** poetry; setuptools; flat layout.

**Why:** A `src/` layout means tests import the *installed* package rather than
the working directory, so a module accidentally missing from the wheel fails in
CI instead of shipping broken. `uv.lock` is committed, and CI runs
`uv sync --locked`, which makes a stranger's clone resolve to the exact
dependency set the tests were verified against.

---

## 2026-07-29 -- `secondary_only` is the default volume mode

**Decided:** every volume-based metric takes a mode of `all`, `secondary_only`,
or `primary_only`, defaulting to `secondary_only`.

**Alternatives:** default to `all`, matching raw on-chain transfer volume.

**Why:** This is the package's central methodological claim. A tokenized fund
that only ever mints and redeems has no secondary market, however large its raw
transfer volume looks. Reporting `all` by default would reproduce exactly the
overstatement the package exists to correct. Defaulting to the conservative
measure means a careless user under-reports liquidity rather than over-reports
it, which is the right direction for an error to run in published work.
