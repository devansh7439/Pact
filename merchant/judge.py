"""Judge mode (doc 07 §3, doc 11): one-click scenarios against the running services.

Agent scenarios (S1–S3) are *prepared* here — which saved card fails and how —
and then started the way a real purchase starts: through the buyer agent's public
`POST /buyer/purchases`. The merchant never reads buyer state except through the
buyer's public API (the linked view's optional `buyer` half). S5 (forged offer)
is buyer-side and lives in buyer_agent. S4 and S6 are human-channel reorders the
merchant starts itself.

Fixture mode creates vaulted test cards named with sandbox triggers. Live sandbox
mode needs real vault ids per trigger, saved by the spike scripts into the
`judge_vaults` control as JSON: {"CCREJECT-IF": "<vault_id>", ..., "wallet": "<vault_id>"}.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from merchant.catalog import CATALOG
from merchant.console import linked_merchant_side
from merchant.db import audit, get_control, now_iso, set_control
from merchant.paypal.fixture import FixturePayPal
from merchant.service import MerchantService

log = logging.getLogger(__name__)

ARJUN = "cus_arjun_demo"

SCENARIOS: dict[str, dict[str, Any]] = {
    "S1": {"title": "Autonomous save", "channel": "agent", "card": "CCREJECT-IF",
           "sku": "beans-ethiopia-1kg",
           "story": "Insufficient funds on Maya's card; her agent pays with her PayPal wallet."},
    "S2": {"title": "Refuses to retry", "channel": "agent", "card": "CCREJECT-SF",
           "sku": "beans-house-500g",
           "story": "Suspected fraud: no autonomous retry, Maya gets a one-tap PayPal link."},
    "S3": {"title": "Mandate says no", "channel": "agent", "card": "CCREJECT-REFUSED",
           "wallet_declines": "0500", "sku": "beans-colombia-1kg",
           "story": "Card and then wallet decline; the merchant would try again, Maya's mandate stops it."},
    "S4": {"title": "Not worth chasing", "channel": "human", "card": "CCREJECT-EC",
           "sku": "filters-v60-100",
           "story": "A $4 add-on on an expired card: Pact drops it and shows the arithmetic."},
    "S6": {"title": "Human save", "channel": "human", "card": "CCREJECT-BANK_ERROR",
           "sku": "reorder-fortnightly",
           "story": "Arjun's $48 reorder declines; he gets a clear message and a PayPal link."},
}

#: Tables cleared by a judge reset. Registrations, mandates, customers and saved
#: sources survive, so the buyer's link and mandate stay valid.
RESET_TABLES = ("idempotency", "security_events", "webhook_events", "outcomes", "actions",
                "offers", "failures", "decisions", "attempts", "payment_intents")


class JudgeError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class Judge:
    def __init__(self, svc: MerchantService, buyer: httpx.Client | None) -> None:
        self.svc, self.buyer = svc, buyer

    def _require_judge_mode(self) -> None:
        if not self.svc.s.judge_mode:
            raise JudgeError(403, "judge endpoints are only enabled with JUDGE_MODE=true")

    # -- sources ------------------------------------------------------------------
    def _vault(self, customer_id: str, alias: str, kind: str, trigger: str | None, tag: str) -> None:
        if isinstance(self.svc.paypal, FixturePayPal):
            vault_id = f"jv_{tag}_{alias}"
            self.svc.paypal.add_vaulted(vault_id, kind, customer_id, trigger)
        else:
            table = json.loads(get_control(self.svc.db, "judge_vaults", "{}"))
            vault_id = table.get(trigger or "wallet")
            if not vault_id:
                raise JudgeError(409, f"no sandbox vault id for {trigger or 'wallet'} in judge_vaults")
        self.svc.save_funding(customer_id, alias, kind, vault_id)

    def _maya(self):
        reg = self.svc.db.one("SELECT * FROM agent_registrations ORDER BY created_at DESC LIMIT 1")
        if reg is None:
            raise JudgeError(409, "no buyer agent registered yet: run scripts/seed.py")
        return reg

    def onboard(self, token: str) -> dict[str, Any]:
        """Fixture onboarding for the seed: save Maya's sources and approve her mandate."""
        self._require_judge_mode()
        reg = self.svc.db.one("SELECT * FROM agent_registrations WHERE onboarding_token=?", (token,))
        if reg is None:
            raise JudgeError(404, "unknown onboarding token")
        mandate = json.loads(reg["draft_mandate_json"])
        for f in mandate["funding"]:
            self._vault(reg["customer_id"], f["alias"], f["kind"], None, "seed")
        return self.svc.onboarding_confirm(token, "SANDBOXMAYA01")[1]

    def seed_human(self) -> None:
        if self.svc.db.one("SELECT 1 FROM customers WHERE customer_id=?", (ARJUN,)):
            return
        with self.svc.db.tx() as conn:
            conn.execute("INSERT INTO customers VALUES (?,?,?,?,?,?,?)",
                         (ARJUN, "Arjun Lee", "arjun@example.com", None, "human", 0, now_iso()))
        self._vault(ARJUN, "saved-card", "CARD", None, "seed")

    # -- endpoints -----------------------------------------------------------------
    def reset(self) -> dict[str, Any]:
        self._require_judge_mode()
        with self.svc.db.tx() as conn:
            for table in RESET_TABLES:
                conn.execute(f"DELETE FROM {table}")  # noqa: S608 — fixed table list
            # The audit trail has no DELETE path (triggers); a reset starts a new one.
            conn.execute("DROP TABLE audit_trail")
        from merchant.db import SCHEMA
        with self.svc.db._write_lock:
            conn = self.svc.db._open()
            try:
                conn.executescript(SCHEMA)
            finally:
                if self.svc.db._memory is None:
                    conn.close()
        with self.svc.db.tx() as conn:
            audit(conn, None, "JUDGE_RESET", {})
        self.seed_human()
        buyer_reset = None
        if self.buyer is not None:
            try:
                buyer_reset = self.buyer.post("/buyer/reset").status_code
            except httpx.HTTPError as exc:
                log.warning("buyer reset failed: %s", exc)
        return {"ok": True, "buyer_reset": buyer_reset}

    def run(self, scenario: str) -> dict[str, Any]:
        """Run one scenario. Its intents are exempt from the live holdout while it runs."""
        self._require_judge_mode()
        spec = SCENARIOS.get(scenario)
        if spec is None:
            raise JudgeError(404, f"unknown scenario {scenario}; S5 runs on the buyer side")
        customer = ARJUN if spec["channel"] == "human" else self._maya()["customer_id"]
        with self.svc.db.tx() as conn:
            set_control(conn, "judge_scripted_customer", customer)
        try:
            return self._run(scenario, spec)
        finally:
            with self.svc.db.tx() as conn:
                set_control(conn, "judge_scripted_customer", "")

    def _run(self, scenario: str, spec: dict[str, Any]) -> dict[str, Any]:
        item = CATALOG[spec["sku"]]
        tag = f"{scenario}_{now_iso().replace(':', '')}"
        if spec["channel"] == "human":
            self.seed_human()
            self._vault(ARJUN, "saved-card", "CARD", spec["card"], tag)
            status, body = self.svc.merchant_charge(ARJUN, spec["sku"], "saved-card")
            return {"scenario": scenario, **spec, "intent_id": body.get("intent_id"),
                    "status": status, "result": body}

        reg = self._maya()
        self._vault(reg["customer_id"], "primary-card", "CARD", spec["card"], tag)
        self._vault(reg["customer_id"], "paypal-wallet", "PAYPAL_WALLET", None, tag)
        if spec.get("wallet_declines"):
            if not isinstance(self.svc.paypal, FixturePayPal):
                raise JudgeError(409, "S3's wallet decline needs negative testing (sandbox header); "
                                 "not wired for live mode yet")
            self.svc.paypal.force_decline(f"jv_{tag}_paypal-wallet", spec["wallet_declines"])
        if self.buyer is None:
            raise JudgeError(409, "BUYER_PUBLIC_URL not configured")
        r = self.buyer.post("/buyer/purchases", json={
            "merchant_id": self.svc.s.merchant_id, "sku": spec["sku"], "category": item["category"],
            "amount_minor": item["price_minor"], "currency_code": "USD", "quantity": 1})
        if r.status_code != 200:
            raise JudgeError(502, f"buyer purchase failed: {r.status_code} {r.text[:200]}")
        body = r.json()
        return {"scenario": scenario, **spec, "intent_id": body.get("intent_id"),
                "status": r.status_code, "result": body}

    def linked(self, intent_id: str) -> dict[str, Any]:
        merchant = linked_merchant_side(self.svc.db, intent_id)
        if merchant is None:
            raise JudgeError(404, "unknown intent")
        buyer = None
        if self.buyer is not None and merchant["intent"]["channel"] == "agent":
            try:
                r = self.buyer.get(f"/buyer/by-intent/{intent_id}")
                buyer = r.json() if r.status_code == 200 else None
            except httpx.HTTPError:
                buyer = None
        timeline = list(merchant["timeline"])
        if buyer:
            for g in buyer.get("guard_decisions", []):
                timeline.append({"at": g.get("created_at"), "side": "buyer", "stage": "GUARD",
                                 "detail": {k: g.get(k) for k in ("result", "rule_fired", "reason")}})
            for o in buyer.get("offers", []):
                timeline.append({"at": o.get("received_at"), "side": "buyer", "stage": "OFFER_RECEIVED",
                                 "detail": {"signature_ok": o.get("signature_ok"),
                                            "scanner_flags": o.get("scanner_flags")}})
        timeline.sort(key=lambda e: e.get("at") or "")
        return {"merchant": merchant, "buyer": buyer, "timeline": timeline}
