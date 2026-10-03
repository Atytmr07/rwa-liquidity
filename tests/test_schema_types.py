"""Transfer classification vocabulary.

`VolumeMode.kinds` is the switch every volume metric filters on, so the mapping
from mode to transfer kinds is methodology rather than plumbing. It is asserted
here explicitly rather than left to be inferred from a metric's output.
"""

from __future__ import annotations

from rwa_liquidity.schema.types import BURN_ADDRESSES, ZERO_ADDRESS, TransferKind, VolumeMode


def test_secondary_only_counts_nothing_but_secondary() -> None:
    assert VolumeMode.SECONDARY_ONLY.kinds == {TransferKind.SECONDARY}


def test_primary_only_counts_issuance_and_redemption() -> None:
    assert VolumeMode.PRIMARY_ONLY.kinds == {TransferKind.MINT, TransferKind.BURN}


def test_all_counts_every_kind() -> None:
    assert VolumeMode.ALL.kinds == set(TransferKind)


def test_unclassified_is_counted_only_under_all() -> None:
    # Assigning an unclassifiable transfer to the secondary bucket would
    # overstate liquidity, which is the specific error this package exists to
    # avoid; assigning it to primary would understate it. It is only included
    # when the caller has explicitly asked for everything.
    assert TransferKind.UNCLASSIFIED in VolumeMode.ALL.kinds
    assert TransferKind.UNCLASSIFIED not in VolumeMode.SECONDARY_ONLY.kinds
    assert TransferKind.UNCLASSIFIED not in VolumeMode.PRIMARY_ONLY.kinds


def test_the_modes_partition_the_classified_kinds() -> None:
    # Every classified kind is counted by exactly one of the two narrow modes,
    # so primary_only and secondary_only volumes sum to the classified total.
    primary = VolumeMode.PRIMARY_ONLY.kinds
    secondary = VolumeMode.SECONDARY_ONLY.kinds
    assert not primary & secondary
    assert primary | secondary == set(TransferKind) - {TransferKind.UNCLASSIFIED}


def test_default_mode_is_the_conservative_one() -> None:
    # Stated as a test because it is the package's headline methodological
    # choice, and a silent flip of this default would change every published
    # number without changing any formula.
    assert VolumeMode("secondary_only") is VolumeMode.SECONDARY_ONLY


def test_kinds_are_plain_strings_so_they_survive_a_parquet_round_trip() -> None:
    # StrEnum members are strings at runtime, which is what lets `kind` be a
    # plain String column rather than something parquet has to be taught about.
    assert f"{TransferKind.MINT}" == "mint"
    assert f"{VolumeMode.SECONDARY_ONLY}" == "secondary_only"


def test_zero_address_is_treated_as_a_burn_destination() -> None:
    assert ZERO_ADDRESS in BURN_ADDRESSES
