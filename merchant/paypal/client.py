"""Live PayPal client: OAuth, Orders v2, Vault v3, webhook verification (doc 04).

The only module allowed to talk to PayPal over HTTP. Status: written against
PayPal's documentation; the behaviours marked VERIFY IN SPIKE (saved-source
charges, stored-credential encoding, vaulted decline triggers, webhook
verification) are proven by `scripts/spike/` before this is relied on.

Error policy (doc 04 §7): 401 → refresh token once; 422 → a decline (mapped by
the taxonomy, not raised); 409/duplicate request id → replay, fetch the order;
429/5xx/timeout → retry up to 3x with the *same* PayPal-Request-Id, then
PayPalError (the executor marks the action DEFERRED; the reconciler follows up).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from merchant.paypal.types import OrderResult, PaymentToken, PayPalError, SetupToken
from shared.money import from_paypal, to_paypal

BASE_URLS = {"sandbox": "https://api-m.sandbox.paypal.com", "live": "https://api-m.paypal.com"}
RETRIES = 3


def parse_order(body: dict[str, Any]) -> OrderResult:
    """Normalise an Orders v2 order body (create / get / capture all return one)."""
    order_id = body.get("id")
    approve = next((link["href"] for link in body.get("links", [])
                    if link.get("rel") in ("payer-action", "approve")), None)
    captures = [c for pu in body.get("purchase_units", [])
                for c in pu.get("payments", {}).get("captures", [])]
    if captures:
        cap = captures[-1]
        pr = cap.get("processor_response") or {}
        status = {"COMPLETED": "COMPLETED", "DECLINED": "DECLINED",
                  "PENDING": "PENDING", "FAILED": "DECLINED"}.get(cap.get("status"), "ERROR")
        return OrderResult(status, order_id, cap.get("id"), pr.get("response_code"),
                           None, None, approve, body)
    status = body.get("status")
    if status == "PAYER_ACTION_REQUIRED" or (status == "CREATED" and approve):
        return OrderResult("PAYER_ACTION_REQUIRED", order_id, approve_url=approve, raw=body)
    if status == "COMPLETED":
        return OrderResult("COMPLETED", order_id, raw=body)
    return OrderResult("PENDING", order_id, approve_url=approve, raw=body)


def parse_error(body: dict[str, Any]) -> OrderResult:
    """A 422 whose details[].issue names the decline (doc 04 §4, shape 2)."""
    detail = (body.get("details") or [{}])[0]
    return OrderResult("DECLINED", issue=detail.get("issue"),
                       description=detail.get("description") or body.get("message"), raw=body)


class LivePayPal:
    mode = "live"

    def __init__(self, client_id: str, client_secret: str, env: str = "sandbox",
                 webhook_id: str = "", http: httpx.Client | None = None) -> None:
        self.base = BASE_URLS[env]
        self._creds = (client_id, client_secret)
        self.webhook_id = webhook_id
        self.http = http or httpx.Client(timeout=30)
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    # -- OAuth ------------------------------------------------------------
    def _access_token(self, force: bool = False) -> str:
        with self._lock:
            if force or not self._token or self._token[1] < time.time() + 60:
                r = self.http.post(f"{self.base}/v1/oauth2/token", auth=self._creds,
                                   data={"grant_type": "client_credentials"})
                if r.status_code != 200:
                    raise PayPalError(f"OAuth failed: {r.status_code}")
                body = r.json()
                self._token = (body["access_token"], time.time() + int(body.get("expires_in", 300)))
            return self._token[0]

    def _request(self, method: str, path: str, *, request_id: str | None = None,
                 json: Any = None) -> httpx.Response:
        refreshed = False
        for attempt in range(RETRIES):
            headers = {"Authorization": f"Bearer {self._access_token(force=refreshed)}",
                       "Content-Type": "application/json", "Prefer": "return=representation"}
            if request_id:
                headers["PayPal-Request-Id"] = request_id
            try:
                r = self.http.request(method, f"{self.base}{path}", headers=headers, json=json)
            except httpx.TransportError as exc:
                if attempt == RETRIES - 1:
                    raise PayPalError(f"{method} {path}: {exc}") from exc
                time.sleep(0.5 * 2 ** attempt)
                continue
            if r.status_code == 401 and not refreshed:
                refreshed = True
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == RETRIES - 1:
                    raise PayPalError(f"{method} {path}: HTTP {r.status_code}")
                time.sleep(0.5 * 2 ** attempt)
                continue
            return r
        raise PayPalError(f"{method} {path}: retries exhausted")

    def _order_call(self, method: str, path: str, request_id: str | None,
                    body: Any = None) -> OrderResult:
        r = self._request(method, path, request_id=request_id, json=body)
        if r.status_code in (200, 201):
            return parse_order(r.json())
        if r.status_code == 422:
            return parse_error(r.json())
        raise PayPalError(f"{method} {path}: HTTP {r.status_code} {r.text[:200]}")

    # -- Orders -----------------------------------------------------------
    def charge_vaulted(self, *, intent_id, amount_minor, currency, vault_id, kind,
                       request_id, stored_credential=None) -> OrderResult:
        if kind == "PAYPAL_WALLET":
            source: dict[str, Any] = {"paypal": {"vault_id": vault_id}}
        else:
            source = {"card": {"vault_id": vault_id}}
            if stored_credential:
                source["card"]["stored_credential"] = stored_credential
        body = {"intent": "CAPTURE",
                "purchase_units": [{"reference_id": intent_id, "custom_id": intent_id,
                                    "amount": {"currency_code": currency,
                                               "value": to_paypal(amount_minor, currency)}}],
                "payment_source": source}
        result = self._order_call("POST", "/v2/checkout/orders", request_id, body)
        # Some sources complete on create; others need an explicit capture (spike item).
        if result.status == "PENDING" and result.order_id and not result.approve_url:
            return self.capture(result.order_id, request_id=f"{request_id}-cap")
        return result

    def create_payer_order(self, *, intent_id, amount_minor, currency, request_id,
                           return_url, cancel_url) -> OrderResult:
        body = {"intent": "CAPTURE",
                "purchase_units": [{"reference_id": intent_id, "custom_id": intent_id,
                                    "amount": {"currency_code": currency,
                                               "value": to_paypal(amount_minor, currency)}}],
                "payment_source": {"paypal": {"experience_context": {
                    "return_url": return_url, "cancel_url": cancel_url,
                    "user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING"}}}}
        return self._order_call("POST", "/v2/checkout/orders", request_id, body)

    def capture(self, order_id, *, request_id) -> OrderResult:
        return self._order_call("POST", f"/v2/checkout/orders/{order_id}/capture", request_id, {})

    def get_order(self, order_id) -> OrderResult:
        return self._order_call("GET", f"/v2/checkout/orders/{order_id}", None)

    # -- Vault ------------------------------------------------------------
    def create_setup_token(self, *, customer_id, kind, return_url, cancel_url, request_id,
                           card_name=None) -> SetupToken:
        if kind != "PAYPAL_WALLET":
            raise PayPalError("card setup tokens need card fields; use the spike script")
        body = {"customer": {"id": customer_id},
                "payment_source": {"paypal": {
                    "usage_type": "MERCHANT", "usage_pattern": "UNSCHEDULED_PREPAID",
                    "experience_context": {"return_url": return_url, "cancel_url": cancel_url}}}}
        r = self._request("POST", "/v3/vault/setup-tokens", request_id=request_id, json=body)
        if r.status_code not in (200, 201):
            raise PayPalError(f"setup token: HTTP {r.status_code}")
        b = r.json()
        href = next(link["href"] for link in b.get("links", []) if link.get("rel") == "approve")
        return SetupToken(b["id"], href)

    def create_payment_token(self, *, setup_token_id, customer_id, request_id) -> PaymentToken:
        body = {"payment_source": {"token": {"id": setup_token_id, "type": "SETUP_TOKEN"}}}
        r = self._request("POST", "/v3/vault/payment-tokens", request_id=request_id, json=body)
        if r.status_code not in (200, 201):
            raise PayPalError(f"payment token: HTTP {r.status_code}")
        b = r.json()
        return PaymentToken(b["id"], (b.get("customer") or {}).get("id", customer_id))

    # -- Webhooks ---------------------------------------------------------
    def verify_webhook(self, headers: dict[str, str], body: dict[str, Any]) -> bool:
        """POST /v1/notifications/verify-webhook-signature. Never weakened to pass."""
        if not self.webhook_id:
            return False
        h = {k.lower(): v for k, v in headers.items()}
        payload = {"auth_algo": h.get("paypal-auth-algo"), "cert_url": h.get("paypal-cert-url"),
                   "transmission_id": h.get("paypal-transmission-id"),
                   "transmission_sig": h.get("paypal-transmission-sig"),
                   "transmission_time": h.get("paypal-transmission-time"),
                   "webhook_id": self.webhook_id, "webhook_event": body}
        if not all(payload.values()):
            return False
        r = self._request("POST", "/v1/notifications/verify-webhook-signature", json=payload)
        return r.status_code == 200 and r.json().get("verification_status") == "SUCCESS"


def amount_of(result: OrderResult, currency: str) -> int | None:
    """Captured amount in minor units, when the order body carries it."""
    for pu in result.raw.get("purchase_units", []):
        for cap in pu.get("payments", {}).get("captures", []):
            if cap.get("amount"):
                return from_paypal(cap["amount"]["value"], currency)
    return None
