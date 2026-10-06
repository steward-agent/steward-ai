"""Minor-unit conversion for providers that charge in cents."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

ZERO_DECIMAL = {
    "BIF",
    "CLP",
    "DJF",
    "GNF",
    "JPY",
    "KMF",
    "KRW",
    "MGA",
    "PYG",
    "RWF",
    "UGX",
    "VND",
    "VUV",
    "XAF",
    "XOF",
    "XPF",
}


def to_minor(amount: Decimal, currency: str) -> int:
    if currency.upper() in ZERO_DECIMAL:
        return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_minor(amount: int, currency: str) -> Decimal:
    if currency.upper() in ZERO_DECIMAL:
        return Decimal(amount)
    return (Decimal(amount) / Decimal(100)).quantize(Decimal("0.01"))
