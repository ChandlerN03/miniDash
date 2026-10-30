import pytest

from src.services.fee_split import split_evenly


# R22 / R23: required examples (total cents, number of parts, expected shares)
@pytest.mark.parametrize(
    ("total_cents", "parts", "expected"),
    [
        (100, 3, [33, 33, 34]),
        (101, 3, [33, 34, 34]),
        (2, 5, [0, 0, 0, 1, 1]),
        (300, 3, [100, 100, 100]),
        (499, 1, [499]),
    ],
)
def test_required_examples(total_cents, parts, expected):
    assert split_evenly(total_cents, parts) == expected


# R22: base share is the fee divided by the participants, rounded down
def test_every_share_is_at_least_the_rounded_down_base_share():
    shares = split_evenly(499, 4)  # 499 // 4 == 124, remainder 3

    assert all(share >= 124 for share in shares)


# R23: leftover cents go one at a time, starting with the last participant
def test_leftover_cents_go_to_the_last_participants_not_the_first():
    assert split_evenly(103, 5) == [20, 20, 21, 21, 21]  # remainder 3


def test_each_participant_gets_at_most_one_leftover_cent():
    shares = split_evenly(7, 10)  # base 0, remainder 7

    assert shares == [0, 0, 0, 1, 1, 1, 1, 1, 1, 1]


def test_zero_total_gives_zero_shares():
    assert split_evenly(0, 4) == [0, 0, 0, 0]


def test_result_has_one_share_per_participant():
    assert len(split_evenly(499, 7)) == 7


def test_result_contains_integers_only():
    shares = split_evenly(499, 3)

    assert all(type(share) is int for share in shares)


# R24: shares always sum to the fee, and differ by at most 1 cent.
# Also checks R23's ordering: later participants never get less than earlier ones.
def test_many_totals_and_group_sizes():
    for total_cents in range(0, 1001):
        for parts in range(1, 21):
            shares = split_evenly(total_cents, parts)
            context = f"total={total_cents}, parts={parts}, shares={shares}"

            assert len(shares) == parts, context
            assert sum(shares) == total_cents, context
            assert max(shares) - min(shares) <= 1, context
            assert min(shares) == total_cents // parts, context
            assert shares == sorted(shares), context
            assert sum(1 for share in shares if share > total_cents // parts) == total_cents % parts, context


# Invalid input
@pytest.mark.parametrize("parts", [0, -1, -10])
def test_parts_below_one_raises_value_error(parts):
    with pytest.raises(ValueError):
        split_evenly(100, parts)


@pytest.mark.parametrize("total_cents", [-1, -499])
def test_negative_total_raises_value_error(total_cents):
    with pytest.raises(ValueError):
        split_evenly(total_cents, 3)


def test_negative_total_and_parts_below_one_raises_value_error():
    with pytest.raises(ValueError):
        split_evenly(-1, 0)
