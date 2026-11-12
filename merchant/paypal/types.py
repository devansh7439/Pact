"""Normalised PayPal results. Everything above `merchant/paypal/` sees only these."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class OrderResult:
    """One Orders v2 attempt, normalised across PayPal's two decline shapes (doc 04 §4).

    status: COMPLETED | DECLINED | PAYER_ACTION_REQUIRED | PENDING | ERROR
    """

    status: str
    order_id: str | None = None
    capture_id: str | None = None
    processor_response_code: str | None = None
    issue: str | None = None
    description: str | None = None
    approve_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def paid(self) -> bool:
        return self.status == "COMPLETED"


@dataclass(frozen=True, slots=True)
class SetupToken:
    token_id: str
    approve_url: str


@dataclass(frozen=True, slots=True)
class PaymentToken:
    vault_id: str
    customer_id: str


class PayPalError(RuntimeError):
    """Transport-level failure after retries (5xx, timeout, 429). Not a decline."""


class PayPal(Protocol):
    mode: str  # "live" | "fixture"

    def charge_vaulted(self, *, intent_id: str, amount_minor: int, currency: str,
                       vault_id: str, kind: str, request_id: str,
                       stored_credential: dict[str, str] | None = None) -> OrderResult: ...

    def create_payer_order(self, *, intent_id: str, amount_minor: int, currency: str,
                           request_id: str, return_url: str, cancel_url: str) -> OrderResult: ...

    def capture(self, order_id: str, *, request_id: str) -> OrderResult: ...

    def get_order(self, order_id: str) -> OrderResult: ...

    def create_setup_token(self, *, customer_id: str, kind: str, return_url: str,
                           cancel_url: str, request_id: str,
                           card_name: str | None = None) -> SetupToken: ...

    def create_payment_token(self, *, setup_token_id: str, customer_id: str,
                             request_id: str) -> PaymentToken: ...

    def verify_webhook(self, headers: dict[str, str], body: dict[str, Any]) -> bool: ...
