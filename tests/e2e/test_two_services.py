"""Both services end to end, in-process: the real buyer agent (buyer_agent.app) talks
PRP to the real merchant (merchant.app) over an ASGI transport. Fixture PayPal.

This is the cross-team contract test: if either side changes a body shape, a
header or a signing rule, it fails here.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from buyer_agent.app import create_app as create_buyer
from buyer_agent.db import BuyerDB
from merchant.app import create_app as create_merchant
from merchant.config import Settings
from merchant.db import Database
from merchant.paypal import FixturePayPal
from merchant.service import MerchantService

MERCHANT = "http://merchant.test"

MANDATE = {
    "mandate_id": "mdt_01JD3E2EMAYA0000",
    "principal": {"display_name": "Maya"},
    "merchant_scope": ["mer_kettle_crumb"],
    "currency_code": "USD",
    "budget": {"period": "WEEK", "limit_minor": 6000},
    "per_purchase_cap_minor": 5000,
    "allowed_categories": ["coffee", "tea", "brewing-supplies"],
    "funding": [{"alias": "primary-card", "kind": "CARD", "priority": 1},
                {"alias": "paypal-wallet", "kind": "PAYPAL_WALLET", "priority": 2}],
    "recovery": {"allow_alternate_funding": True, "allow_retry_after": False,
                 "max_autonomous_recoveries_per_purchase": 1,
                 "always_escalate_classes": ["RISK_BLOCKED", "AUTH_FAILURE", "UNKNOWN"]},
    "expires_at": "2027-02-20T00:00:00Z",
}


class Pair:
    def __init__(self, tmp_path, card_trigger: str | None) -> None:
        cfg = Settings(_env_file=None, merchant_db_path=tmp_path / "m.db", pact_mode="autonomous",
                       holdout_rate=0.0, llm_api_key="", paypal_client_id="")
        self.paypal = FixturePayPal()
        self.svc = MerchantService(cfg, Database(cfg.merchant_db_path), self.paypal,
                                   predict=lambda events: [0.9 for _ in events])
        merchant_app = create_merchant(self.svc, cfg=cfg)
        http = httpx.AsyncClient(transport=httpx.ASGITransport(app=merchant_app), base_url=MERCHANT)
        self.buyer = TestClient(create_buyer(db=BuyerDB(tmp_path / "b.db"), http=http))

        assert self.buyer.post("/buyer/mandates/draft", json=MANDATE).status_code == 201
        assert self.buyer.post(f"/buyer/mandates/{MANDATE['mandate_id']}/activate").status_code == 200
        r = self.buyer.post("/buyer/merchants/mer_kettle_crumb/connect",
                            json={"base_url": MERCHANT, "callback": False})
        assert r.status_code == 200, r.text
        token = r.json()["approval_url"].rsplit("/", 1)[1]

        # Maya's onboarding on the merchant page: save sources with PayPal, approve caps.
        cust = self.svc.db.one("SELECT customer_id FROM agent_registrations WHERE onboarding_token=?",
                               (token,))["customer_id"]
        self.paypal.add_vaulted("v_card", "CARD", cust, card_trigger)
        self.paypal.add_vaulted("v_wallet", "PAYPAL_WALLET", cust)
        self.svc.save_funding(cust, "primary-card", "CARD", "v_card")
        self.svc.save_funding(cust, "paypal-wallet", "PAYPAL_WALLET", "v_wallet")
        assert self.svc.onboarding_confirm(token, "SANDBOXPAYER123")[0] == 200

    def buy(self, sku="beans-ethiopia-1kg", category="coffee", amount=3200) -> dict:
        r = self.buyer.post("/buyer/purchases", json={
            "merchant_id": "mer_kettle_crumb", "sku": sku, "category": category,
            "amount_minor": amount, "currency_code": "USD", "quantity": 1})
        assert r.status_code == 200, r.text
        return r.json()

    def outcome(self, intent_id: str) -> str | None:
        row = self.svc.db.one("SELECT outcome FROM outcomes WHERE intent_id=?", (intent_id,))
        return row["outcome"] if row else None


def test_s1_agent_recovers_with_no_human(tmp_path):
    pair = Pair(tmp_path, "CCREJECT-IF")
    result = pair.buy()
    assert pair.outcome(result["intent_id"]) == "RECOVERED"
    view = pair.buyer.get(f"/buyer/by-intent/{result['intent_id']}").json()
    assert view["guard_decisions"][0]["result"] == "ACCEPT"
    assert "PayPal wallet" in view["guard_decisions"][0]["checklist"] or \
        "paypal-wallet" in view["guard_decisions"][0]["checklist"]


def test_s2_fraud_escalates_to_maya_with_a_paypal_link(tmp_path):
    pair = Pair(tmp_path, "CCREJECT-SF")
    result = pair.buy()
    assert pair.outcome(result["intent_id"]) is None             # nothing paid autonomously
    inbox = pair.buyer.get("/buyer/inbox").json()
    assert any((m.get("approve_url") or "").startswith("https://") for m in inbox)
    assert pair.svc.db.one("SELECT state FROM payment_intents WHERE intent_id=?",
                           (result["intent_id"],))["state"] == "ESCALATED_TO_HUMAN"


def test_s3_buyer_guard_stops_a_payment_the_merchant_would_retry(tmp_path):
    pair = Pair(tmp_path, "CCREJECT-REFUSED")
    pair.paypal.force_decline("v_wallet", "0500")
    result = pair.buy(sku="beans-colombia-1kg", amount=2800)
    view = pair.buyer.get(f"/buyer/by-intent/{result['intent_id']}").json()
    results = [g["result"] for g in view["guard_decisions"]]
    assert results[0] == "ACCEPT" and results[-1] == "ESCALATE"
    assert pair.outcome(result["intent_id"]) is None


def test_successful_purchase_is_not_a_recovery(tmp_path):
    pair = Pair(tmp_path, None)
    result = pair.buy()
    assert pair.outcome(result["intent_id"]) == "PAID"


@pytest.mark.parametrize("trigger", ["CCREJECT-IF"])
def test_offer_amount_matches_buyer_record(tmp_path, trigger):
    pair = Pair(tmp_path, trigger)
    result = pair.buy()
    view = pair.buyer.get(f"/buyer/by-intent/{result['intent_id']}").json()
    for offer in view["offers"]:
        body = offer["body"] if isinstance(offer["body"], dict) else __import__("json").loads(offer["body"])
        assert body["amount"]["value_minor"] == view["amount_minor"]
