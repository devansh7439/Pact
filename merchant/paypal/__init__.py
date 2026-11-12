"""PayPal integration. `make_paypal()` picks live (credentials present) or fixture."""

from __future__ import annotations

from merchant.config import Settings
from merchant.paypal.fixture import FixturePayPal
from merchant.paypal.types import OrderResult, PaymentToken, PayPal, PayPalError, SetupToken

__all__ = ["FixturePayPal", "OrderResult", "PayPal", "PayPalError", "PaymentToken",
           "SetupToken", "make_paypal"]


def make_paypal(settings: Settings) -> PayPal:
    if settings.paypal_live:
        from merchant.paypal.client import LivePayPal
        return LivePayPal(settings.paypal_client_id, settings.paypal_client_secret,
                          settings.paypal_env, settings.paypal_webhook_id)
    return FixturePayPal()
