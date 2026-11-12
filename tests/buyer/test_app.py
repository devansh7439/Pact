"""buyer-agent HTTP API against a signing fake merchant."""

import json
from datetime import timedelta

import httpx
from fastapi.testclient import TestClient

from buyer_agent import fixtures as fx
from buyer_agent.app import create_app
from buyer_agent.db import BuyerDB
from shared.prp import keys, signing

NOW = fx.T0 + timedelta(minutes=1)
TS = int(NOW.timestamp())
MER_KID = "mer_kettle_crumb#k1"
AGT_KEY = keys.generate()
AGT_KID = "agt_maya#k1"

PAID = {"prp_version": "0.1", "intent_id": fx.INTENT_ID, "status": "COMPLETED",
        "paypal_order_id": "5O190127TN364715T", "amount": {"currency_code": "USD", "value_minor": 3200}}


class Merchant:
    def __init__(self):
        self.key = keys.generate()
        self.calls = []
        self.script = []
        self.register_conflict = False

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/store/catalog":
            return httpx.Response(200, json={"items": [
                {"sku": "eth-1kg", "name": "Ethiopian Yirgacheffe 1 kg", "category": "coffee", "price_minor": 3200},
                {"sku": "kettle", "name": "Gooseneck kettle", "category": "brewing-supplies", "price_minor": 4500},
            ]})
        body = json.loads(req.content) if req.content else None
        self.calls.append((req.method, path, body))
        if path == "/agent/v1/register" and self.register_conflict:
            status, resp = 409, {"prp_version": "0.1",
                                 "error": {"code": "OUTSIDE_MANDATE", "message": "agent already registered"}}
        elif path == "/agent/v1/register":
            status, resp = 201, {
                "prp_version": "0.1", "agent_id": body["agent_id"], "merchant_id": fx.MERCHANT_ID,
                "merchant_name": fx.MERCHANT_NAME, "merchant_public_key": keys.public_to_b64(self.key.public_key()),
                "merchant_key_id": MER_KID, "approval_url": "http://merchant.test/onboard/onb_x",
                "registration_status": "PENDING_APPROVAL"}
        else:
            status, resp = self.script.pop(0)
        msg = signing.sign(self.key, MER_KID, req.method, path, resp, timestamp=TS)
        return httpx.Response(status, content=msg.body, headers=msg.headers)


def setup():
    m = Merchant()
    http = httpx.AsyncClient(transport=httpx.MockTransport(m.handler))
    app = create_app(db=BuyerDB(), http=http, signing_key_b64=keys.private_to_b64(AGT_KEY), key_id=AGT_KID,
                     clock=lambda: NOW)
    c = TestClient(app)
    assert c.post("/buyer/mandates/draft", json=fx.mandate_dict()).status_code == 201
    assert c.post(f"/buyer/mandates/{fx.MANDATE_ID}/activate").json()["status"] == "ACTIVE"
    r = c.post(f"/buyer/merchants/{fx.MERCHANT_ID}/connect", json={"base_url": "http://merchant.test"})
    assert r.status_code == 200, r.text
    assert r.json()["approval_url"].endswith("/onboard/onb_x")
    return m, c


def test_health_and_mandates():
    _, c = setup()
    h = c.get("/health").json()
    assert h["agent_key_id"] == AGT_KID and h["signing_key"] == "configured"
    assert c.get("/buyer/mandates").json()[0]["status"] == "ACTIVE"
    assert c.post("/buyer/mandates/draft", json={"mandate_id": "bad"}).status_code == 422


def test_mandate_drafted_from_words_with_template():
    _, c = setup()
    r = c.post("/buyer/mandates/draft", json={"text": "keep me stocked on beans, ~$60 a week, max $50 per order"})
    assert r.status_code == 201, r.text
    m = r.json()["mandate"]
    assert m["budget"] == {"period": "WEEK", "limit_minor": 6000}
    assert m["per_purchase_cap_minor"] == 5000 and m["allowed_categories"] == ["coffee"]
    assert "RISK_BLOCKED" in m["recovery"]["always_escalate_classes"]
    assert c.post("/buyer/mandates/draft", json={"text": "buy me stuff"}).status_code == 422


def test_reregister_error_surfaces_merchant_status_not_bad_signature():
    m, c = setup()
    m.register_conflict = True
    r = c.post(f"/buyer/merchants/{fx.MERCHANT_ID}/connect", json={"base_url": "http://merchant.test"})
    assert r.status_code == 409  # verified against the pinned key, real status surfaced
    assert "already registered" in r.text


def test_register_sends_signed_public_key():
    m, _ = setup()
    reg = m.calls[0][2]
    assert reg["agent_public_key"] == keys.public_to_b64(AGT_KEY.public_key())
    assert reg["mandate"]["mandate_id"] == fx.MANDATE_ID and reg["callback_url"].endswith("/prp/callback")


def test_s1_purchase_and_linked_view():
    m, c = setup()
    m.script = [(402, fx.s1_offer()), (200, PAID)]
    r = c.post("/buyer/purchases", json={"merchant_id": fx.MERCHANT_ID, "sku": "eth-1kg", "category": "coffee",
                                         "amount_minor": 3200}).json()
    assert (r["status"], r["outcome"]) == ("PAID", "RECOVERED")
    view = c.get(f"/buyer/by-intent/{fx.INTENT_ID}").json()
    checklist = view["guard_decisions"][0]["checklist"]
    assert checklist.startswith("Recovery offer from Kettle & Crumb · $32.00")
    assert "✓ Within this week's budget ($32.00 needed, $60.00 left)" in checklist
    assert checklist.endswith("→ Accepted automatically")
    assert json.loads(view["offers"][0]["body"])["offer_id"] == fx.OFFER_ID
    b = c.get("/buyer/budget").json()
    assert (b["spent_minor"], b["remaining_minor"]) == (3200, 2800)


def test_chat_uses_template_shopper():
    m, c = setup()
    m.script = [(200, PAID)]
    r = c.post("/buyer/chat", json={"message": "order a 1 kg bag of the Ethiopian"}).json()
    assert r["purchase"]["status"] == "PAID"
    assert m.calls[-1][2]["sku"] == "eth-1kg"


def test_pause_resume_and_inbox():
    m, c = setup()
    c.post("/buyer/pause")
    r = c.post("/buyer/purchases", json={"merchant_id": fx.MERCHANT_ID, "sku": "eth-1kg", "category": "coffee",
                                         "amount_minor": 3200}).json()
    assert r["status"] == "BLOCKED"
    msg = c.get("/buyer/inbox").json()[0]
    assert c.post(f"/buyer/inbox/{msg['msg_id']}/dismiss").status_code == 200
    assert c.get("/buyer/inbox").json() == []
    assert c.post("/buyer/resume").json() == {"paused": False}


def test_registration_active_callback_activates_mandate():
    m = Merchant()
    http = httpx.AsyncClient(transport=httpx.MockTransport(m.handler))
    c = TestClient(create_app(db=BuyerDB(), http=http, signing_key_b64=keys.private_to_b64(AGT_KEY),
                              key_id=AGT_KID, clock=lambda: NOW))
    c.post("/buyer/mandates/draft", json=fx.mandate_dict())
    assert c.post(f"/buyer/merchants/{fx.MERCHANT_ID}/connect", json={"base_url": "http://merchant.test"}).status_code == 200
    assert c.get("/buyer/mandates").json()[0]["status"] == "DRAFT"
    ev = {"prp_version": "0.1", "event": "registration.active", "mandate_id": fx.MANDATE_ID}
    msg = signing.sign(m.key, MER_KID, "POST", "/prp/callback", ev, timestamp=TS)
    assert c.post("/prp/callback", content=msg.body, headers=msg.headers).status_code == 200
    assert c.get("/buyer/mandates").json()[0]["status"] == "ACTIVE"


def test_callback_requires_merchant_signature_and_marks_paid():
    m, c = setup()
    m.script = [(402, fx.s1_offer(failure={"class": "RISK_BLOCKED"})),
                (202, {"prp_version": "0.1", "approve_url": "https://www.sandbox.paypal.com/x"})]
    r = c.post("/buyer/purchases", json={"merchant_id": fx.MERCHANT_ID, "sku": "eth-1kg", "category": "coffee",
                                         "amount_minor": 3200}).json()
    assert r["status"] == "ESCALATED"
    event = {"prp_version": "0.1", "event": "intent.updated", "intent_id": fx.INTENT_ID, "outcome": "RECOVERED_BY_HUMAN"}

    forged = signing.sign(keys.generate(), MER_KID, "POST", "/prp/callback", event, timestamp=TS)
    assert c.post("/prp/callback", content=forged.body, headers=forged.headers).status_code == 401

    good = signing.sign(m.key, MER_KID, "POST", "/prp/callback", event, timestamp=TS)
    resp = c.post("/prp/callback", content=good.body, headers=good.headers)
    assert resp.status_code == 200
    p = c.get(f"/buyer/by-intent/{fx.INTENT_ID}").json()
    assert (p["status"], p["outcome"]) == ("PAID", "RECOVERED_BY_HUMAN")
    assert c.get("/buyer/budget").json()["spent_minor"] == 3200
    # replay of the same callback is refused
    assert c.post("/prp/callback", content=good.body, headers=good.headers).status_code == 401
