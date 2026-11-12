import pytest
from hypothesis import given
from hypothesis import strategies as st

from shared.money import fmt, from_paypal, to_paypal


def test_usd_round_trip_examples():
    assert to_paypal(3200, "USD") == "32.00"
    assert to_paypal(5, "USD") == "0.05"
    assert from_paypal("32.00", "USD") == 3200
    assert from_paypal("0.5", "USD") == 50


def test_zero_decimal_currency():
    assert to_paypal(1000, "JPY") == "1000"
    assert from_paypal("1000", "JPY") == 1000


@given(st.integers(min_value=0, max_value=10**12))
def test_round_trip_is_exact(value):
    assert from_paypal(to_paypal(value, "USD"), "USD") == value


@pytest.mark.parametrize("bad", ["1.005", "abc", "-1.00"])
def test_from_paypal_rejects_bad_amounts(bad):
    with pytest.raises(ValueError):
        from_paypal(bad, "USD")


def test_to_paypal_refuses_floats_and_negatives():
    with pytest.raises(TypeError):
        to_paypal(32.0, "USD")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        to_paypal(-1, "USD")


def test_fmt():
    assert fmt(3200) == "$32.00"
    assert fmt(-50) == "-$0.50"
    assert fmt(123456) == "$1,234.56"
