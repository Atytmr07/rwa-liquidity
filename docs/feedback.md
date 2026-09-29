# Feedback on the code, data and working paper

Hi Atay,

Thanks for building on my paper. I like the idea of classifying each transfer and checking the holder balances against `totalSupply()`, this is exactly the part I could not do in my paper. I am happy to work together on the next version.

I read through the repo (commit `57f39e3`) and the SSRN draft. I put my notes below, split into code, data and paper. Please note I only read the code, I could not run it on my side, so some points may be wrong or already handled somewhere I did not see. Please check them with a real run.

## Code

1. **Holder balances in `report` are from chain head, not window end.** In `evm_rpc.py`, the docstring of `fetch_holders` says the balances are always at the chain head and passing `as_of` will misdate the rows. But `pipeline.collect` passes `as_of=window.end`. So in the cross-section, HHI, top-10 share and dormancy use balances from the scan date but transfers from the window. `trend` already uses `holder_snapshots` at each window end, maybe `report` can do the same.

2. **Reconciliation failure is only a warning.** `_verify_reconstruction` logs the mismatch but does not mark the holder data, so the metrics are still computed. USDM becomes `n/a` only because some share is above 1. STBT has 141 negative balances and 2.7% shortfall but still gets HHI 9,369. I think we need a `reconciled` flag and return `None` for holder metrics when it fails.

3. **After excluding contracts, the denominator is still full supply** (`resolve_total_supply` in `metrics/base.py`). When investors deposit OUSG into the Flux vault, the vault gets bigger and the share of the other holders goes down automatically. I am worried this alone can explain OUSG going from 81.6% to 70.1%. Same with ZTLN, the HHI 1,110.6 is just (1/3)^2, because the other 2/3 is in the Balancer vault. Can we export both versions (full supply and renormalised on non-excluded supply)? Even better if we can look through the vault to the fOUSG holders.

4. **`unmeasured` check.** In `pipeline.collect` an asset is counted as measured if transfers OR holders came back. I think it should need both, or at least say which one is missing.

5. **`_drop_implausible`.** Dropping transfers bigger than supply makes sense (the CACHE Gold case), but the number of dropped transfers per asset should be in the output, not only in the log.

6. **Block numbers.** Can we save the start block, end block and head block for every window in the exported rows? Then anyone can recompute the same number later.

7. **Bridges.** BUIDL, USYC and OUSG are on several chains. Burn-and-mint bridges will look like issuance and lock-and-mint bridges will look like secondary transfers. Maybe we can add known bridge contracts to `known_addresses.toml`.

8. **Type of mints.** If I remember correctly BUIDL pays the yield as new tokens (we need to check this in the BlackRock/Securitize docs). If yes, a lot of the 696 "issuance" transfers are yield payments, not new subscriptions. Maybe add another `kind` for distributions.

## Data and reporting

1. **BUIDL trend.** In `findings.md` 7b, BUIDL has values for the windows ending 08-01 and 08-31, but the last scan was 07-30. The 08-31 value (0.0187) is the same as the old cross-section value. I think we should remove these or scan BUIDL again with a better RPC.

2. **Two runs are mixed.** The paper uses the 10-asset run from 07-30, while the README and findings use the 14-asset run ending 08-28/08-31. Some examples:
   - 8 of 10 vs 11 of 14 assets above HHI 2,500
   - FDIT in 5: 3 holders, turnover 1.08, HHI 9,362. In the 2 table: 2 holders, 0.3539, HHI 9,569
   - PAXG supply 441,941.91 in 7a vs 429,666.38 in 1
   - OUSG window transfers 50 (in `known_addresses.toml` and 8) vs 30 (in 1)
   - window end 08-31 in README vs 08-28 in findings
   - 8 says exclusions cover three assets, 5a lists seven assets

3. **Zero-trade assets.** Paper and README say ZTLN, RCOIN, CGT and ATT. But in the current table CGT has 1 secondary transfer and HLSCOPE has zero.

4. **"1.0x" for assets with no activity** is 0/0, so it should be undefined, not 1.0x.

5. **Token units vs USD.** Turnover denominator and log(Supply) in the regression are in token units. It is ok for $1 T-bill tokens, but not for CGT (gold), CANA (carbon) or HLSCOPE (159.94 units). I have NAV/price data from RWA.xyz, I can send it.

6. **Reproducibility.** `.rwa-cache/` is in `.gitignore` and the Dune SQL for PAXG is not in the repo. So right now nobody can reproduce the numbers exactly. We can put a frozen snapshot on Zenodo.

My suggestion: do one clean rerun of all 16 assets with a paid RPC or indexer, with fixed blocks, and generate all paper tables from that run with a script. I will write the paper in Overleaf, so it would be great if the script can export the tables as `.tex` directly into a `paper/` folder and I just `\input` them. Then the numbers in the paper and the repo will always be the same.

## Paper

1. **Framing.** Since we write it together now, I prefer to present it as an extension of my 2026 paper, not "this paper resolves Mafrur (2026)". We use my panel and hypotheses, and test them again with your transfer classification.

2. **Regression.** Section 3.5 says it uses the same sample as Table 1, but Table 1 has n = 10 (with BUIDL) and I can only reproduce the regression with n = 9 (without BUIDL). Anyway with 6 degrees of freedom it cannot say much. I would like to replace it with a proper panel (supply and holders per window, asset-class and month fixed effects). I can do the econometrics part.

3. **PAXG argument.** Low HHI shows PAXG is widely held, but it does not really show the method can detect liquidity. Better to use turnover and holder counts for this point.

4. **Section 2.1** says mismatches are reported as undefined, but USDM and STBT still have HHI in the tables. This will be fine after code point 2 is fixed.

Best,
Rischan
