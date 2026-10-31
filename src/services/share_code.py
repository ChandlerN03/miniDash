import secrets
import string
from typing import Collection, Protocol

CODE_LENGTH = 6
MAX_ATTEMPTS = 100

# A-Z, a-z and 0-9 without the look-alike characters 0, O, 1, I and l (57 left).
AMBIGUOUS = "0O1Il"
ALPHABET = "".join(
    c for c in string.ascii_uppercase + string.ascii_lowercase + string.digits if c not in AMBIGUOUS
)


class Rng(Protocol):
    """Anything with choice(sequence), such as random.Random or secrets.SystemRandom."""

    def choice(self, sequence): ...


def generate_share_code(existing_codes: Collection[str], rng: Rng | None = None) -> str:
    """Return a new share code that is not in `existing_codes`.

    A code is CODE_LENGTH characters from ALPHABET. If a generated code is
    already taken, another one is generated. After MAX_ATTEMPTS taken codes in
    a row, RuntimeError is raised. Pass `rng` to make the result repeatable in
    tests; by default the secrets module is used.
    """
    if rng is None:
        rng = secrets.SystemRandom()

    for _ in range(MAX_ATTEMPTS):
        code = "".join(rng.choice(ALPHABET) for _ in range(CODE_LENGTH))
        if code not in existing_codes:
            return code

    raise RuntimeError(f"Could not generate an unused share code in {MAX_ATTEMPTS} attempts.")
