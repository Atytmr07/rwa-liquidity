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
