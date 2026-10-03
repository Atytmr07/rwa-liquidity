"""Build the committed sample dataset.

The dataset is **synthetic**. No keyless source publishes transfer-level or
holder-level data, so no real dataset can demonstrate this package's metrics
until someone supplies a Dune key. Constructing one is the only way a stranger
can clone the repository and see real output in two commands, which is the
property that makes the repository worth looking at.

Synthetic data is honest as long as it is never presented as observed. It is
labelled as constructed here, in `data/sample/README.md`, in the project README,
and in the CLI's own output.

The three assets are shaped to demonstrate three different findings:

`SYNTH-TBILL`
    A fund that only ever mints and redeems. Its raw transfer volume is 66% of
    supply; its secondary volume is zero. This is the case the package exists
    for, and the one a naive implementation reports as highly liquid.

`SYNTH-GOLD`
    A genuinely traded token, so the two readings differ but neither is absurd.

`SYNTH-CREDIT`
    Thin and concentrated, with a holder list truncated to 6 of 40 reported
    holders so that the coverage warning on the concentration metrics fires.

The CSVs are written as CSV rather than parquet on purpose: a reader can open
them on GitHub and check every number without installing anything.

Run with `uv run python data/sample/build.py`.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

HERE: Final = Path(__file__).parent

WINDOW_END: Final = datetime(2026, 7, 1, tzinfo=UTC)
WINDOW_START: Final = WINDOW_END - timedelta(days=30)

TBILL: Final = "ethereum:0x0000000000000000000000000000000000000001"
GOLD: Final = "ethereum:0x0000000000000000000000000000000000000002"
CREDIT: Final = "ethereum:0x0000000000000000000000000000000000000003"

ZERO: Final = "0x0000000000000000000000000000000000000000"


#: Holder addresses start well above the contract addresses above, so that a
#: reader skimming the CSVs never mistakes a holder for an asset.
_HOLDER_BASE: Final = 0xA0000


def address(n: int) -> str:
    """Return a distinct, obviously-synthetic holder address."""
    return f"0x{_HOLDER_BASE + n:040x}"


def stamp(day: int, hour: int = 12) -> str:
    """Return an ISO timestamp `day` days into the observation window."""
    return (WINDOW_START + timedelta(days=day, hours=hour)).isoformat()


def write(name: str, rows: list[dict[str, Any]]) -> None:
    """Write one CSV, using the first row's keys as the header."""
    path = HERE / name
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path.relative_to(HERE.parents[1])} ({len(rows)} rows)")


def snapshots() -> list[dict[str, Any]]:
    """Asset snapshots, including one deliberate cross-source disagreement."""
    common = {
        "retrieved_at": WINDOW_END.isoformat(),
        "as_of": WINDOW_END.isoformat(),
        "decimals": 6,
    }
    return [
        {
            "asset_uid": TBILL,
            "source": "sample_registry",
            "symbol": "SYNTH-TBILL",
            "name": "Synthetic Tokenized Treasury Fund",
            "total_supply": 500_000_000.0,
            "market_value_usd": 500_000_000.0,
            "price_usd": 1.0,
            "holder_count": 8,
            **common,
        },
        {
            # A second source for the same asset, disagreeing by 12%. Mirrors
            # the real BUIDL case, where a protocol-level figure covers more
            # than the single contract it is compared against.
            "asset_uid": TBILL,
            "source": "sample_protocol_feed",
            "symbol": "SYNTH-TBILL",
            "name": "Synthetic Tokenized Treasury Fund",
            "total_supply": 560_000_000.0,
            "market_value_usd": 560_000_000.0,
            "price_usd": 1.0,
            "holder_count": "",
            **common,
        },
        {
            "asset_uid": GOLD,
            "source": "sample_registry",
            "symbol": "SYNTH-GOLD",
            "name": "Synthetic Tokenized Gold",
            "total_supply": 1_000_000.0,
            "market_value_usd": 4_000_000_000.0,
            "price_usd": 4000.0,
            "holder_count": 12,
            **common,
        },
        {
            "asset_uid": CREDIT,
            "source": "sample_registry",
            "symbol": "SYNTH-CREDIT",
            "name": "Synthetic Private Credit Note",
            "total_supply": 100_000.0,
            "market_value_usd": 100_000_000.0,
            "price_usd": 1000.0,
            # Deliberately larger than the holder rows below, so the truncation
            # warning on the concentration metrics fires.
            "holder_count": 40,
            **common,
        },
    ]


def transfers() -> list[dict[str, Any]]:
    """Transfer events. Kinds are pre-assigned, as a real adapter would."""
    rows: list[dict[str, Any]] = []
    index = 0

    def add(  # noqa: PLR0913, PLR0917 -- one parameter per column of the row
        asset: str,
        day: int,
        sender: str,
        recipient: str,
        amount: float,
        kind: str,
        price: float,
    ) -> None:
        nonlocal index
        rows.append(
            {
                "asset_uid": asset,
                "source": "sample_chain",
                "retrieved_at": WINDOW_END.isoformat(),
                "block_time": stamp(day),
                "tx_hash": f"0x{index:064x}",
                "log_index": 0,
                "from_address": sender,
                "to_address": recipient,
                "amount": amount,
                "amount_usd": amount * price,
                "kind": kind,
                "block_time_sort": day,
            }
        )
        index += 1

    # SYNTH-TBILL: issuance and redemption only. 280m minted, 50m redeemed,
    # nothing traded between holders. Raw volume 330m against 500m supply.
    for day, amount, holder in [(2, 100e6, 1), (8, 80e6, 2), (15, 60e6, 3), (22, 40e6, 4)]:
        add(TBILL, day, ZERO, address(holder), amount, "mint", 1.0)
    for day, amount, holder in [(11, 30e6, 5), (26, 20e6, 6)]:
        add(TBILL, day, address(holder), ZERO, amount, "burn", 1.0)

    # SYNTH-GOLD: a real secondary market. 250,000 traded between holders.
    add(GOLD, 1, ZERO, address(20), 50_000.0, "mint", 4000.0)
    add(GOLD, 17, ZERO, address(21), 30_000.0, "mint", 4000.0)
    add(GOLD, 24, address(22), ZERO, 10_000.0, "burn", 4000.0)
    trades = [
        (3, 20, 21, 40_000.0),
        (5, 21, 22, 25_000.0),
        (6, 22, 23, 30_000.0),
        (9, 23, 24, 15_000.0),
        (12, 24, 25, 20_000.0),
        (13, 25, 26, 18_000.0),
        (16, 26, 27, 22_000.0),
        (19, 27, 28, 12_000.0),
        (21, 28, 29, 35_000.0),
        (27, 29, 20, 33_000.0),
    ]
    for day, sender, recipient, amount in trades:
        add(GOLD, day, address(sender), address(recipient), amount, "secondary", 4000.0)

    # SYNTH-CREDIT: thin. One issuance, two small trades, and one transfer whose
    # counterparty could not be classified.
    add(CREDIT, 4, ZERO, address(40), 20_000.0, "mint", 1000.0)
    add(CREDIT, 14, address(40), address(41), 500.0, "secondary", 1000.0)
    add(CREDIT, 25, address(41), address(42), 300.0, "secondary", 1000.0)
    add(CREDIT, 28, address(42), address(43), 1_200.0, "unclassified", 1000.0)

    for row in rows:
        del row["block_time_sort"]
    return rows


def holders() -> list[dict[str, Any]]:
    """Holder balances at the end of the window."""
    rows: list[dict[str, Any]] = []

    def add(asset: str, holder: int, balance: float, price: float) -> None:
        rows.append(
            {
                "asset_uid": asset,
                "source": "sample_chain",
                "retrieved_at": WINDOW_END.isoformat(),
                "as_of": WINDOW_END.isoformat(),
                "address": address(holder),
                "balance": balance,
                "balance_usd": balance * price,
            }
        )

    # SYNTH-TBILL: 8 holders summing to 500m, dominated by two institutions.
    for holder, balance in [
        (1, 200e6),
        (2, 130e6),
        (3, 70e6),
        (4, 40e6),
        (5, 30e6),
        (6, 15e6),
        (7, 10e6),
        (8, 5e6),
    ]:
        add(TBILL, holder, balance, 1.0)

    # SYNTH-GOLD: 12 holders summing to 1,000,000, comparatively even.
    gold = [
        (20, 180_000.0),
        (21, 150_000.0),
        (22, 120_000.0),
        (23, 100_000.0),
        (24, 90_000.0),
        (25, 80_000.0),
        (26, 70_000.0),
        (27, 60_000.0),
        (28, 55_000.0),
        (29, 45_000.0),
        (30, 30_000.0),
        (31, 20_000.0),
    ]
    for holder, balance in gold:
        add(GOLD, holder, balance, 4000.0)

    # SYNTH-CREDIT: only 6 of 40 reported holders, so coverage is 15% and the
    # concentration metrics warn that the true value is higher than reported.
    for holder, balance in [
        (40, 55_000.0),
        (41, 20_000.0),
        (42, 10_000.0),
        (43, 6_000.0),
        (44, 4_000.0),
        (45, 3_000.0),
    ]:
        add(CREDIT, holder, balance, 1000.0)

    return rows


def main() -> None:
    """Write all three files."""
    write("asset_snapshots.csv", snapshots())
    write("transfer_events.csv", transfers())
    write("holder_balances.csv", holders())


if __name__ == "__main__":
    main()
