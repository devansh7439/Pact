"""The only caller of PayPal *write* functions (doc 02 §7).

Every new attempt re-runs two checks immediately before the PayPal call, not just
at decision time (doc 05, HARD_CONSENT_INVALID; doc 08 I10, I16):

- kill switch off;
- consent: the alias maps to an ACTIVE saved method owned by this customer, and —
  for the agent channel — the registration is ACTIVE and the registered mandate is
  unexpired with caps that still allow the amount.

A revocation between accept and execution therefore still stops the charge.
Every write carries a deterministic PayPal-Request-Id, so retries never duplicate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from merchant.db import Database, audit, dumps, now_iso
from merchant.paypal.types import OrderResult, PayPal, PayPalError
from shared.prp.ids import new_id

#: Stored-credential encoding for saved cards. Working choice A (doc 04 §3.4),
#: pending spike step S4b; recoveries use the same encoding as the original purchase.
STORED_CREDENTIAL_AGENT = {"payment_initiator": "CUSTOMER", "payment_type": "ONE_TIME",
                           "usage": "SUBSEQUENT"}
STORED_CREDENTIAL_MERCHANT = {"payment_initiator": "MERCHANT", "payment_type": "UNSCHEDULED",
                              "usage": "SUBSEQUENT"}


class ExecutionBlocked(Exception):
    """A pre-call check failed. `code` is a PRP error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class AttemptResult:
    attempt_id: str
    result: OrderResult
    funding_alias: str | None


def consent_problem(db: Database, intent_id: str, alias: str, now: datetime | None = None) -> str | None:
    """The HARD_CONSENT_INVALID check. Returns a reason string, or None when consent holds."""
    now = now or datetime.now(timezone.utc)
    intent = db.one("SELECT * FROM payment_intents WHERE intent_id=?", (intent_id,))
    if intent is None:
        return "unknown intent"
    src = db.one("SELECT * FROM funding_sources WHERE customer_id=? AND alias=?",
                 (intent["customer_id"], alias))
    if src is None:
        return f"alias {alias!r} is not a saved method of this customer"
    if src["status"] != "ACTIVE":
        return f"saved method {alias!r} is {src['status']}"
    if intent["channel"] == "agent":
        reg = db.one("SELECT status FROM agent_registrations WHERE agent_id=?", (intent["agent_id"],))
        if reg is None or reg["status"] != "ACTIVE":
            return "agent registration is not active"
        mdt = db.one("SELECT * FROM registered_mandates WHERE mandate_id=?", (intent["mandate_id"],))
        if mdt is None:
            return "no registered mandate"
        if datetime.fromisoformat(mdt["expires_at"]) <= now:
            return "registered mandate has expired"
        caps = json.loads(mdt["caps_json"])
        if intent["amount_minor"] > caps["per_purchase_cap_minor"]:
            return "amount exceeds the registered per-purchase cap"
        if alias not in {f["alias"] for f in caps["funding"]}:
            return f"alias {alias!r} is not in the registered mandate"
    return None


class Executor:
    def __init__(self, db: Database, paypal: PayPal, *, killed: callable,
                 merchant_public_url: str) -> None:
        # Gate on the kill switch only. Review-first is enforced by the service,
        # which queues the work; an approved item then executes through here.
        self.db, self.paypal, self._killed = db, paypal, killed
        self.public_url = merchant_public_url.rstrip("/")

    def _gate(self) -> None:
        if self._killed():
            raise ExecutionBlocked("KILL_SWITCH_ACTIVE", "Kill switch is on: nothing executes.")

    def charge(self, intent_id: str, alias: str, request_id: str) -> AttemptResult:
        """Charge a saved method. Idempotent on request_id (a replay returns the stored attempt)."""
        prior = self.db.one("SELECT * FROM attempts WHERE request_id=?", (request_id,))
        if prior is not None:
            return AttemptResult(prior["attempt_id"], _from_row(prior), prior["funding_alias"])

        self._gate()
        if problem := consent_problem(self.db, intent_id, alias):
            with self.db.tx() as conn:
                audit(conn, intent_id, "CONSENT_CHECK", {"alias": alias, "ok": False,
                                                         "reason": problem})
            raise ExecutionBlocked("CONSENT_INVALID", problem)

        intent = self.db.one("SELECT * FROM payment_intents WHERE intent_id=?", (intent_id,))
        src = self.db.one("SELECT * FROM funding_sources WHERE customer_id=? AND alias=?",
                          (intent["customer_id"], alias))
        sc = STORED_CREDENTIAL_AGENT if intent["channel"] == "agent" else STORED_CREDENTIAL_MERCHANT
        try:
            result = self.paypal.charge_vaulted(
                intent_id=intent_id, amount_minor=intent["amount_minor"],
                currency=intent["currency_code"], vault_id=src["vault_id"], kind=src["kind"],
                request_id=request_id, stored_credential=sc if src["kind"] == "CARD" else None)
        except PayPalError as exc:
            result = OrderResult("ERROR", description=str(exc))
        return self._record(intent_id, alias, request_id, result)

    def payer_order(self, intent_id: str, request_id: str) -> AttemptResult:
        """An order needing payer approval (PAYER_ACTION / CHECKOUT_LINK). Moves no money."""
        prior = self.db.one("SELECT * FROM attempts WHERE request_id=?", (request_id,))
        if prior is not None:
            return AttemptResult(prior["attempt_id"], _from_row(prior), None)
        self._gate()
        intent = self.db.one("SELECT * FROM payment_intents WHERE intent_id=?", (intent_id,))
        try:
            result = self.paypal.create_payer_order(
                intent_id=intent_id, amount_minor=intent["amount_minor"],
                currency=intent["currency_code"], request_id=request_id,
                return_url=f"{self.public_url}/paypal/return?intent_id={intent_id}",
                cancel_url=f"{self.public_url}/paypal/return?intent_id={intent_id}&cancel=1")
        except PayPalError as exc:
            result = OrderResult("ERROR", description=str(exc))
        return self._record(intent_id, None, request_id, result)

    def capture(self, intent_id: str, order_id: str) -> AttemptResult:
        """Capture an approved payer order. Idempotent via a request id derived from the order."""
        self._gate()
        request_id = f"cap_{order_id}"
        try:
            result = self.paypal.capture(order_id, request_id=request_id)
        except PayPalError as exc:
            result = OrderResult("ERROR", order_id, description=str(exc))
        row = self.db.one("SELECT * FROM attempts WHERE paypal_order_id=?", (order_id,))
        with self.db.tx() as conn:
            conn.execute("UPDATE attempts SET status=?, paypal_capture_id=COALESCE(?, paypal_capture_id), "
                         "raw_json=? WHERE paypal_order_id=?",
                         (result.status, result.capture_id, dumps(result.raw), order_id))
            audit(conn, intent_id, "CAPTURE", {"order_id": order_id, "status": result.status})
        return AttemptResult(row["attempt_id"] if row else "", result, row["funding_alias"] if row else None)

    def _record(self, intent_id: str, alias: str | None, request_id: str,
                result: OrderResult) -> AttemptResult:
        attempt_id = new_id("att")
        with self.db.tx() as conn:
            conn.execute(
                "INSERT INTO attempts (attempt_id, intent_id, paypal_order_id, paypal_capture_id, "
                "funding_alias, request_id, status, processor_code, issue, raw_json, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (attempt_id, intent_id, result.order_id, result.capture_id, alias, request_id,
                 result.status, result.processor_response_code, result.issue,
                 dumps({**result.raw, "approve_url": result.approve_url,
                        "description": result.description}), now_iso()))
            audit(conn, intent_id, "ATTEMPT", {"attempt_id": attempt_id, "alias": alias,
                                               "request_id": request_id, "status": result.status,
                                               "processor_code": result.processor_response_code,
                                               "issue": result.issue})
        return AttemptResult(attempt_id, result, alias)


def _from_row(row) -> OrderResult:
    raw = json.loads(row["raw_json"] or "{}")
    return OrderResult(row["status"], row["paypal_order_id"], row["paypal_capture_id"],
                       row["processor_code"], row["issue"], raw.get("description"),
                       raw.get("approve_url"), raw)
