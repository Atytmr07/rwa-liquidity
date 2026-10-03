-- PAXG supply, holder concentration, active addresses and dormancy at a window end.
--
-- Dune query 8517510. Window [2026-06-30, 2026-07-30) UTC, bounded by block
-- time. Balances are replayed from the full Transfer history up to the window
-- end; Dune cannot read totalSupply(), so the reconstructed supply is compared
-- with it separately.

WITH bounds AS (
    SELECT TIMESTAMP '2026-06-30 00:00:00' AS t0,
           TIMESTAMP '2026-07-30 00:00:00' AS t1
),
xfer AS (
    SELECT t."from" AS sender, t."to" AS recipient,
           CAST(t.value AS DECIMAL(38,0)) AS raw, t.evt_block_time AS ts
    FROM erc20_ethereum.evt_Transfer t, bounds b
    WHERE t.contract_address = 0x45804880de22913dafe09f4980848ece6ecbaf78
      AND t.evt_block_time < b.t1
),
flows AS (
    SELECT recipient AS addr,  raw AS delta FROM xfer
    UNION ALL
    SELECT sender    AS addr, -raw AS delta FROM xfer
),
bal AS (
    SELECT addr, SUM(delta) / 1e18 AS balance
    FROM flows
    WHERE addr NOT IN (
        0x0000000000000000000000000000000000000000,
        0x000000000000000000000000000000000000dEaD
    )
    GROUP BY addr
    HAVING SUM(delta) > 0
),
ranked AS (
    SELECT balance, ROW_NUMBER() OVER (ORDER BY balance DESC) AS rn FROM bal
),
totals AS (
    SELECT SUM(balance) AS supply, COUNT(*) AS holders FROM bal
),
-- Addresses on either side of a *secondary* transfer inside the window.
active AS (
    SELECT DISTINCT addr FROM (
        SELECT sender AS addr FROM xfer, bounds b
        WHERE ts >= b.t0 AND ts < b.t1
          AND sender <> 0x0000000000000000000000000000000000000000
          AND recipient NOT IN (
              0x0000000000000000000000000000000000000000,
              0x000000000000000000000000000000000000dEaD)
        UNION ALL
        SELECT recipient AS addr FROM xfer, bounds b
        WHERE ts >= b.t0 AND ts < b.t1
          AND sender <> 0x0000000000000000000000000000000000000000
          AND recipient NOT IN (
              0x0000000000000000000000000000000000000000,
              0x000000000000000000000000000000000000dEaD)
    ) u
)
SELECT
    (SELECT supply  FROM totals)                                   AS supply,
    (SELECT holders FROM totals)                                   AS holders,
    (SELECT SUM(balance) FROM ranked WHERE rn <= 10)
        / (SELECT supply FROM totals)                              AS top_10_share,
    (SELECT SUM(POWER(balance / (SELECT supply FROM totals), 2)) FROM bal) * 10000 AS hhi,
    (SELECT COUNT(*) FROM active)                                  AS active_addresses,
    (SELECT SUM(b.balance) FROM bal b
      WHERE b.addr NOT IN (SELECT addr FROM active))
        / (SELECT supply FROM totals)                              AS dormancy
