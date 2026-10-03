# Sample dataset

**This data is synthetic. It was constructed, not observed.**

The sample lets the package run without network access or credentials:

```bash
uv run rwa-liquidity report --demo
```

It is labelled as synthetic here, in `build.py`, and in the CLI's output on
every run. The files are CSV so that every value can be read without
installing anything.

## Assets

| Asset | Supply | Reported holders | Purpose |
|---|---|---|---|
| `SYNTH-TBILL` | 500,000,000 | 8 | A fund that only issues and redeems |
| `SYNTH-GOLD` | 1,000,000 | 12 | A token traded between holders |
| `SYNTH-CREDIT` | 100,000 | 40 | A thin token with a partly observed holder list |

### SYNTH-TBILL

Four issuances totalling 280m and two redemptions totalling 50m, with no
transfer between holders.

| | `--mode all` | `--mode secondary_only` |
|---|---|---|
| Turnover | 0.6600 | 0.0000 |
| Dormancy | 3.0% | 100.0% |

Counting issuance and redemption as activity reports two thirds of supply
turning over in a month; excluding them shows no secondary activity and every
holder dormant.

### SYNTH-GOLD

Ten transfers between holders totalling 250,000, alongside 80,000 of issuance
and 10,000 of redemption. Turnover is 0.34 with all transfers and 0.25 with
secondary transfers only.

### SYNTH-CREDIT

Two small transfers on a supply of 100,000, so secondary turnover is 0.008.
One of its four transfers is `unclassified`, so narrow modes report the share
set aside. Its holder list contains 6 addresses against a reported holder
count of 40, so concentration is biased downward and the metrics warn about it.

### Cross-source disagreement

`SYNTH-TBILL` is described by two sources: `sample_registry` reports a supply of
500m and `sample_protocol_feed` reports 560m, a difference of 10.7%. The
reconciliation step reports the difference rather than choosing one, and
`report --demo` prints it under the table.

## Rebuilding

```bash
uv run python data/sample/build.py
```

`build.py` defines the data, and `tests/test_demo.py` checks the properties
described above.
