"""The Dune adapter and transfer classification.

Payloads follow the shape documented at docs.dune.com. Unlike the DeFiLlama
tests, these were built from documentation rather than from observed responses,
because no key was available. That is recorded here so nobody later mistakes
them for evidence the adapter works against the real API.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx
import polars as pl
import pytest

import rwa_liquidity.config
from rwa_liquidity.cache import ParquetCache
from rwa_liquidity.schema.asset import AssetRef
from rwa_liquidity.schema.types import ZERO_ADDRESS, TransferKind
from rwa_liquidity.sources import Capability, DuneSource, SourceFetchError, classify_transfers

ASSET = AssetRef.parse("ethereum:0x7712c34205737192402172409a8f7ccef8aa2aec")
OTHER = AssetRef.parse("ethereum:0x" + "f" * 40)
TREASURY = "0x" + "7" * 40
ALICE, BOB = "0x" + "a" * 40, "0x" + "b" * 40

START = datetime(2026, 6, 1, tzinfo=UTC)
END = datetime(2026, 7, 1, tzinfo=UTC)
INSIDE = "2026-06-15 12:00:00"
OUTSIDE = "2026-05-15 12:00:00"


def transfer_row(  # noqa: PLR0913 -- a row builder; each field is one column
    *,
    sender: str,
    recipient: str,
    amount: float,
    block_time: str = INSIDE,
    contract: str | None = None,
    log_index: int = 0,
) -> dict[str, object]:
    return {
        "block_time": block_time,
        "tx_hash": f"0x{log_index:04x}",
        "log_index": log_index,
        "contract_address": contract or ASSET.address,
        "from_address": sender,
        "to_address": recipient,
        "amount": amount,
        "amount_usd": amount * 2,
    }


def results_payload(
    rows: list[dict[str, object]], *, next_offset: int | None = None
) -> dict[str, object]:
    payload: dict[str, object] = {
        "query_id": 1234,
        "execution_id": "01HKZJ2683PHF9Q9PHHQ8FW4Q1",
        "state": "QUERY_STATE_COMPLETED",
        "is_execution_finished": True,
        "result": {
            "rows": rows,
            "metadata": {"row_count": len(rows), "total_row_count": len(rows)},
        },
    }
    if next_offset is not None:
        payload["next_offset"] = next_offset
    return payload


def dune(
    cache_root: Path,
    payload: object,
    *,
    issuers: dict[str, list[str]] | None = None,
    seen: list[httpx.Request] | None = None,
) -> DuneSource:
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=payload)

    return DuneSource(
        cache=ParquetCache(cache_root),
        client=httpx.Client(transport=httpx.MockTransport(handle)),
        transfers_query_id="1234",
        holders_query_id="5678",
        issuer_addresses=issuers,
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify(rows: list[tuple[str, str]], issuers: list[str] | None = None) -> list[str]:
    frame = pl.DataFrame({"from_address": [r[0] for r in rows], "to_address": [r[1] for r in rows]})
    return classify_transfers(frame, issuer_addresses=issuers or []).get_column("kind").to_list()


def test_zero_address_transfers_are_primary() -> None:
    assert classify([(ZERO_ADDRESS, ALICE)]) == [TransferKind.MINT.value]
    assert classify([(ALICE, ZERO_ADDRESS)]) == [TransferKind.BURN.value]


def test_holder_to_holder_is_secondary() -> None:
    assert classify([(ALICE, BOB)]) == [TransferKind.SECONDARY.value]


def test_treasury_distribution_is_primary_not_secondary() -> None:
    # The failure this rule exists for: an issuer that mints one tranche and
    # then distributes from a treasury makes every subscription look like
    # ordinary trading, inflating secondary volume by the size of the issuance.
    assert classify([(TREASURY, ALICE)]) == [TransferKind.SECONDARY.value]
    assert classify([(TREASURY, ALICE)], issuers=[TREASURY]) == [TransferKind.MINT.value]
    assert classify([(ALICE, TREASURY)], issuers=[TREASURY]) == [TransferKind.BURN.value]


def test_issuer_matching_is_case_insensitive() -> None:
    assert classify([(TREASURY.upper(), ALICE)], issuers=[TREASURY]) == [TransferKind.MINT.value]


def test_zero_to_burn_is_unclassified_rather_than_guessed() -> None:
    # Not a coherent event. Refusing to guess is the reason the fourth label
    # exists at all.
    assert classify([(ZERO_ADDRESS, ZERO_ADDRESS)]) == [TransferKind.UNCLASSIFIED.value]


def test_all_secondary_with_no_issuer_configured_is_flagged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The package's largest exposure: treasury issuance silently counted as
    # trading. It cannot be detected with certainty, so it is reported.
    with caplog.at_level(logging.WARNING):
        classify([(ALICE, BOB), (BOB, ALICE)])
    assert "liquidity is overstated" in caplog.text


def test_no_warning_when_issuance_is_visible(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        classify([(ZERO_ADDRESS, ALICE), (ALICE, BOB)])
    assert "overstated" not in caplog.text


# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------


def test_transfers_become_a_validated_frame(cache_root: Path) -> None:
    rows = [
        transfer_row(sender=ZERO_ADDRESS, recipient=ALICE, amount=400.0, log_index=0),
        transfer_row(sender=ALICE, recipient=BOB, amount=100.0, log_index=1),
    ]
    frame = dune(cache_root, results_payload(rows)).fetch_transfers(ASSET, start=START, end=END)

    assert frame.height == 2
    assert set(frame["kind"].to_list()) == {TransferKind.MINT.value, TransferKind.SECONDARY.value}
    assert frame["asset_uid"].unique().to_list() == [ASSET.uid]
    # Dune returns naive timestamps documented as UTC; the zone must be attached
    # explicitly or the schema layer refuses the frame.
    assert frame.schema["block_time"] == pl.Datetime("us", "UTC")


def test_rows_for_other_contracts_are_dropped(cache_root: Path) -> None:
    # One saved query can serve many assets, so scoping happens here.
    rows = [
        transfer_row(sender=ALICE, recipient=BOB, amount=100.0, log_index=0),
        transfer_row(
            sender=ALICE, recipient=BOB, amount=999.0, log_index=1, contract=OTHER.address
        ),
    ]
    frame = dune(cache_root, results_payload(rows)).fetch_transfers(ASSET, start=START, end=END)
    assert frame.height == 1
    assert frame["amount"].item() == 100.0


def test_transfers_outside_the_window_are_dropped(cache_root: Path) -> None:
    rows = [
        transfer_row(sender=ALICE, recipient=BOB, amount=100.0, log_index=0),
        transfer_row(sender=ALICE, recipient=BOB, amount=999.0, log_index=1, block_time=OUTSIDE),
    ]
    frame = dune(cache_root, results_payload(rows)).fetch_transfers(ASSET, start=START, end=END)
    assert frame["amount"].to_list() == [100.0]


def test_issuer_addresses_are_applied_per_asset(cache_root: Path) -> None:
    rows = [transfer_row(sender=TREASURY, recipient=ALICE, amount=500.0)]
    frame = dune(
        cache_root, results_payload(rows), issuers={ASSET.uid: [TREASURY]}
    ).fetch_transfers(ASSET, start=START, end=END)
    assert frame["kind"].item() == TransferKind.MINT.value


def test_empty_result_is_an_empty_frame_not_an_error(cache_root: Path) -> None:
    # "This asset did not trade" is a finding, and the frame has to carry the
    # full schema so it can be concatenated with populated ones.
    frame = dune(cache_root, results_payload([])).fetch_transfers(ASSET, start=START, end=END)
    assert frame.is_empty()
    assert "kind" in frame.columns


def test_missing_required_column_names_it(cache_root: Path) -> None:
    # A silently wrong query would produce an empty frame, which reads
    # downstream as a real finding of no trading.
    broken = [{"block_time": INSIDE, "tx_hash": "0x1", "amount": 1.0}]
    with pytest.raises(SourceFetchError, match="log_index"):
        dune(cache_root, results_payload(broken)).fetch_transfers(ASSET, start=START, end=END)


def test_unfinished_query_is_an_error(cache_root: Path) -> None:
    payload = {"state": "QUERY_STATE_EXECUTING", "result": {"rows": []}}
    with pytest.raises(SourceFetchError, match="QUERY_STATE_EXECUTING"):
        dune(cache_root, payload).fetch_transfers(ASSET, start=START, end=END)


def test_unconfigured_query_id_explains_what_to_set(
    cache_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Passing None only means "use the environment variable instead" (see
    # DuneSource.__init__); it does not force the id unset. Without clearing
    # these, this test passed only because no developer machine happened to
    # have them set -- which stopped being true the day this project's own
    # .env got real Dune credentials in it.
    #
    # Clearing the two variables is not sufficient on its own: config.py loads
    # `.env` at most once per process, guarded by a module-level flag, and
    # `load_dotenv(override=False)` only protects a variable that is already
    # set. If this test is what happens to trigger that one-time load, it
    # freely refills the very variables just cleared, straight from the file.
    # Forcing the flag true first makes load_environment() a no-op regardless
    # of whether anything upstream in this test run has called it yet.
    monkeypatch.setattr(rwa_liquidity.config, "_loaded", True)
    monkeypatch.delenv("DUNE_TRANSFERS_QUERY_ID", raising=False)
    monkeypatch.delenv("DUNE_HOLDERS_QUERY_ID", raising=False)
    source = DuneSource(
        cache=ParquetCache(cache_root),
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
        transfers_query_id=None,
        holders_query_id=None,
    )
    with pytest.raises(SourceFetchError, match="DUNE_TRANSFERS_QUERY_ID"):
        source.fetch_transfers(ASSET, start=START, end=END)


def test_missing_amount_usd_column_is_tolerated(cache_root: Path) -> None:
    # USD metrics then report themselves undefined rather than guessing a price.
    row = transfer_row(sender=ALICE, recipient=BOB, amount=100.0)
    del row["amount_usd"]
    frame = dune(cache_root, results_payload([row])).fetch_transfers(ASSET, start=START, end=END)
    assert frame["amount_usd"].null_count() == 1


# ---------------------------------------------------------------------------
# Holders
# ---------------------------------------------------------------------------


def holder_rows() -> list[dict[str, object]]:
    return [
        {"contract_address": ASSET.address, "address": ALICE, "balance": 700.0},
        {"contract_address": ASSET.address, "address": BOB, "balance": 300.0},
        {"contract_address": OTHER.address, "address": ALICE, "balance": 999.0},
    ]


def test_holders_become_a_validated_frame(cache_root: Path) -> None:
    frame = dune(cache_root, results_payload(holder_rows())).fetch_holders(ASSET, as_of=END)
    assert frame.height == 2
    assert frame["balance"].sum() == 1000.0
    assert frame["as_of"].unique().to_list() == [END]


def test_holders_missing_required_column_names_it(cache_root: Path) -> None:
    rows = [{"address": ALICE, "balance": 1.0}]
    with pytest.raises(SourceFetchError, match="contract_address"):
        dune(cache_root, results_payload(rows)).fetch_holders(ASSET)


def test_pagination_follows_next_offset(cache_root: Path) -> None:
    calls: list[httpx.Request] = []
    page_one = results_payload(
        [transfer_row(sender=ALICE, recipient=BOB, amount=1.0, log_index=0)], next_offset=1
    )

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "offset=0" in str(request.url):
            return httpx.Response(200, json=page_one)
        return httpx.Response(
            200,
            json=results_payload(
                [transfer_row(sender=BOB, recipient=ALICE, amount=2.0, log_index=1)]
            ),
        )

    source = DuneSource(
        cache=ParquetCache(cache_root),
        client=httpx.Client(transport=httpx.MockTransport(handle)),
        transfers_query_id="1234",
        holders_query_id="5678",
    )
    frame = source.fetch_transfers(ASSET, start=START, end=END)

    assert len(calls) == 2
    assert sorted(frame["amount"].to_list()) == [1.0, 2.0]


def test_dune_declares_transfer_and_holder_capabilities(cache_root: Path) -> None:
    source = dune(cache_root, results_payload([]))
    assert source.supports(Capability.TRANSFER_EVENT)
    assert source.supports(Capability.HOLDER_BALANCE)
    assert not source.supports(Capability.ASSET_SNAPSHOT)


@pytest.mark.parametrize(
    "block_time",
    [
        "2026-06-15 12:00:00",
        "2026-06-15 12:00:00.000",
        "2026-06-15T12:00:00Z",
        "2026-06-15 12:00:00.000 UTC",
    ],
)
def test_timestamp_formats_dune_has_used(cache_root: Path, block_time: str) -> None:
    # Dune's JSON timestamp format has varied. All of these must land on the
    # same instant, and all must come back timezone-aware.
    rows = [transfer_row(sender=ALICE, recipient=BOB, amount=1.0, block_time=block_time)]
    frame = dune(cache_root, results_payload(rows)).fetch_transfers(ASSET, start=START, end=END)

    assert frame.height == 1
    assert frame["block_time"].item() == datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def test_unparseable_timestamp_is_an_error_not_a_dropped_row(cache_root: Path) -> None:
    # Nulling it would remove the transfer from its window and quietly lower
    # every volume figure.
    rows = [transfer_row(sender=ALICE, recipient=BOB, amount=1.0, block_time="last Tuesday")]
    with pytest.raises(SourceFetchError, match="could not be read as a timestamp"):
        dune(cache_root, results_payload(rows)).fetch_transfers(ASSET, start=START, end=END)


def test_retrieved_at_is_the_fetch_time_not_the_window_end(cache_root: Path) -> None:
    # retrieved_at answers "when did we ask", which is not "what period is this".
    rows = [transfer_row(sender=ALICE, recipient=BOB, amount=1.0)]
    frame = dune(cache_root, results_payload(rows)).fetch_transfers(ASSET, start=START, end=END)
    assert frame["retrieved_at"].item() != END
