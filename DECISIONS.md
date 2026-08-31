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

## 2026-08-31 -- a self-review of the two previous fixes found four more real issues, closed three

**Decided:** reviewing the 2026-08-27/28 fixes below under `/code-review`
turned up eight candidate findings. Three were fixed here; the rest were
judged, not ignored -- each has a stated reason for the call.

**Fixed:**

1. `ParquetCache.put()` returned `CacheEntry(frame=frame, ...)` built from the
   caller's own argument even on the branch where `_replace_atomically` lost
   the race and a *different* process's write is what is actually on disk --
   contradicting the method's own "Returns: the entry as written" contract.
   `_replace_atomically` now returns whether its own write is the one that
   landed; `put()` reads the entry back from disk (`self._read`) when it
   is not. Regression test added and confirmed to fail against the prior code
   (`test_losing_a_write_race_returns_the_winners_entry_not_the_losers`).
2. `_replace_atomically` caught only `PermissionError`. Windows sharing
   violations (`WinError 32`) do not always arrive wrapped as
   `PermissionError` -- some antivirus/indexer interference surfaces them as a
   plain `OSError` -- so a real, retryable lock could have propagated straight
   through the retry loop and reproduced the original crash for a narrower
   class of contention than intended. Broadened to catch `OSError` and check
   `winerror` against the two known-transient codes (5, 32); anything else
   still raises immediately.
3. `_collect_history`'s `merge()` closure in `cli.py` reimplemented
   `pipeline.py`'s existing `_empty()`/`_concat()` helpers line for line.
   Replaced with a direct import of `pipeline._concat`. `_collect_live`
   already goes through `pipeline.collect()`, which uses the same helpers, so
   this also removes a place the two callers' empty-frame handling could have
   quietly drifted apart.

**Judged real but left as documented, deliberate behavior:**

4. `_collect_history` wraps `supply_snapshots`, `holder_snapshots`, and
   `fetch_transfers` in one `try/except` per asset, so a `fetch_transfers`
   failure after the other two succeed discards their already-fetched frames
   and marks the asset fully unmeasured. Splitting this into one `try/except`
   per call was considered and rejected: it would let an asset keep a
   transfer-less frame that reads as "measured, zero activity" to every
   downstream metric -- exactly the empty-frame-means-inactive conflation
   `pipeline.collect()`'s own docstring warns against, and the failure mode
   this package's `secondary_only` default and undefined-rather-than-zero
   metrics exist to avoid. The current behavior wastes a fetch on partial
   failure; the alternative risks manufacturing a liquidity finding from an
   outage. Kept the safer direction and added a comment explaining why the
   grouping is deliberate, not an oversight.
5. A TOCTOU window remains between `_replace_atomically`'s final failed
   `replace()` and its `path.exists()` check: a concurrent `ParquetCache.
   clear()` in that gap could make a genuine lost race look like a hard
   failure. Not fixed, for the same reason a lock file was rejected in the
   2026-08-28 entry below -- closing it fully needs OS-level locking, which is
   more machinery than the actual cost (one spurious exception, on a
   `clear()`-during-a-live-scan sequence nothing in this codebase does) is
   worth addressing again for.

Also simplified while in the area: `_replace_atomically`'s retry backoff was
linear (`0.05s * (attempt + 1)`) with no stated reason for the growth, against
a docstring that describes the contention as uniform, millisecond-scale.
Flattened to a constant delay, which the same rationale already justified.

**A ninth issue, found by the same review round but in a different function
(`build_report`), is recorded separately** -- see 2026-08-27's
`known_addresses.toml` entry's sibling fix in `metrics/report.py`, committed
as `2b304a6`: it named zero assets rather than every asset during a total
outage, the opposite of what the `merge()` fix above was written to achieve.

---

## 2026-08-28 -- losing a cache write race is not an error, because entries are content-addressed

**Decided:** `ParquetCache.put` retries a refused rename a few times and then,
if the destination file exists, accepts that another process won and discards
its own temporary file. A refusal with *no* file at the destination is still
raised.

**Alternatives:** retry indefinitely; take a lock file around the write;
swallow `PermissionError` unconditionally; leave it and document that the CLI
is single-instance.

**Why:** the old code was written against POSIX semantics, and its comment said
so outright -- "whichever renames last wins, and both are complete." That is
true on POSIX, where a rename can replace a file another process has open. On
Windows it is false: `os.replace` raises `PermissionError` (`WinError 5`) while
any other handle to the destination is open, which a concurrent reader or
writer of the same entry routinely holds.

This was not found by reading the code. Two `rwa-liquidity` commands were run
concurrently against the same registry, and one died partway through a scan
with a `PermissionError` traceback pointing at `store.py`. Nothing about the
failure looked cache-shaped from the outside -- it read as a crash in the
middle of fetching logs.

Accepting the loss is correct rather than merely convenient: cache entries are
addressed by a digest of the request, so whoever won the race wrote the
response to the *same* query. The purpose of the write is that the entry
exists, not that this process authored it.

Swallowing `PermissionError` unconditionally was rejected because it hides the
case that actually matters -- a read-only cache directory, or a scanner holding
the tree -- behind silent success, leaving a cache that never writes anything
and a workflow that re-fetches forever without saying why. The existence check
separates the two, and both branches are covered by tests that were confirmed
to fail against the old implementation.

A lock file was rejected as too much machinery for a problem whose entire cost
is one redundant write.

---

## 2026-08-27 -- PAXG measured through Dune as a control case, aggregated in SQL rather than pulled row by row

**Decided:** PAXG, which `evm_rpc` refuses for exceeding the 250,000-log scan
ceiling, was measured once through Dune Analytics over the published 30-day
window, with the primary/secondary rules re-expressed in SQL. It is **not**
added to the live pipeline; the numbers live in `docs/findings.md` §7a and
`docs/thesis-chapter-draft.md` §4.5a as a control case, labelled as coming from
a different code path.

**Alternatives:** leave PAXG unmeasured and keep the boundary as a pure
limitation; add PAXG to the Dune saved queries so every `report` run includes
it; raise `DEFAULT_MAX_LOGS` past 250,000 and let `evm_rpc` try.

**Why:** the strongest objection to this project's headline findings is that
they might be circular -- if the method only reaches assets thin enough to scan
exhaustively, then "these assets barely trade" could describe the method's
reach rather than the market. That objection cannot be answered by reasoning;
it needs an asset from the other side of the boundary. Measured, PAXG comes back
with 84,962 holders, an HHI of 378, a top-10 share of 34%, and a
primary/secondary overstatement factor of 1.03x -- against a sample where eight
of ten exceed HHI 2,500 and BUIDL's factor is 10.8x. The method discriminates,
and the finding is properly scoped: raw volume overstates secondary liquidity
**for permissioned funds that mint and redeem**, not for tokenized RWAs as a
class.

Two implementation notes worth recording. First, the cost objection that
originally justified excluding PAXG (roughly 453,000 rows for a 90-day window,
past Dune's whole free monthly allowance) applies to *pulling raw rows*.
Aggregating in SQL and returning summary rows instead cost **0.38 credits** for
the transfer split and **103.8** for the balance reconstruction -- about 4% of
the monthly allowance rather than 40%+. The earlier estimate was not wrong, it
was answering a different question. Second, the Dune reconstruction was held to
the same invariant as everything else: balances summed to 441,940.72 against
the contract's own `totalSupply()` of 441,941.91, a 0.00027% discrepancy. A
figure from a paid source still has to reconcile.

Raising `DEFAULT_MAX_LOGS` was rejected for the reason it was set: the ceiling
is not arbitrary, it is roughly where a free endpoint stops serving sustained
scans, and PAXG's log count grows. Moving the number defers the refusal without
removing it.

---

## 2026-08-27 -- issuer addresses are found by distributor signature, then gated on an explorer label

**Decided:** `issuer_addresses` in `known_addresses.toml` is now populated for
two assets -- CANA (`0xccadea5c…`, Etherscan "Maseer: Deployer") and CGT
(`0x6522b05f…`, Etherscan "CACHE Gold: Old Backed Treasury"). A third and
stronger-by-behaviour candidate for OUSG (`0x3d85c41e…`, 220 sends to 12
distinct recipients) was **rejected** and recorded as rejected.

**Alternatives:** configure every address matching the distributor signature;
keep `issuer_addresses` empty and continue reporting the risk as an
unquantified caveat.

**Why:** the search itself is behavioural -- find addresses that took delivery
of a zero-address mint and then distributed onward to many distinct recipients,
which is what an issuer's treasury looks like on chain. But behaviour alone
cannot distinguish a treasury from an early whale or a market maker, and
configuring an address as an issuer *reclassifies its transfers as primary*,
which lowers reported secondary liquidity. Acting on the signature alone would
make the package understate liquidity on a guess -- the mirror image of the
error it exists to prevent, and worse for being invisible. So the signature
selects candidates and an independent label confirms them; OUSG's candidate had
no label and was left out despite being the most suggestive of the three.

The residual risk is now bounded rather than merely admitted, which was the
point. CANA's issuer touches zero transfers in the published window (11 of 1,885
across the six trend windows); CGT's has been dormant since 2021; OUSG's
unconfirmed candidate touches 3 of that asset's 50 window transfers. Those
bounds are in `docs/findings.md` §8 and the thesis §4.4.

---

## 2026-08-26 -- known_addresses.toml: hand-verified DeFi-contract exclusions and issuer addresses, loaded by the CLI

**Decided:** a new file, `src/rwa_liquidity/sources/known_addresses.py` and its
data file `known_addresses.toml`, records per-asset `excluded_contracts`
(dropped from concentration/dormancy) and `issuer_addresses` (classified as
primary rather than secondary), each entry required to carry a citation in
`notes`. The `report` and `trend` CLI commands load it automatically and pass
the flattened sets into `build_report`/`build_trend`'s existing `exclude`
parameter and `EvmRpcSource`'s existing `issuer_addresses` parameter. The
library functions themselves keep defaulting to neither -- the CLI's use of
the file is a convenience layered on top, not a change to what the functions
do when called directly.

**Alternatives:** leave `exclude` and `issuer_addresses` as advanced,
undiscovered constructor arguments a user must know to pass; hard-code the
known contract addresses directly into the registry or into `evm_rpc.py`.

**Why:** both mechanisms already existed -- `classify_transfers`'s
`issuer_addresses` rule and `build_report`'s `exclude` parameter -- and both
were exercised only by tests. In production the CLI always constructed
`EvmRpcSource()` with no arguments and always called `build_report()` with
`exclude` unset, so every real run measured concentration and dormancy with
zero contracts excluded and classified every transfer as if issuance only
ever happened through the zero address. Checking the top holders of the
registry's four most active assets against Etherscan's own contract labels
(2026-08-26) found real cases: OUSG's largest holder (~25% of supply) is
`Flux Finance: fOUSG Token`, a lending vault; USDM's largest holder is
Mountain Protocol's own `wUSDM` wrapper; CANA's top holders include a
CANA-specific Uniswap V2 pool and Uniswap V4's global pool-manager contract.
None of that was reachable by the package's existing mechanisms without
someone doing the manual lookup and wiring it in -- this closes that gap for
the three assets checked. It does not close it for the rest of the registry,
and it found no `issuer_addresses` yet for any asset -- see the file's own
`notes` fields for what each entry does and does not establish, and
`docs/thesis-chapter-draft.md` §4.4 for a related correction: an earlier draft
overclaimed that one historical zero-address mint rules out treasury-routed
issuance for the rest of an asset's history, which does not follow and has
been rewritten.

A file separate from `registry.py` was chosen over hard-coding because the
two serve different questions on different schedules: the DeFiLlama registry
states what an asset *is*, required for every entry before the asset can be
measured at all; this file states what is *known* about an asset's holder set
and issuance, which is optional, grows only as assets are checked by hand, and
should be reviewable (and disputable) as a record of citations rather than as
inline constants.

---

## 2026-08-25 -- CLI help is tested by introspection, not by scraping rich's output

**Decided:** `test_live_mode_is_offered_and_needs_no_key` and
`test_trend_and_issuance_are_documented_in_the_help` check typer's own command
registration (`typer.main.get_command(app).commands[...].params`) instead of
searching the ANSI text of a rendered `--help` panel for a substring.

**Alternatives:** force a specific console width for the test; strip ANSI
codes and normalise whitespace before searching; leave it, since it passed
in every local run.

**Why:** the first real CI run on this repo -- three jobs, two OSes -- failed
all three on the same assertion: `'--demo' in output` was `False` against a
rich-drawn options panel. It had never failed locally, including in a fresh
clone built to match CI exactly. Sweeping the console width from 40 to 200
columns, before and after import, reproduced nothing; the option name never
wrapped at any width tried. The one confirmed difference: CI resolved
`cpython-3.11.16`, and every local environment available here was pinned to
`3.11.15` -- uv's local Python index had no Windows build of `.16` to install
and verify against directly. A same-minor patch bump changing how a
rich-rendered panel lays out is exactly the kind of thing a Unicode Character
Database update between patch releases could cause, though this was not
confirmed by running `.16` locally -- it could not be installed to check.

The fix does not depend on settling which of the two it was. Scraping
rendered terminal text for a literal flag string was always hostage to
whatever rich decides about wrapping, and that decision is sensitive to
console width, OS, and now demonstrably to interpreter patch version -- three
axes a test has no business caring about. Reading the option straight off the
command definition tests the actual invariant (the flag exists and carries
the right help text) with no rendering step in between, and did not merely
happen to dodge this specific failure: whatever caused it, there is no
render path left for it to hide in.

**Decided:** stop retrying BUIDL against the default endpoint for now.
`docs/findings.md` says plainly that BUIDL's figures are the original
2026-07-30 measurement, not re-confirmed after the windowing rewrite, rather
than implying a fresh confirmation that did not happen. `DEFAULT_RPC_URL`
stays the free, keyless endpoint; it was not swapped for a paid one.

**Alternatives considered and rejected:**

- **Point `EVM_RPC_URL` at a paid provider for this one check.** Rejected. The
  package's central claim is that its headline numbers are reproducible by a
  stranger with no credentials; quietly stepping outside that for the one
  figure most likely to be quoted would undermine the thing being verified in
  the act of verifying it.
- **Keep retrying.** Tested, not just considered: a script (kept out of the
  repo, it served one validation run, not a code path) called `fetch_holders`
  in a loop, 40 attempts, 90 seconds of real idle time between each, over 85
  minutes. Every attempt failed identically -- `-32603 service temporarily
  unavailable`, ~40 seconds in. Checked afterwards rather than assumed: the
  cache holds zero new BUIDL log-query entries from that 85-minute window.
  Discovery and deployment detection succeed every time (cached from a
  prior run), then not one of the 40 attempts got past its first live
  `eth_getLogs` call against BUIDL's own address -- not partial progress
  each time, none. That rules out what the 2026-08-14 entry's error message
  assumes: that a pause clears it. For BUIDL specifically, right now, it does
  not. Further identical attempts would only add load to a service already
  struggling, for no evidence they would behave differently.

**Why leaving it open is the right call rather than a gap to hide:** the
scanning method itself was not left unverified. Nine of the ten other
measured assets went through the identical code path this session and
reconstructed correctly -- four of them (ZTLN, RCOIN, CGT, ATT) reproduced
every published figure exactly, because zero activity in either window makes
that the only correct answer; USDM's rebasing guard fired again, correctly,
on a fresh scan; FDIT's implausible-transfer guard fired again, correctly.
None of that logic is BUIDL-specific -- BUIDL differs only in needing roughly
15x the requests (641 ten-thousand-block windows against a token deployed
2024-03) of the next largest asset in the registry, which is exactly the
axis the endpoint is throttling on. There is no path by which the same code,
proven correct nine times, is silently wrong only for the one asset that
could not finish a scan. The finding that needs re-confirming is a number,
not a method.

---

## 2026-08-15 -- `tzdata` is a base dependency, not an accident of `pandas`

**Decided:** `tzdata; sys_platform == "win32" or sys_platform == "emscripten"` is a
direct dependency in `pyproject.toml`, not left to arrive transitively through
the optional `pandas` extra.

**Alternatives:** leave it as-is; document "run `uv sync --all-extras`" as a
requirement even for users who never touch pandas.

**Why:** every timestamp in this package is timezone-aware UTC, and polars
resolves `"UTC"` through Python's `zoneinfo` when building a row or dict from a
`Datetime` column. Windows has no system IANA timezone database for `zoneinfo`
to fall back on, so without the `tzdata` package this panics inside polars with
`ZoneInfoNotFoundError` -- and it panics on `report --demo`, the first command
in the README's two-command quickstart. A plain `uv sync` on Windows failed the
package's own headline promise.

This was invisible for the entire build. `pandas` is an optional extra and
happens to depend on `tzdata` too, so any environment that ever ran
`uv sync --all-extras` -- every dev environment, by the README's own
instructions -- got it as a side effect and never saw the gap. CI never saw it
either: both jobs run on `ubuntu-latest`, which has a native tzdata database and
needs the package for nothing, and always installs with `--all-extras` regardless.
Two independent reasons for the gap, and neither is a Windows-CI job away from
mattering to a plain `uv sync` on Windows, which is exactly what surfaced it: an
environment recreated today happened to run a bare `uv sync`.

Confirmed by rebuilding the venv from scratch with a plain `uv sync` (no extras)
and running `report --demo`: it panicked before the fix and completed after,
with `tzdata` now installed regardless of which extras are requested.

---

## 2026-08-14 -- An overloaded node reports a fault, not a verdict

**Decided:** JSON-RPC error `-32603` raises `SourceTransportError`. Batching was
evaluated and rejected. The default endpoint stands, because the alternatives
still do not serve keyless archive log queries.

**Alternatives:** batch 10--20 calls per HTTP request; move to another public
endpoint; treat every JSON-RPC error alike, as before.

**Why:** the endpoint answers `{"code": -32603, "message": "service temporarily
unavailable"}` over HTTP 200 when it is struggling. Read as a refusal of the
range -- which is what every JSON-RPC error looked like -- the scanner splits and
sends two queries where it sent one, to a node already overloaded, and each half
gets the same answer and splits again. The scan drives the overload it is
reacting to. JSON-RPC defines -32603 as a fault inside the server rather than a
complaint about the request, which is the distinction, and it is the third and
last place this same conflation was hiding.

Batching was measured before being written: the endpoint accepts a JSON-RPC
array and answers it correctly, but ten calls in one request took 10.3 seconds
against 1.38 seconds each, so it processes them serially. A quarter off a
two-hour run does not pay for a change to how the cache attributes per-call
failures, which is precisely where this session's mistakes have been living.

Nine public endpoints were re-checked for keyless `eth_getLogs` over a historical
range. None serve it: publicnode and 1rpc require archive access, Cloudflare and
dRPC refuse the query shape, merkle does not implement the method. The finding
that put the current endpoint in this file has not aged.

What is left is that the endpoint answers a log query in about a second and does
so serially, so a first full-registry scan is on the order of two hours. That is
a property of free infrastructure rather than of this code, it is paid once
because every window is cached, and it is now documented rather than discovered
by waiting.

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
