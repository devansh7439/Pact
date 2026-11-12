"""Money: integer minor units everywhere, PayPal decimal strings only at the edge.

Every amount inside Pact is an `int` in the currency's minor unit (cents for
USD). PayPal's APIs take and return decimal strings ("32.00"). This module is
the only place the two meet, so no float ever touches a money value.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

#: Currencies PayPal treats as having no minor unit. Amounts in these must be
#: sent as whole numbers ("1000", not "1000.00").
ZERO_DECIMAL_CURRENCIES: frozenset[str] = frozenset({"HUF", "JPY", "TWD"})

_SYMBOLS: dict[str, str] = {"USD": "$", "EUR": "€", "GBP": "£", "AUD": "A$", "CAD": "C$"}


def exponent(currency_code: str) -> int:
    """Number of minor-unit digits for a currency."""
    return 0 if currency_code.upper() in ZERO_DECIMAL_CURRENCIES else 2


def to_paypal(value_minor: int, currency_code: str) -> str:
    """Integer minor units -> PayPal amount string. `to_paypal(3200, "USD") == "32.00"`."""
    if not isinstance(value_minor, int) or isinstance(value_minor, bool):
        raise TypeError(f"value_minor must be int, got {type(value_minor).__name__}")
    if value_minor < 0:
        raise ValueError(f"value_minor must be non-negative, got {value_minor}")
    exp = exponent(currency_code)
    if exp == 0:
        return str(value_minor)
    return f"{Decimal(value_minor).scaleb(-exp):.{exp}f}"


def from_paypal(value: str, currency_code: str) -> int:
    """PayPal amount string -> integer minor units. Rejects sub-minor precision."""
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"not a decimal amount: {value!r}") from exc
    exp = exponent(currency_code)
    scaled = amount.scaleb(exp)
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{value!r} has more precision than {currency_code} allows")
    if scaled < 0:
        raise ValueError(f"negative amount: {value!r}")
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


def fmt(value_minor: int, currency_code: str = "USD") -> str:
    """Human display: `fmt(3200) == "$32.00"`, `fmt(-50) == "-$0.50"`."""
    exp = exponent(currency_code)
    sign = "-" if value_minor < 0 else ""
    major = Decimal(abs(value_minor)).scaleb(-exp)
    symbol = _SYMBOLS.get(currency_code.upper())
    body = f"{major:,.{exp}f}"
    return f"{sign}{symbol}{body}" if symbol else f"{sign}{body} {currency_code.upper()}"
