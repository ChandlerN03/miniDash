def split_evenly(total_cents: int, parts: int) -> list[int]:
    if parts < 1:
        raise ValueError("parts must be at least 1")
    if total_cents < 0:
        raise ValueError("total_cents cannot be negative")
    base_share, remainder = divmod(total_cents, parts)
    shares = [base_share] * parts
    for i in range(remainder):
        shares[parts - 1 - i] += 1
    return shares