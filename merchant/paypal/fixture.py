"""Fixture PayPal: deterministic, offline, labelled `fixture` everywhere it shows.

Used when no PayPal credentials are configured, so a clean clone runs every
scenario and the tests never touch the network. It mimics the sandbox's
documented behaviour:

- A saved card whose *name* is a sandbox trigger (`CCREJECT-IF`, `CCREJECT-SF`, …)
  declines with that trigger's processor response code, as on PayPal's
  card-testing page. Any other saved source completes.
- A source can be forced to decline once with `force_decline(vault_id, code)`,
  standing in for the sandbox negative-testing header (S3's wallet decline).
- `PayPal-Request-Id` is honoured: the same request id returns the same result
  and never creates a second order.
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any

from merchant.engine.taxonomy import SANDBOX_TRIGGERS
from merchant.paypal.types import OrderResult, PaymentToken, SetupToken


def _id(*parts: str, n: int = 17) -> str:
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:n].upper()


class FixturePayPal:
    mode = "fixture"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.by_request: dict[str, OrderResult] = {}
        self.orders: dict[str, OrderResult] = {}
        self.vault: dict[str, dict[str, str]] = {}       # vault_id -> {kind, card_name, customer}
        self.setup_tokens: dict[str, dict[str, str]] = {}
        self.forced: dict[str, list[str]] = {}            # vault_id -> queued processor codes
        self.write_calls = 0                              # for the kill-switch invariant (I10)

    # -- test / seed helpers ------------------------------------------------
    def add_vaulted(self, vault_id: str, kind: str, customer_id: str,
                    card_name: str | None = None) -> None:
        self.vault[vault_id] = {"kind": kind, "card_name": card_name or "", "customer": customer_id}

    def force_decline(self, vault_id: str, processor_code: str) -> None:
        self.forced.setdefault(vault_id, []).append(processor_code)

    # -- PayPal protocol ------------------------------------------------------
    def _idempotent(self, request_id: str, make) -> OrderResult:
        with self._lock:
            self.write_calls += 1
            if request_id in self.by_request:
                return self.by_request[request_id]
            result = make()
            self.by_request[request_id] = result
            if result.order_id:
                self.orders[result.order_id] = result
            return result

    def charge_vaulted(self, *, intent_id, amount_minor, currency, vault_id, kind,
                       request_id, stored_credential=None) -> OrderResult:
        def make() -> OrderResult:
            order_id = _id("order", request_id)
            meta = self.vault.get(vault_id)
            if meta is None:
                return OrderResult("DECLINED", order_id, issue="INSTRUMENT_DECLINED",
                                   description="Unknown vault id (fixture).")
            code = None
            if self.forced.get(vault_id):
                code = self.forced[vault_id].pop(0)
            elif meta["card_name"] in SANDBOX_TRIGGERS:
                code = SANDBOX_TRIGGERS[meta["card_name"]]
            raw = {"id": order_id, "custom_id": intent_id, "amount_minor": amount_minor,
                   "currency": currency, "fixture": True}
            if code:
                return OrderResult("DECLINED", order_id, _id("cap", request_id),
                                   processor_response_code=code, raw=raw)
            return OrderResult("COMPLETED", order_id, _id("cap", request_id), raw=raw)
        return self._idempotent(request_id, make)

    def create_payer_order(self, *, intent_id, amount_minor, currency, request_id,
                           return_url, cancel_url) -> OrderResult:
        def make() -> OrderResult:
            order_id = _id("order", request_id)
            return OrderResult(
                "PAYER_ACTION_REQUIRED", order_id,
                approve_url=f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}",
                raw={"id": order_id, "custom_id": intent_id, "amount_minor": amount_minor,
                     "currency": currency, "fixture": True})
        return self._idempotent(request_id, make)

    def approve(self, order_id: str) -> None:
        """Fixture stand-in for the payer approving on PayPal."""
        with self._lock:
            o = self.orders[order_id]
            self.orders[order_id] = OrderResult("APPROVED", o.order_id, approve_url=o.approve_url,
                                                raw=o.raw)

    def capture(self, order_id, *, request_id) -> OrderResult:
        def make() -> OrderResult:
            o = self.orders.get(order_id)
            if o is None or o.status not in ("APPROVED", "COMPLETED"):
                return OrderResult("PAYER_ACTION_REQUIRED", order_id,
                                   approve_url=o.approve_url if o else None,
                                   issue="ORDER_NOT_APPROVED")
            return OrderResult("COMPLETED", order_id, _id("cap", order_id), raw=o.raw)
        result = self._idempotent(request_id, make)
        if result.paid:
            self.orders[order_id] = result
        return result

    def get_order(self, order_id) -> OrderResult:
        return self.orders.get(order_id) or OrderResult("ERROR", order_id)

    def create_setup_token(self, *, customer_id, kind, return_url, cancel_url, request_id,
                           card_name=None) -> SetupToken:
        token = _id("setup", request_id, n=12)
        self.setup_tokens[token] = {"customer": customer_id, "kind": kind,
                                    "card_name": card_name or ""}
        sep = "&" if "?" in return_url else "?"
        return SetupToken(token, f"{return_url}{sep}approval_token_id={token}&fixture=1")

    def create_payment_token(self, *, setup_token_id, customer_id, request_id) -> PaymentToken:
        meta = self.setup_tokens[setup_token_id]
        vault_id = _id("vault", setup_token_id, n=10).lower()
        self.add_vaulted(vault_id, meta["kind"], customer_id, meta["card_name"])
        return PaymentToken(vault_id, customer_id)

    def verify_webhook(self, headers: dict[str, str], body: dict[str, Any]) -> bool:
        # Fixture webhooks are only trusted when explicitly marked by the test harness.
        return headers.get("x-fixture-verified") == "1"
