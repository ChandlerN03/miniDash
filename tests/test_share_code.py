import random

import pytest

from src.services.share_code import ALPHABET, generate_share_code

FORBIDDEN = set("0O1Il")
SAMPLES = 2000


class ScriptedRng:
    """A fake rng that hands out a fixed list of codes, one character per choice() call.

    It has the same choice(sequence) method as random.Random. It fails the test
    if the code asks for more characters than were scripted, and if a scripted
    character is not in the sequence offered.
    """

    def __init__(self, codes: list[str]):
        self._chars = list("".join(codes))
        self.calls = 0

    def choice(self, sequence):
        assert self._chars, "rng was asked for more characters than the test scripted"
        char = self._chars.pop(0)
        assert char in sequence, f"scripted character {char!r} is not in the alphabet offered"
        self.calls += 1
        return char

    @property
    def remaining(self) -> int:
        return len(self._chars)


# ------------------------------------------------------------------- alphabet


def test_alphabet_has_exactly_57_characters():
    assert len(ALPHABET) == 57


def test_alphabet_has_no_repeated_characters():
    assert len(set(ALPHABET)) == len(ALPHABET)


def test_alphabet_excludes_the_ambiguous_characters():
    assert FORBIDDEN.isdisjoint(ALPHABET)


def test_alphabet_has_every_other_letter_and_digit():
    upper = set("ABCDEFGHJKLMNPQRSTUVWXYZ")  # A-Z without I and O
    lower = set("abcdefghijkmnopqrstuvwxyz")  # a-z without l
    digits = set("23456789")  # 0-9 without 0 and 1

    assert set(ALPHABET) == upper | lower | digits


def test_alphabet_is_case_sensitive():
    assert "a" in ALPHABET and "A" in ALPHABET


# ---------------------------------------------------- generated codes (default rng)


def test_every_code_is_exactly_6_characters():
    for _ in range(SAMPLES):
        assert len(generate_share_code(set())) == 6


def test_every_code_is_a_string_of_alphabet_characters_only():
    for _ in range(SAMPLES):
        code = generate_share_code(set())
        assert isinstance(code, str)
        assert set(code) <= set(ALPHABET), code


def test_no_code_contains_an_ambiguous_character():
    for _ in range(SAMPLES):
        code = generate_share_code(set())
        assert FORBIDDEN.isdisjoint(code), code


def test_both_upper_and_lower_case_letters_appear_across_many_samples():
    characters = set("".join(generate_share_code(set()) for _ in range(SAMPLES)))

    assert any(c.isupper() for c in characters)
    assert any(c.islower() for c in characters)


def test_digits_appear_across_many_samples():
    characters = set("".join(generate_share_code(set()) for _ in range(SAMPLES)))

    assert any(c.isdigit() for c in characters)


def test_codes_are_not_all_the_same():
    codes = {generate_share_code(set()) for _ in range(200)}

    assert len(codes) > 100


# ------------------------------------------------------------ injected rng


def test_injected_rng_makes_the_result_deterministic():
    first = generate_share_code(set(), rng=random.Random(1234))
    second = generate_share_code(set(), rng=random.Random(1234))

    assert first == second


def test_code_comes_from_the_injected_rng():
    rng = ScriptedRng(["ab2CD3"])

    assert generate_share_code(set(), rng=rng) == "ab2CD3"
    assert rng.calls == 6


def test_rng_is_offered_the_57_character_alphabet():
    offered = []

    class RecordingRng:
        def choice(self, sequence):
            offered.append(len(sequence))
            return sequence[0]

    generate_share_code(set(), rng=RecordingRng())

    assert offered == [57] * 6


# ------------------------------------------------------------- uniqueness (R6)


def test_collision_is_retried_and_the_result_is_not_in_existing_codes():
    existing = {"ab2CD3"}
    rng = ScriptedRng(["ab2CD3", "xY7kQ9"])  # first attempt collides

    code = generate_share_code(existing, rng=rng)

    assert code == "xY7kQ9"
    assert code not in existing
    assert rng.remaining == 0  # both attempts were used


def test_several_collisions_in_a_row_are_retried():
    existing = {"aaaaaa", "bbbbbb", "cccccc"}
    rng = ScriptedRng(["aaaaaa", "bbbbbb", "cccccc", "dddddd"])

    assert generate_share_code(existing, rng=rng) == "dddddd"


def test_codes_differing_only_in_case_are_different_codes():
    existing = {"abcdef"}
    rng = ScriptedRng(["ABCDEF"])

    assert generate_share_code(existing, rng=rng) == "ABCDEF"


def test_existing_codes_are_not_modified():
    existing = {"ab2CD3", "xY7kQ9"}
    before = set(existing)

    generate_share_code(existing)

    assert existing == before


def test_works_when_no_codes_exist_yet():
    assert len(generate_share_code(set(), rng=ScriptedRng(["ab2CD3"]))) == 6


def test_never_returns_an_existing_code_across_many_runs():
    existing: set[str] = set()
    for _ in range(SAMPLES):
        code = generate_share_code(existing)
        assert code not in existing
        existing.add(code)

    assert len(existing) == SAMPLES


# ---------------------------------------------------------- giving up after 100


def test_100_straight_collisions_raise_runtime_error():
    existing = {"ab2CD3"}
    rng = ScriptedRng(["ab2CD3"] * 100)

    with pytest.raises(RuntimeError):
        generate_share_code(existing, rng=rng)

    assert rng.remaining == 0  # it made all 100 attempts


def test_it_does_not_make_a_101st_attempt():
    # The rng fails the test if asked for a 101st code, so this proves the limit.
    existing = {"ab2CD3"}
    rng = ScriptedRng(["ab2CD3"] * 100)

    with pytest.raises(RuntimeError):
        generate_share_code(existing, rng=rng)


def test_success_on_the_100th_attempt_is_returned():
    existing = {"ab2CD3"}
    rng = ScriptedRng(["ab2CD3"] * 99 + ["xY7kQ9"])

    assert generate_share_code(existing, rng=rng) == "xY7kQ9"


def test_success_on_the_99th_attempt_is_returned():
    existing = {"ab2CD3"}
    rng = ScriptedRng(["ab2CD3"] * 98 + ["xY7kQ9"])

    assert generate_share_code(existing, rng=rng) == "xY7kQ9"
