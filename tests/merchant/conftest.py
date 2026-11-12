"""A merchant app on a temp DB with fixture PayPal, plus a signing test agent."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from merchant.app import create_app
from merchant.config import Settings
from merchant.db import Database
from merchant.paypal import FixturePayPal
from merchant.service import Clock, MerchantService
from shared.prp import keys, signing

MANDATE = {
    "mandate_id": "mdt_01JD3TESTMAYA00",
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


class Box:
    """Mutable clock for expiry tests."""

    def __init__(self) -> None:
        self.t = datetime.now(timezone.utc)

    def __call__(self) -> datetime:
        return self.t


@dataclass
class Agent:
    client: TestClient
    key: object = field(default_factory=keys.generate)
    agent_id: str = "agt_maya01"
    merchant_pub: object = None

    @property
    def key_id(self) -> str:
        return f"{self.agent_id}#k1"

    def call(self, method: str, path: str, body=None, *, key=None, key_id=None, headers=None):
        msg = signing.sign(key or self.key, key_id or self.key_id, method, path, body)
        r = self.client.request(method, path, content=msg.body or None,
                                headers={**msg.headers, **(headers or {})})
        if self.merchant_pub is not None and r.content:
            # Every merchant response is signed with the request's method and path.
            signing.verify(r.headers, method, path, r.content,
                           lambda kid: self.merchant_pub, signing.MemoryNonceStore())
        return r

    def register(self, mandate=None):
        body = {"prp_version": "0.1", "agent_id": self.agent_id, "agent_key_id": self.key_id,
                "agent_public_key": keys.public_to_b64(self.key.public_key()),
                "mandate": mandate or MANDATE, "callback_url": None}
        r = self.call("POST", "/agent/v1/register", body)
        if r.status_code == 201:
            self.merchant_pub = keys.public_from_b64(r.json()["merchant_public_key"])
        return r

    def checkout(self, sku="beans-ethiopia-1kg", qty=1, alias="primary-card", key="k1",
                 amount=None):
        from merchant.catalog import price
        body = {"prp_version": "0.1", "mandate_id": MANDATE["mandate_id"], "sku": sku,
                "quantity": qty, "amount": {"currency_code": "USD",
                                            "value_minor": amount or price(sku, qty)},
                "funding_alias": alias, "idempotency_key": f"chk_{key}"}
        return self.call("POST", "/agent/v1/checkout", body)

    def accept(self, offer, option_id, alias=None, idem=None):
        body = {"prp_version": "0.1", "offer_id": offer["offer_id"], "option_id": option_id,
                "mandate_id": MANDATE["mandate_id"], "agent_decision_ref": "gd_01JD4KTESTREF0",
                "idempotency_key": idem or f"acc_{offer['offer_id']}_{option_id}"}
        if alias:
            body["funding_alias"] = alias
        return self.call("POST", f"/agent/v1/offers/{offer['offer_id']}/accept", body)


@dataclass
class World:
    svc: MerchantService
    paypal: FixturePayPal
    client: TestClient
    agent: Agent
    clock: Box

    def onboard(self, card_trigger: str | None = "CCREJECT-IF", wallet: bool = True) -> None:
        """Register Maya's agent and approve her mandate with fixture-vaulted sources."""
        r = self.agent.register()
        assert r.status_code == 201, r.text
        token = r.json()["approval_url"].rsplit("/", 1)[1]
        reg = self.svc.db.one("SELECT customer_id FROM agent_registrations WHERE onboarding_token=?",
                              (token,))
        cust = reg["customer_id"]
        self.paypal.add_vaulted("vault_card", "CARD", cust, card_trigger)
        self.svc.save_funding(cust, "primary-card", "CARD", "vault_card")
        if wallet:
            self.paypal.add_vaulted("vault_wallet", "PAYPAL_WALLET", cust)
            self.svc.save_funding(cust, "paypal-wallet", "PAYPAL_WALLET", "vault_wallet")
        assert self.svc.onboarding_confirm(token, "SANDBOXPAYER123")[0] == 200

    def audit_stages(self, intent_id: str) -> list[str]:
        return [r["stage"] for r in self.svc.db.query(
            "SELECT stage FROM audit_trail WHERE intent_id=? ORDER BY seq", (intent_id,))]


@pytest.fixture
def world(tmp_path) -> World:
    cfg = Settings(_env_file=None, merchant_db_path=tmp_path / "m.db", pact_mode="autonomous",
                   holdout_rate=0.0, llm_api_key="", paypal_client_id="")
    paypal = FixturePayPal()
    clock = Box()
    svc = MerchantService(cfg, Database(cfg.merchant_db_path), paypal, clock=Clock(clock),
                          predict=lambda events: [0.9 for _ in events])
    client = TestClient(create_app(svc, cfg=cfg))
    return World(svc, paypal, client, Agent(client), clock)


def body(r) -> dict:
    return json.loads(r.content)


def later(world: World, minutes: int) -> None:
    world.clock.t += timedelta(minutes=minutes)
