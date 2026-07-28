# Design decisions

Every non-trivial architectural choice, with its alternatives and the reason it
went the way it did. Newest first. The point of this file is to make the design
defensible in conversation months from now.

---

## Open questions

Decisions that are proposed but not yet settled. Each one is answered before the
phase that depends on it.

| # | Question | Blocks |
|---|----------|--------|
| 1 | Is the normalized model **three** frames (`asset_snapshot`, `transfer_event`, `holder_balance`) rather than one flat schema? | Phase 2 |
| 2 | Canonical asset key: `(chain, contract_address)` plus a hand-maintained mapping file for slug-only sources? | Phase 2 |
| 3 | Turnover ratio units: token-denominated (volume / supply) or USD-denominated (volume x price / market value)? | Phase 4 |
| 4 | "Active" address: sender, receiver, or either? | Phase 4 |
| 5 | Does the primary/secondary mode filter also apply to dormancy and active-holder ratio? | Phase 4 |
| 6 | Concentration metrics: include issuer/treasury/bridge addresses by default, or exclude via per-asset config? | Phase 4 |
| 7 | Truncated holder lists bias HHI downward. Warn, or refuse to emit the metric? | Phase 4 |
| 8 | Mint/burn classification: zero-address heuristic plus per-asset issuer address list, with a third `unclassified` label? | Phase 4 |
| 9 | Demo dataset: synthetic-but-realistic and loudly labelled, or a real Dune snapshot (which delays demo mode to Phase 5)? | Phase 7 |

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

**Known risk:** pandera's polars backend is younger than its pandas backend.
Some built-in checks and the statistical-hypothesis features are pandas-only.
If we hit a wall, the fallback is pydantic for the config/envelope layer plus
hand-written polars assertions at the boundaries -- **not** a retreat to pandas.
mypy's `follow_untyped_imports` is scoped to `pandera.*` for the same reason;
the relaxation is confined to one library rather than weakening `--strict`.

---

## 2026-07-29 -- Development targets Python 3.11, the floor of the supported range

**Decided:** `.python-version` pins 3.11; CI tests 3.11 and 3.13.

**Alternatives:** develop on the newest interpreter and let CI catch
incompatibilities.

**Why:** `requires-python = ">=3.11"` is a promise. Developing on 3.13 makes it
easy to write syntax or use stdlib APIs that 3.11 does not have and only find
out at CI time. Developing on the floor makes the promise self-enforcing. CI
still runs the ceiling so that deprecations surface early.

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
