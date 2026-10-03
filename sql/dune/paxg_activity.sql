-- PAXG transfer activity by kind over one window.
--
-- Dune query 8517507. Window [2026-06-30, 2026-07-30) UTC, bounded by block
-- time. Out of the zero address is a mint, into the zero or dead address a
-- burn, and every other transfer secondary. PAXG exceeds the transfer-log
-- ceiling of the on-chain adapter, so it was measured in SQL instead.

WITH bounds AS (
    SELECT TIMESTAMP '2026-06-30 00:00:00' AS t0,
           TIMESTAMP '2026-07-30 00:00:00' AS t1
),
moves AS (
    SELECT
        t."from"  AS sender,
        t."to"    AS recipient,
        t.value / 1e18 AS amount
    FROM erc20_ethereum.evt_Transfer t, bounds b
    WHERE t.contract_address = 0x45804880de22913dafe09f4980848ece6ecbaf78
      AND t.evt_block_time >= b.t0
      AND t.evt_block_time <  b.t1
)
SELECT
    CASE
        WHEN sender = 0x0000000000000000000000000000000000000000 THEN 'mint'
        WHEN recipient IN (
                 0x0000000000000000000000000000000000000000,
                 0x000000000000000000000000000000000000dEaD
             ) THEN 'burn'
        ELSE 'secondary'
    END AS kind,
    COUNT(*)                  AS n_transfers,
    SUM(amount)               AS volume,
    COUNT(DISTINCT sender)    AS distinct_senders,
    COUNT(DISTINCT recipient) AS distinct_recipients
FROM moves
GROUP BY 1
ORDER BY 1
